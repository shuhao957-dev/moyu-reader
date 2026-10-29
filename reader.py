import webview
import sys
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
import json
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from settings import get_settings_html

class BookReader:
    def __init__(self, data_dir=None):
        self.content = ""
        self.current_file = None
        data_dir = Path(data_dir) if data_dir is not None else Path.home()
        self.progress_file = data_dir / '.moyu_reader_progress.json'
        self.config_file = data_dir / '.moyu_reader_config.json'
        self._window = None
        self._reader_size = None
        # 自研 pointer 拖动状态（取代 pywebview easy_drag）
        self._drag_anchor = None   # (win_left, win_top, anchor_screen_x, anchor_screen_y, dpi_scale)
        self._drag_hwnd = None
        self._drag_lock = threading.Lock()
        self.progress = {}
        self.sense = MouseSenseController(self)
        self.load_progress()
        self.load_config()

    DEFAULT_CONFIG = {
        'window': {'width': 400, 'height': 60, 'x': 100, 'y': 100},
        'speed': 50,
        'mouse_sense': False,
        'font_size': 14,
        'text_color': '#333333',
        'text_opacity': 100,
    }

    def load_config(self):
        """加载配置文件"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            else:
                self.config = self.DEFAULT_CONFIG
        except:
            self.config = self.DEFAULT_CONFIG
        # 老配置文件补齐新增字段的默认值
        for key, value in self.DEFAULT_CONFIG.items():
            self.config.setdefault(key, value)

    def load_progress(self):
        """加载阅读进度"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    self.progress = json.load(f)
            except:
                self.progress = {}

    def save_progress(self, file_path, position):
        """保存阅读进度"""
        self.progress[file_path] = position
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(self.progress, f, indent=4, ensure_ascii=False)
        except:
            pass

    def get_progress(self, file_path):
        """获取阅读进度。先查全路径，再回退短文件名（兼容旧数据）"""
        pos = self.progress.get(file_path, None)
        if pos is not None:
            return pos
        # Fallback: old versions stored progress under short filename
        short_name = Path(file_path).name
        pos = self.progress.get(short_name, 0)
        if pos > 0:
            # Migrate old entry to full path key
            self.progress[file_path] = pos
            del self.progress[short_name]
            self._save_progress_sync()
        return pos

    def _save_progress_sync(self):
        """Internal: flush progress dict to disk immediately"""
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(self.progress, f, indent=4, ensure_ascii=False)
        except:
            pass

    def get_config(self):
        return self.config

    SETTINGS_SIZE = (420, 660)

    @staticmethod
    def _work_area():
        """屏幕工作区（排除任务栏）。取不到时逐级退回：主屏尺寸 → 保守默认值。"""
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
        try:
            import ctypes
            sm = ctypes.windll.user32.GetSystemMetrics
            return 0, 0, sm(0), sm(1)
        except Exception:
            return 0, 0, 1920, 1080

    def open_settings(self):
        self.sense.suspend()  # 设置窗口打开期间暂停鼠标感应隐身
        win = self._window
        if self._reader_size is None:
            # 记录阅读时的位置和尺寸，关闭设置后原样恢复
            self._reader_size = (win.x, win.y, win.width, win.height)
        w, h = self.SETTINGS_SIZE
        left, top, right, bottom = self._work_area()
        # 把拉大后的设置窗口平移到工作区内，避免贴边时按钮被顶出屏幕
        x = max(left, min(win.x, right - w))
        y = max(top, min(win.y, bottom - h))
        try:
            win.resize(w, h)
            win.move(x, y)
        except Exception:
            pass  # 拖不动也不影响：Esc/点空白仍可退出设置
        return self.config

    def close_settings(self):
        self.sense.resume()
        if self._reader_size is not None:
            x, y, w, h = self._reader_size
            try:
                self._window.resize(w, h)
                self._window.move(x, y)
            except Exception:
                pass
            self._reader_size = None

    def sense_toggle(self):
        """Ctrl+H 兜底开关：运行时切换鼠标感应模式（不写配置文件）"""
        return self.sense.toggle()

    # ---------- 自研窗口拖动（pointer 事件链） ----------
    # 背景：pywebview 的 easy_drag 只监听 mousedown/mousemove 且不做指针捕获，
    # 在触摸屏一体机（合成鼠标事件不连续）和快速拖动（光标跑出小窗口导致
    # mousemove 断流）场景下会"拖不动"。改为 JS 侧 pointer 事件 + setPointerCapture，
    # 鼠标/触摸/触控笔统一走本链路，Python 侧用锚点式 SetWindowPos 移动。

    @staticmethod
    def _drag_scale(hwnd):
        """窗口 DPI 缩放系数（JS screenX 是 DIP，win32 坐标是物理像素）"""
        try:
            import ctypes
            dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
            if dpi and dpi >= 96:
                return dpi / 96.0
        except Exception:
            pass
        return 1.0

    def drag_begin(self, screen_x, screen_y):
        """pointerdown：记录窗口当前原点与指针屏幕坐标作为拖动锚点"""
        try:
            import ctypes
            from ctypes import wintypes
            win = self._window
            if win is None:
                return False
            hwnd = win.native.Handle.ToInt64()
            rect = wintypes.RECT()
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return False
            self._drag_hwnd = hwnd
            self._drag_anchor = (rect.left, rect.top,
                                 float(screen_x), float(screen_y),
                                 self._drag_scale(hwnd))
            return True
        except Exception:
            return False

    def drag_move(self, screen_x, screen_y):
        """pointermove：按锚点把窗口挪到目标位置。
        每次调用经 js_api 各起一个线程，故用非阻塞锁丢帧——锚点式计算丢帧无损。"""
        anchor = self._drag_anchor
        if anchor is None or self._drag_hwnd is None:
            return False
        if not self._drag_lock.acquire(False):
            return False  # 上一帧还在搬，跳过本帧
        try:
            import ctypes
            win_left, win_top, ax, ay, scale = anchor
            x = int(win_left + (float(screen_x) - ax) * scale)
            y = int(win_top + (float(screen_y) - ay) * scale)
            SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
            ctypes.windll.user32.SetWindowPos(
                self._drag_hwnd, None, x, y, None, None,
                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            return True
        except Exception:
            return False
        finally:
            self._drag_lock.release()

    def drag_end(self):
        """pointerup / pointercancel：结束拖动"""
        self._drag_anchor = None
        return True

    def apply_settings(self, width, height, speed, mouse_sense=None,
                       font_size=None, text_color=None, text_opacity=None):
        try:
            width, height, speed = int(width), int(height), int(speed)
            if not (150 <= width <= 1200 and 20 <= height <= 600 and 10 <= speed <= 200):
                raise ValueError('设置超出允许范围')
        except (TypeError, ValueError, OverflowError):
            return {'success': False, 'message': '宽度须为 150–1200，高度须为 20–600，速度须为 10–200。'}

        # 文字样式：未传参时保持现值（兼容旧调用方）
        if font_size is None:
            font_size = self.config.get('font_size', 14)
        if text_color is None:
            text_color = self.config.get('text_color', '#333333')
        if text_opacity is None:
            text_opacity = self.config.get('text_opacity', 100)
        try:
            font_size, text_opacity = int(font_size), int(text_opacity)
            if not (10 <= font_size <= 48):
                raise ValueError('字号')
            if not (20 <= text_opacity <= 100):
                raise ValueError('透明度')
            if not (isinstance(text_color, str)
                    and re.fullmatch(r'#[0-9a-fA-F]{6}', text_color)):
                raise ValueError('颜色')
        except (TypeError, ValueError, OverflowError):
            return {'success': False, 'message': '字号须为 10–48，不透明度须为 20–100，颜色须为 #RRGGBB。'}

        config = {**self.config,
                  'window': {**self.config['window'], 'width': width, 'height': height},
                  'speed': speed,
                  'font_size': font_size,
                  'text_color': text_color,
                  'text_opacity': text_opacity}
        if mouse_sense is not None:
            config['mouse_sense'] = bool(mouse_sense)
        try:
            self.config_file.write_text(json.dumps(config, indent=4, ensure_ascii=False), encoding='utf-8')
        except OSError as error:
            return {'success': False, 'message': f'保存失败：{error}'}
        self.config = config
        if self._reader_size is not None:
            # 设置面板开着时保存了新尺寸：更新待恢复的阅读窗口尺寸（位置不变）
            self._reader_size = (*self._reader_size[:2], width, height)
        if mouse_sense is not None and bool(mouse_sense) != self.sense.enabled:
            self.sense.set_enabled(bool(mouse_sense))
        # 文字样式立即生效
        if self._window is not None:
            try:
                self._window.evaluate_js(
                    f'applyFontStyle({font_size}, {json.dumps(text_color)}, {text_opacity})')
            except Exception:
                pass
        return {'success': True, 'config': config}

    @staticmethod
    def _decode_score(s):
        """给解码结果打分：常用字符（中文/中文标点/可打印ASCII）占比越高越好"""
        if not s:
            return 0.0
        good = 0
        for ch in s:
            o = ord(ch)
            if (0x4E00 <= o <= 0x9FFF      # CJK 统一表意文字
                    or 0x3000 <= o <= 0x303F  # 中文标点
                    or 0xFF00 <= o <= 0xFFEF  # 全角字符
                    or 0x20 <= o <= 0x7E      # 可打印 ASCII
                    or ch in '\n\r\t'):
                good += 1
        return good / len(s)

    def load_txt(self, file_path):
        """加载TXT文件，自动检测编码（BOM优先，支持UTF-16/UTF-8/GB18030）。
        任何编码问题都不会抛异常：最坏显示替换字符或乱码，而不是打不开。"""
        with open(file_path, 'rb') as f:
            raw = f.read()

        # UTF-16 要求偶数字节；文件被截断多出 1 字节时先去掉
        utf16_raw = raw[:-1] if len(raw) % 2 else raw

        # BOM 信息（有 BOM 的文件优先按 BOM 编码严格解码）
        bom_enc, bom_data = None, None
        if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
            bom_enc, bom_data = 'utf-16', utf16_raw
        elif raw.startswith(b'\xef\xbb\xbf'):
            bom_enc, bom_data = 'utf-8-sig', raw

        content = None
        # 1. BOM 严格解码
        if bom_enc:
            try:
                content = bom_data.decode(bom_enc)
            except UnicodeDecodeError:
                content = None

        # 2. UTF-8 严格解码（无 BOM 或 BOM 解码失败时）
        if content is None:
            try:
                content = raw.decode('utf-8')
            except UnicodeDecodeError:
                # 3. 竞争打分：GB18030 / UTF-16LE / UTF-16BE 谁解出来更"像中文"用谁
                best = None
                for enc, data in (('gb18030', raw), ('utf-16-le', utf16_raw), ('utf-16-be', utf16_raw)):
                    try:
                        text = data.decode(enc)
                    except UnicodeDecodeError:
                        continue
                    score = self._decode_score(text)
                    if best is None or score > best[0]:
                        best = (score, text)
                if best is not None and best[0] > 0.6:
                    content = best[1]

        # 4. 最终兜底（保证不抛异常）：有 BOM 就替换坏字符解码，否则忽略错误解码
        if content is None:
            try:
                content = bom_data.decode(bom_enc, errors='replace') if bom_enc else raw.decode('utf-8', errors='ignore')
            except (UnicodeDecodeError, ValueError):
                content = raw.decode('utf-8', errors='ignore')

        self.content = content

        self.content = '\n'.join(line.strip() for line in self.content.split('\n') if line.strip())
        self.current_file = file_path
        return True

    def load_epub(self, file_path):
        """加载EPUB文件"""
        try:
            book = epub.read_epub(file_path)
            text_parts = []

            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    text = soup.get_text()
                    text_parts.append(text)

            self.content = '\n'.join(text_parts)
            self.content = '\n'.join(line.strip() for line in self.content.split('\n') if line.strip())
            self.current_file = file_path
            return True
        except Exception as e:
            return False

    def open_file(self):
        """打开文件对话框"""
        file_types = ('Text Files (*.txt)', 'EPUB Files (*.epub)', 'All Files (*.*)')
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)

        if result and len(result) > 0:
            file_path = result[0]
            ext = Path(file_path).suffix.lower()

            if ext == '.txt':
                if self.load_txt(file_path):
                    saved_position = self.get_progress(file_path)
                    return {'success': True, 'content': self.content, 'filename': Path(file_path).name, 'filepath': file_path, 'position': saved_position}
            elif ext == '.epub':
                if self.load_epub(file_path):
                    saved_position = self.get_progress(file_path)
                    return {'success': True, 'content': self.content, 'filename': Path(file_path).name, 'filepath': file_path, 'position': saved_position}

            return {'success': False, 'error': '不支持的文件格式'}

        return {'success': False, 'error': '未选择文件'}




# ---------------------------------------------------------------------------
# Dependency self-check: auto-install WebView2 / .NET if missing
# ---------------------------------------------------------------------------

def _is_webview2_installed():
    """Check if WebView2 runtime is installed via Windows registry.

    Microsoft has used multiple GUIDs for WebView2 over time.
    We check all known ones + fall back to checking the DLL path.
    """
    # Known WebView2 Runtime GUIDs (varies by installer version/channel)
    WEBVIEW2_GUIDS = [
        '{F3017226-FE2A-4295-8BEB-3A2F0F6B5A7B}',  # Early Evergreen Standalone
        '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',  # Current Evergreen Standalone
    ]
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for wow64 in ('', 'WOW6432Node\\'):
                for guid in WEBVIEW2_GUIDS:
                    try:
                        key = winreg.OpenKey(
                            root,
                            rf'SOFTWARE\{wow64}Microsoft\EdgeUpdate\Clients\{guid}',
                        )
                        winreg.CloseKey(key)
                        return True
                    except (FileNotFoundError, OSError):
                        continue
    except ImportError:
        pass

    # Fallback: check if the EmbeddedFixedVersion DLL exists
    import glob
    dll_patterns = [
        os.path.expandvars(r'%ProgramFiles(x86)%\Microsoft\EdgeWebView\Application\*\EmbeddedFixedVersion.dll'),
        os.path.expandvars(r'%ProgramFiles%\Microsoft\EdgeWebView\Application\*\EmbeddedFixedVersion.dll'),
        os.path.expandvars(r'%LocalAppData%\Microsoft\EdgeWebView\Application\*\EmbeddedFixedVersion.dll'),
    ]
    for pattern in dll_patterns:
        if glob.glob(pattern):
            return True

    return False


def _is_dotnet8_desktop_installed():
    """Check if .NET 8 Desktop Runtime is installed (optional, for transparency)."""
    try:
        result = subprocess.run(
            ['dotnet', '--list-runtimes'],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        return 'Microsoft.WindowsDesktop.App 8.' in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _get_exe_dir():
    """Get directory of the running exe or script."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _msg_box(text, title='摸鱼阅读器', icon=0x40):
    """Show a Windows message box. icon: 0x10=error 0x30=warn 0x40=info 0x20=question"""
    import ctypes as _ct
    _ct.windll.user32.MessageBoxW(0, text, title, icon)


def _run_installer_elevated(installer_path):
    """Run an installer with UAC elevation via PowerShell. Returns True on success."""
    try:
        # PowerShell Start-Process -Verb RunAs handles UAC; -Wait blocks until done
        cmd = (
            f'powershell -ExecutionPolicy Bypass -Command '
            f'"Start-Process -FilePath \'{installer_path}\' -Verb RunAs -Wait"'
        )
        subprocess.run(
            cmd, shell=True, timeout=180,
            creationflags=0x08000000,  # CREATE_NO_WINDOW — hide PS console flash
        )
        return True
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def ensure_dependencies():
    """Check and auto-install missing dependencies. Returns True if OK to proceed."""
    import ctypes as _ct

    # --- WebView2 (required) ---
    if not _is_webview2_installed():
        exe_dir = _get_exe_dir()
        local_installer = os.path.join(exe_dir, 'MicrosoftEdgeWebview2Setup.exe')

        if os.path.exists(local_installer):
            installer = local_installer
        else:
            # No local installer — ask to download from Microsoft
            result = _ct.windll.user32.MessageBoxW(
                0,
                '摸鱼阅读器需要 WebView2 运行时才能运行。\n\n'
                '点击「确定」自动下载安装（约 2MB，需要网络）\n'
                '点击「取消」退出程序',
                '摸鱼阅读器',
                0x31,  # MB_OKCANCEL | MB_ICONQUESTION
            )
            if result != 1:  # not IDOK
                return False

            try:
                installer = os.path.join(
                    tempfile.gettempdir(), 'MicrosoftEdgeWebview2Setup.exe'
                )
                urllib.request.urlretrieve(
                    'https://go.microsoft.com/fwlink/p/?LinkId=2124703',
                    installer,
                )
            except Exception as e:
                _msg_box(
                    f'下载失败：{e}\n\n请手动安装 WebView2 后重试。',
                    icon=0x10,
                )
                return False

        # Run installer (with UAC elevation if needed)
        _run_installer_elevated(installer)

        # Verify installation
        if not _is_webview2_installed():
            _msg_box(
                'WebView2 安装似乎未成功。\n'
                '阅读器仍将尝试启动，但可能无法正常工作。',
                icon=0x30,  # MB_ICONWARNING
            )

    # --- .NET 8 Desktop Runtime (optional — only for transparency) ---
    if not _is_dotnet8_desktop_installed():
        # Already handled gracefully by enable_windows_transparency's try/except.
        # Just leave a quiet note; no blocking dialog.
        print('[摸鱼阅读器] .NET 8 Desktop Runtime 未安装，透明背景不可用（不影响阅读）')

    return True


def enable_windows_transparency(window):
    """Keep the WinForms host transparent when WebView2 resizes or restores.
    Requires pythonnet + .NET Desktop Runtime. Falls back gracefully if unavailable."""
    if sys.platform != 'win32' or webview.renderer != 'edgechromium':
        return

    try:
        import ctypes
        from ctypes import wintypes
        import clr
        clr.AddReference('System.Drawing')
        from System.Drawing import Color

        class Margins(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int) for name in ('left', 'right', 'top', 'bottom')]

        extend_frame = ctypes.WinDLL('dwmapi').DwmExtendFrameIntoClientArea
        extend_frame.argtypes = [wintypes.HWND, ctypes.POINTER(Margins)]
        extend_frame.restype = ctypes.c_long

        # Negative margins cover the entire client area, including future resizes.
        # A black host supplies zero-alpha pixels to DWM; WebView2 still draws text
        # and opaque controls normally. This is not a color-key transparency mask.
        margins = Margins(-1, -1, -1, -1)
        result = extend_frame(window.native.Handle.ToInt64(), ctypes.byref(margins))
        if result < 0:
            raise OSError(f'DwmExtendFrameIntoClientArea failed: 0x{result & 0xffffffff:08X}')
        window.native.BackColor = Color.Black
    except (ImportError, OSError, Exception) as e:
        # pythonnet / .NET Desktop Runtime not available — transparency disabled,
        # but the reader still works perfectly without it.
        print(f'[摸鱼阅读器] 透明背景未启用: {e}')
        print('[摸鱼阅读器] 提示: 安装 .NET Desktop Runtime 可启用透明背景效果')


class MouseSenseController:
    """鼠标感应模式：鼠标在窗口内 = 正常显示；离开超过 0.5 秒 = 窗口淡出 + 暂停滚动 + 点击穿透。

    实现要点：
    - 后台线程轮询全局鼠标坐标（GetCursorPos）与窗口矩形（GetWindowRect），
      不依赖窗口自身接收鼠标事件，因此隐身（点击穿透）状态下仍能感知鼠标回来。
    - 隐藏用"视觉隐身"（JS 淡出 + WS_EX_TRANSPARENT 点击穿透）而非 window.hide()，
      避免窗口消失后无法再触发的死锁。
    - 恢复滚动带 1 秒缓冲，防止鼠标路过窗口导致误触发。
    """

    POLL_INTERVAL = 0.2
    HIDE_DELAY = 0.5
    RESUME_DELAY = 1.0

    def __init__(self, reader):
        self.reader = reader
        self._window = None
        self._hwnd = None
        self._enabled = False
        self._suspended = False
        self._stop = threading.Event()
        self._thread = None

    @property
    def enabled(self):
        return self._enabled

    def attach(self, window):
        """窗口 shown 后（GUI 线程）调用，缓存原生句柄供 win32 调用使用"""
        self._window = window
        try:
            self._hwnd = window.native.Handle.ToInt64()
        except Exception:
            self._hwnd = None

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self._enabled:
            if not enabled:
                self._force_visible()
            return
        if enabled:
            self._enabled = True
            self._suspended = False
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name='moyu-mouse-sense', daemon=True)
            self._thread.start()
        else:
            self._enabled = False
            self._suspended = False
            self._stop.set()
            t = self._thread
            self._thread = None
            if t is not None and t is not threading.current_thread():
                t.join(timeout=2)
            self._force_visible()

    def suspend(self):
        """设置窗口打开等场景：强制可见并暂停隐身判定"""
        if not self._enabled:
            return
        self._suspended = True
        self._force_visible()

    def resume(self):
        self._suspended = False

    def toggle(self):
        self.set_enabled(not self._enabled)
        return self._enabled

    def _force_visible(self):
        self._set_click_through(False)
        self._eval_js('moyuSenseShow()')

    def _eval_js(self, code):
        try:
            if self._window is not None:
                self._window.evaluate_js(code)
        except Exception:
            pass  # 窗口关闭等竞态下静默失败

    def _set_click_through(self, on):
        """给窗口加/去 WS_EX_TRANSPARENT：开启后鼠标点击穿到下层窗口"""
        if sys.platform != 'win32' or not self._hwnd:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            style = user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
            if on:
                style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
            else:
                style &= ~WS_EX_TRANSPARENT  # LAYERED 保留（透明背景依赖）
            user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def _loop(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        pt = wintypes.POINT()
        rect = wintypes.RECT()
        hidden = False
        out_since = None
        resume_at = None
        while not self._stop.wait(self.POLL_INTERVAL):
            try:
                if self._suspended or not self._hwnd:
                    if hidden:
                        self._force_visible()
                        hidden = False
                    out_since = None
                    resume_at = None
                    continue
                if not user32.GetCursorPos(ctypes.byref(pt)):
                    continue
                if not user32.GetWindowRect(self._hwnd, ctypes.byref(rect)):
                    continue
                inside = rect.left <= pt.x < rect.right and rect.top <= pt.y < rect.bottom
                now = time.time()
                if inside:
                    out_since = None
                    if hidden:
                        # 鼠标回来了：先关穿透再淡入，滚动等缓冲后恢复
                        self._set_click_through(False)
                        self._eval_js('moyuSenseShow()')
                        hidden = False
                        resume_at = now + self.RESUME_DELAY
                    elif resume_at is not None and now >= resume_at:
                        self._eval_js('moyuSenseResume()')
                        resume_at = None
                else:
                    resume_at = None
                    if out_since is None:
                        out_since = now
                    elif not hidden and (now - out_since) >= self.HIDE_DELAY:
                        # 离开超过宽限期：JS 淡出+暂停，再开点击穿透
                        self._eval_js('moyuSenseHide()')
                        self._set_click_through(True)
                        hidden = True
            except Exception:
                continue  # 单次轮询异常不终止线程


def get_html():
    """返回HTML内容"""
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: "Microsoft YaHei", sans-serif;
            font-size: 14px;
            line-height: 1.6;
            color: #333;
            overflow: hidden;
            -webkit-app-region: drag;
            user-select: none;
            background: transparent;
            touch-action: none; /* 触摸拖窗口不被浏览器滚动手势截胡（截胡会发 pointercancel） */
        }

        #container {
            height: 100vh;
            display: flex;
            flex-direction: column;
            padding: 4px 8px;
            transition: opacity 0.4s;
        }

        /* 鼠标感应模式：隐身时整体淡出，面板和模式指示完全消失 */
        body.sense-hidden #container { opacity: 0; }
        body.sense-hidden #controls { display: none !important; }
        body.sense-hidden #mode-indicator { display: none; }

        #text-display {
            flex: 1;
            overflow: hidden;
            position: relative;
            cursor: pointer;
            -webkit-app-region: no-drag;
        }

        #text-content {
            white-space: pre-wrap;
            word-break: break-all;
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            transition: transform 0.1s linear;
        }

        #controls {
            position: fixed;
            top: 0;
            right: 0;
            padding: 4px;
            background: transparent;
            border-radius: 4px;
            font-size: 12px;
            -webkit-app-region: no-drag;
            z-index: 1000;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.5s;
        }

        #controls.show {
            opacity: 1;
            pointer-events: auto;
        }

        #controls button {
            background: transparent;
            color: #333;
            border: none;
        }

        #controls button:hover {
            background: transparent;
            color: #000;
            text-decoration: underline;
        }

        #controls button.active {
            background: transparent;
            color: #388E3C;
            border: none;
            font-weight: bold;
        }

        #controls label {
            color: #333;
        }

        #controls input[type="range"] {
            accent-color: #888;
        }

        #mode-indicator {
            position: fixed;
            top: 4px;
            left: 4px;
            padding: 3px 8px;
            background: rgba(100, 100, 100, 0.7);
            color: white;
            border-radius: 4px;
            font-size: 10px;
            -webkit-app-region: no-drag;
            z-index: 999;
            opacity: 0;
            transition: opacity 0.3s;
        }

        #mode-indicator.show {
            opacity: 1;
        }

        button {
            margin: 0 2px;
            padding: 2px 6px;
            font-size: 11px;
            cursor: pointer;
            border: 1px solid #ccc;
            background: white;
            border-radius: 3px;
        }

        button:hover {
            background: #f0f0f0;
        }

        button.active {
            background: #4CAF50;
            color: white;
            border-color: #4CAF50;
        }

        #speed-control {
            margin-top: 4px;
        }

        input[type="range"] {
            width: 100px;
            vertical-align: middle;
        }
    </style>
</head>
<body>
    <div id="container">
        <div id="mode-indicator">自动滚动</div>
        <div id="controls">
            <div>
                <button onclick="openFile()">打开</button>
                <button id="settings-btn" onclick="openSettings()" title="Ctrl+,">设置</button>
                <button id="mode-btn" onclick="toggleMode()" class="active">自动</button>
                <button id="pause-btn" onclick="togglePause()">暂停</button>
                <button onclick="closeApp()">关闭</button>
            </div>
            <div id="speed-control">
                <label>速度: <span id="speed-value">50</span></label>
                <input type="range" min="10" max="200" value="50" oninput="changeSpeed(this.value)">
            </div>
        </div>
        <div id="text-display" onclick="togglePause()">
            <div id="text-content">右键点击打开电子书...</div>
        </div>
    </div>

    <script>
        let content = '';
        let currentPosition = 0;
        let isPaused = false;
        let scrollSpeed = 50;
        let lastTimestamp = 0;
        let isAutoMode = true;
        // 行对齐分页：页首永远落在文字行边界上（行高的整数倍），不再维护"固定页高切片"的页数概念。
        // 窗口高度是用户随手调的，几乎不可能是行高整数倍；固定页高切片会把切缝处的一行腰斩成
        // 两半（上一页半行 + 下一页半行），两半都读不出来，效果就是跳过了一行。
        let currentFilePath = '';  // full path for progress tracking
        let currentFile = '';      // short name for display
        let scrollFrame = 0;
        let autoSaveInterval = null;
        // --- 鼠标感应模式状态（由 Python 端 MouseSenseController 驱动） ---
        let senseHidden = false;        // 当前是否处于感应隐身
        let sensePrevPaused = false;    // 隐藏时的暂停状态（恢复依据）
        let senseResumePending = false; // 淡入后是否待自动恢复滚动

        function startScroll() {
            if (!content || isPaused || scrollFrame) return;
            scrollFrame = requestAnimationFrame(scroll);
        }

        function scroll(timestamp) {
            scrollFrame = 0;
            if (!lastTimestamp) lastTimestamp = timestamp;
            const delta = timestamp - lastTimestamp;
            lastTimestamp = timestamp;

            if (!isPaused && content) {
                if (isAutoMode) {
                    currentPosition += (scrollSpeed / 1000) * delta;
                    const textElement = document.getElementById('text-content');
                    textElement.style.transform = `translateY(-${currentPosition}px)`;

                    const displayHeight = document.getElementById('text-display').offsetHeight;
                    const contentHeight = textElement.offsetHeight;

                    if (currentPosition > contentHeight + displayHeight) {
                        currentPosition = -displayHeight;
                    }
                }

                scrollFrame = requestAnimationFrame(scroll);
            }
        }

        function toggleMode() {
            isAutoMode = !isAutoMode;
            const modeBtn = document.getElementById('mode-btn');
            const indicator = document.getElementById('mode-indicator');

            if (isAutoMode) {
                modeBtn.textContent = '自动';
                modeBtn.classList.add('active');
                indicator.textContent = '自动滚动';
            } else {
                modeBtn.textContent = '手动';
                modeBtn.classList.remove('active');
                indicator.textContent = '手动翻页';
            }

            indicator.classList.add('show');
            setTimeout(() => indicator.classList.remove('show'), 1500);
        }

        // --- 行对齐分页的工具函数 ---
        function getLineHeight() {
            const el = document.getElementById('text-content');
            const lh = parseFloat(getComputedStyle(el).lineHeight);
            if (lh && lh > 4) return lh;
            // 兜底：极老内核对无单位 line-height 可能返回 "normal"，按 CSS 定义 1.6 倍字号推算
            const fs = parseFloat(getComputedStyle(el).fontSize) || 14;
            return fs * 1.6;
        }
        function viewHeight() {
            return document.getElementById('text-display').offsetHeight;
        }
        function contentHeight() {
            return document.getElementById('text-content').offsetHeight;
        }
        // 把任意 y 回退对齐到行边界（所在行的行首；进度恢复用，最多回退一行，不跳内容）
        function lineFloor(y) {
            const lh = getLineHeight();
            return Math.max(0, Math.floor(y / lh) * lh);
        }

        function togglePause() {
            senseResumePending = false;  // 任何手动/其他入口的暂停切换都取消待恢复
            isPaused = !isPaused;
            const pauseBtn = document.getElementById('pause-btn');
            if (isPaused) {
                cancelAnimationFrame(scrollFrame);
                scrollFrame = 0;
                pauseBtn.textContent = '继续';
            } else {
                pauseBtn.textContent = '暂停';
                lastTimestamp = 0;
                startScroll();
            }
        }

        function pageUp() {
            if (!isAutoMode && content) {
                if (currentPosition <= 0) return;
                const lh = getLineHeight();
                // pageDown(floor) 的镜像逆映射(ceil)：当前首行成为上一页的页尾腰斩行，
                // 再往上翻时它会完整重现——与下翻语义完全对称，来回翻页位置严格可逆
                let target = Math.ceil((currentPosition - viewHeight()) / lh) * lh;
                // 防御：视口不足一行时至少上翻一行
                if (target >= currentPosition) target = currentPosition - lh;
                currentPosition = Math.max(0, target);
                updatePagePosition();
                saveProgress();
            }
        }

        function pageDown() {
            if (!isAutoMode && content) {
                const lh = getLineHeight();
                // 下一页起点 = 视口底部所在行的行首（floor）：页尾被截断的行完整重现于下页开头，
                // 任何行都不会被跳过（ceil 会把腰斩行的下半截永远留在屏外，等于跳行）
                let target = Math.floor((currentPosition + viewHeight()) / lh) * lh;
                // 防御：视口不足一行时至少下翻一行
                if (target <= currentPosition) target = currentPosition + lh;
                // 剩余内容本页已显示完（下一页首行不存在）：到底，不再翻
                if (target >= contentHeight()) return;
                currentPosition = target;
                updatePagePosition();
                saveProgress();
            }
        }

        function updatePagePosition() {
            const textElement = document.getElementById('text-content');
            textElement.style.transform = `translateY(-${currentPosition}px)`;
        }

        function changeSpeed(value) {
            scrollSpeed = Number(value);
            document.getElementById('speed-value').textContent = value;
            document.querySelector('#speed-control input').value = value;
        }

        function saveProgress() {
            if (currentFilePath && content) {
                pywebview.api.save_progress(currentFilePath, currentPosition);
            }
        }

        // --- Auto-save every 5 seconds ---
        function startAutoSave() {
            if (autoSaveInterval) clearInterval(autoSaveInterval);
            autoSaveInterval = setInterval(() => {
                if (currentFilePath && content) {
                    saveProgress();
                }
            }, 5000);
        }

        function openFile() {
            pywebview.api.open_file().then(result => {
                if (result.success) {
                    content = result.content;
                    currentFile = result.filename;
                    currentFilePath = result.filepath;
                    currentPosition = result.position || 0;
                    isPaused = false;
                    lastTimestamp = 0;

                    document.getElementById('text-content').textContent = content;
                    // 手动模式：恢复进度时对齐到行边界——旧版本存的任意像素可能落在行中间，
                    // floor 回退让首行完整重读（最多回退一行，绝不跳内容）；自动模式保持任意像素平滑续滚
                    if (!isAutoMode) {
                        currentPosition = lineFloor(currentPosition);
                    }
                    document.getElementById('text-content').style.transform = `translateY(-${currentPosition}px)`;

                    startAutoSave();

                    if (isAutoMode) {
                        startScroll();
                    }
                } else {
                    alert(result.error || '打开文件失败');
                }
            }).catch(err => alert('打开文件出错：' + err));
        }

        function closeApp() {
            if (autoSaveInterval) clearInterval(autoSaveInterval);
            saveProgress();
            pywebview.api.close();
        }

        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === ',') {
                e.preventDefault();
                openSettings();
                return;
            }
            if (e.ctrlKey && (e.key === 'h' || e.key === 'H')) {
                e.preventDefault();
                pywebview.api.sense_toggle().then(enabled => {
                    const indicator = document.getElementById('mode-indicator');
                    indicator.textContent = enabled ? '鼠标感应：开' : '鼠标感应：关';
                    indicator.classList.add('show');
                    setTimeout(() => indicator.classList.remove('show'), 1500);
                }).catch(() => {});
                return;
            }
            if (settingsOpen) {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    closeSettings();
                }
                return;
            }
            if (e.key === 'Escape') {
                closeApp();
            } else if (e.key === 'm' || e.key === 'M') {
                toggleMode();
            } else if (e.key === 'ArrowUp' || e.key === 'PageUp') {
                e.preventDefault();
                pageUp();
            } else if (e.key === ' ' || e.key === 'Enter') {
                e.preventDefault();
                pageDown();
            } else if (e.key.length === 1 && /[a-zA-Z]/.test(e.key)) {
                // Any single letter key = page down (looks like typing!)
                // 'm' for mode toggle still works above, so it won't reach here
                e.preventDefault();
                pageDown();
            } else if (e.key === 'ArrowDown' || e.key === 'PageDown') {
                e.preventDefault();
                pageDown();
            }
        });

        document.getElementById('text-display').addEventListener('contextmenu', (e) => {
            e.preventDefault();
            openFile();
        });

        document.getElementById('text-display').addEventListener('wheel', (e) => {
            if (!isAutoMode && !settingsOpen) {
                e.preventDefault();
                if (e.deltaY < 0) {
                    pageUp();
                } else {
                    pageDown();
                }
            }
        });

        // --- 自研窗口拖动：pointer 事件（鼠标/触摸/触控笔通吃）+ 指针捕获 ---
        // 取代 pywebview 的 easy_drag：其只监听 mousedown/mousemove 且无捕获，
        // 触摸屏机器合成鼠标事件不连续、快速拖动光标跑出小窗口会断流，都会"拖不动"。
        let moyuDragId = null;
        function moyuDragApi(name, ...args) {
            try {
                if (window.pywebview && pywebview.api && pywebview.api[name]) {
                    pywebview.api[name](...args).catch(() => {});
                }
            } catch (err) { /* 桥未就绪等竞态下静默 */ }
        }
        function moyuDragStop(e) {
            if (e.pointerId !== moyuDragId) return;
            moyuDragId = null;
            moyuDragApi('drag_end');
        }
        document.addEventListener('pointerdown', (e) => {
            if (moyuDragId !== null) return;          // 已有指针在拖（多指忽略）
            if (e.button !== 0) return;               // 只认主键/触摸
            // 仅真交互控件豁免（点击/滑杆自身要响应）；label、面板背景等照常可拖，
            // 与旧 easy_drag "任何位置可拖"行为保持一致——控件面板被 mouseenter 唤起
            // 覆盖在窗口上时，从其文字/空白处仍可拖动窗口
            if (e.target.closest('button, input, select, textarea')) return;
            moyuDragId = e.pointerId;
            try { e.target.setPointerCapture(e.pointerId); } catch (err) {}
            moyuDragApi('drag_begin', e.screenX, e.screenY);
        });
        document.addEventListener('pointermove', (e) => {
            if (e.pointerId !== moyuDragId) return;
            moyuDragApi('drag_move', e.screenX, e.screenY);
        });
        document.addEventListener('pointerup', moyuDragStop);
        document.addEventListener('pointercancel', moyuDragStop);

        // --- 鼠标感应模式：由 Python 端 MouseSenseController 调用 ---
        function moyuSenseHide() {
            if (senseHidden) return;
            senseHidden = true;
            sensePrevPaused = isPaused;
            senseResumePending = false;
            if (!isPaused) togglePause();  // 隐藏时暂停滚动
            hideControls();
            document.body.classList.add('sense-hidden');
        }
        function moyuSenseShow() {
            if (!senseHidden) return;
            senseHidden = false;
            senseResumePending = !sensePrevPaused;  // 之前在滚 → 淡入后待恢复
            document.body.classList.remove('sense-hidden');
        }
        function moyuSenseResume() {
            if (senseHidden || !senseResumePending) return;
            senseResumePending = false;
            if (isPaused) togglePause();  // 恢复滚动
        }

        // --- 文字样式（字号/颜色/不透明度，Python 端保存后调用或启动时初始化） ---
        function applyFontStyle(size, color, opacity) {
            const m = /^#?([0-9a-fA-F]{6})$/.exec(color || '');
            if (!m) return;
            const r = parseInt(m[1].slice(0, 2), 16);
            const g = parseInt(m[1].slice(2, 4), 16);
            const b = parseInt(m[1].slice(4, 6), 16);
            const a = Math.min(1, Math.max(0.2, (Number(opacity) || 100) / 100));
            document.body.style.fontSize = Number(size) + 'px';
            document.body.style.color = 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
        }

        // Controls auto-hide: show on window entry, fade out after 3s.
        // Mouse movement inside the window does NOT re-trigger the panel;
        // only leaving the window and re-entering does.
        const controlsEl = document.getElementById('controls');
        let controlsTimer = null;
        function showControls() {
            controlsEl.classList.add('show');
            if (controlsTimer) clearTimeout(controlsTimer);
            controlsTimer = setTimeout(() => controlsEl.classList.remove('show'), 3000);
        }
        function hideControls() {
            if (controlsTimer) clearTimeout(controlsTimer);
            controlsEl.classList.remove('show');
        }
        document.getElementById('container').addEventListener('mouseenter', showControls);
        document.getElementById('container').addEventListener('mouseleave', hideControls);
        controlsEl.addEventListener('mouseenter', () => {
            if (controlsTimer) clearTimeout(controlsTimer);  // hovering the panel: stay visible
        });
        controlsEl.addEventListener('mouseleave', showControls);  // leaving panel: restart countdown

        window.addEventListener('resize', () => {
            // 窗口尺寸或字号变化会改变行高，当前页首可能落在行中间：重新对齐（floor 回退，不跳行）
            if (!isAutoMode && content && !settingsOpen) {
                currentPosition = lineFloor(currentPosition);
                updatePagePosition();
            }
        });
    </script>
    <!-- SETTINGS -->
</body>
</html>
    """.replace('<!-- SETTINGS -->', get_settings_html())


def create_reader_window(api):
    cfg = api.config['window']

    window = webview.create_window(
        '摸鱼阅读器',
        html=get_html(),
        js_api=api,
        width=cfg['width'],
        height=cfg['height'],
        x=cfg['x'],
        y=cfg['y'],
        min_size=(150, 20),
        resizable=False,
        frameless=True,
        easy_drag=False,  # 拖动由自研 pointer 事件链实现（见 drag_begin/drag_move/drag_end），覆盖鼠标/触摸/触控笔
        on_top=True,
        transparent=True
    )
    # before_show runs on the GUI thread after the native handle is available.
    window.events.before_show += enable_windows_transparency
    api._window = window

    def _on_shown():
        window.resize(cfg['width'], cfg['height'])
        api.sense.attach(window)
        if api.config.get('mouse_sense'):
            api.sense.set_enabled(True)
    window.events.shown += _on_shown
    api.close = lambda: window.destroy()
    return window


if __name__ == '__main__':
    if not ensure_dependencies():
        sys.exit(0)
    api = BookReader()
    window = create_reader_window(api)
    webview.start()
