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
        enable_windows_transparency(self._window)  # resize 后重挂 DWM 透明（幂等）
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
            enable_windows_transparency(self._window)  # 同上，恢复后重挂

    def sense_toggle(self):
        """Ctrl+H 兜底开关：运行时切换鼠标感应模式（不写配置文件）"""
        return self.sense.toggle()

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
        # pywebview 4.x 用 webview.FileDialog.OPEN；3.6（Win7 构建）用 webview.OPEN_DIALOG
        FileDialog = getattr(webview, 'FileDialog', None)
        dialog_type = FileDialog.OPEN if FileDialog is not None else webview.OPEN_DIALOG
        result = self._window.create_file_dialog(dialog_type, file_types=file_types)

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
        # Win7/8：微软新版 WebView2 运行时已放弃这些系统（Win7 支持止于 109 版），
        # 自动下载会装上跑不起来的版本，改为指引用户手动装 109 版。
        if sys.getwindowsversion() < (6, 2):
            _msg_box(
                '摸鱼阅读器需要 WebView2 运行时才能运行。\n\n'
                '检测到当前是 Windows 7 系统。\n'
                '请手动安装「WebView2 Runtime 109 版」\n'
                '（微软支持 Win7 的最后版本，安装包见发布页附件），\n'
                '安装完成后重新打开本程序。',
                icon=0x30,  # MB_ICONWARNING
            )
            return False

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


def _ensure_topmost():
    """强制置顶（HWND_TOPMOST），绕开 pywebview 3.6.3 的 on_top 实现 bug。

    3.6.3 的 winforms 后端两个坑叠加：
    1) 创建窗口时不应用 on_top 参数（收了钱不办事）；
    2) 即便事后赋值 window.on_top = True，其内部用 ctypes 裸 -1 传 HWND_TOPMOST，
       64 位 Python 上会截断为 0xFFFFFFFF，系统不认，SetWindowPos 静默失败。
    因此直接用 64 位完整的 HWND(-1) 调用（已实验验证：裸 -1 失败、HWND(-1) 成功）。
    """
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, '摸鱼阅读器')
        if hwnd:
            SWP_NOSIZE, SWP_NOMOVE = 0x1, 0x2
            user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE)
    except Exception:
        pass  # 置顶失败不影响其他功能


def enable_windows_transparency(window):
    """Make the reader window a true transparent overlay that stays interactive.

    Two host generations are handled:
    - pywebview 6.x (main branch): window.native is the WinForms host.
    - pywebview 3.6 (Win7 build): no window.native; resolve the HWND via
      FindWindowW and get the Form back through Control.FromHandle.

    The 3.6 host implements ``transparent=True`` with a color-key
    (Form.BackColor = TransparencyKey = LimeGreen). Color-key pixels are
    click-through by design, which kills right-click / drag on the whole
    background — so the first job here is to dismantle the color key and
    rebuild transparency with the DWM extended-frame recipe (negative margins
    + black host = zero-alpha pixels), same as the main branch. Idempotent:
    safe to call again after resizes. Falls back gracefully without pythonnet.
    """
    if sys.platform != 'win32':
        return

    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        # --- 1) resolve the native HWND ---
        hwnd = None
        native = getattr(window, 'native', None)
        if native is not None:
            try:
                hwnd = native.Handle.ToInt64()
            except Exception:
                hwnd = None
        if not hwnd:
            hwnd = user32.FindWindowW(None, '摸鱼阅读器')
        if not hwnd:
            print('[摸鱼阅读器] 未找到窗口句柄，跳过 DWM 透明（不影响使用）')
            return

        # --- 2) dismantle the color key from the .NET side and go black ---
        # pywebview 6.x exposes the Form via window.native; pywebview 3.6
        # (Win7 build) keeps it in BrowserView.instances keyed by window.uid.
        form = native
        if form is None:
            try:
                from webview.platforms.winforms import BrowserView
                form = BrowserView.instances.get(getattr(window, 'uid', None))
            except ImportError:
                form = None
        if form is not None:
            import clr
            clr.AddReference('System.Drawing')
            from System.Drawing import Color
            form.TransparencyKey = Color.Empty   # kill the LimeGreen color key
            form.BackColor = Color.Black         # black host = zero-alpha for DWM
            # WinForms recalculates window styles asynchronously after the
            # property change; give it a moment before touching win32 styles.
            time.sleep(0.3)

        # --- 3) belt and braces: strip WS_EX_LAYERED at the win32 level ---
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x20
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if style & WS_EX_LAYERED:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_LAYERED)
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED)

        # --- 4) DWM extended frame: negative margins cover the entire client
        # area, including future resizes; black host pixels become transparent ---
        class Margins(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int) for name in ('left', 'right', 'top', 'bottom')]

        extend_frame = ctypes.WinDLL('dwmapi').DwmExtendFrameIntoClientArea
        extend_frame.argtypes = [wintypes.HWND, ctypes.POINTER(Margins)]
        extend_frame.restype = ctypes.c_long
        margins = Margins(-1, -1, -1, -1)
        result = extend_frame(hwnd, ctypes.byref(margins))
        if result < 0:
            raise OSError(f'DwmExtendFrameIntoClientArea failed: 0x{result & 0xffffffff:08X}')
    except (ImportError, OSError, Exception) as e:
        # pythonnet / .NET Desktop Runtime not available — transparency disabled,
        # but the reader still works perfectly without it.
        print(f'[摸鱼阅读器] 透明背景未启用: {e}')
        print('[摸鱼阅读器] 提示: 安装 .NET Desktop Runtime 可启用透明背景效果')


class MouseSenseController:
    """鼠标感应模式：鼠标在窗口内 = 正常显示；离开超过 0.5 秒 = 窗口淡出 + 暂停滚动 + 整体移出屏幕。

    实现要点：
    - 后台线程轮询全局鼠标坐标（GetCursorPos）与窗口矩形（GetWindowRect），
      不依赖窗口自身接收鼠标事件，因此窗口移出屏幕后仍能感知鼠标回来。
    - 隐藏用"视觉淡出（JS）+ 物理移出屏幕（SetWindowPos）"而非点击穿透：
      WS_EX_TRANSPARENT 在 pywebview 3.6 老栈上有样式残留 bug，且窗口悬停在
      原处不可见也会挡住下层软件的点击——移出屏幕两个问题一起解决。
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
        self._stash_rect = None  # 隐藏时把窗口移出屏幕前记录的原位置

    @property
    def enabled(self):
        return self._enabled

    def attach(self, window):
        """窗口 shown 后（GUI 线程）调用，缓存原生句柄供 win32 调用使用"""
        self._window = window
        self._hwnd = None
        try:
            self._hwnd = window.native.Handle.ToInt64()
        except Exception:
            self._hwnd = None
        if not self._hwnd:
            # pywebview 3.6（Win7 兼容构建）无 native 属性：按窗口标题查找句柄
            try:
                import ctypes
                self._hwnd = ctypes.windll.user32.FindWindowW(None, '摸鱼阅读器') or None
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
        self._restore_window()
        self._eval_js('moyuSenseShow()')

    def _eval_js(self, code):
        try:
            if self._window is not None:
                self._window.evaluate_js(code)
        except Exception:
            pass  # 窗口关闭等竞态下静默失败

    def _stash_window(self):
        """隐藏兜底：把窗口整体移出屏幕（不依赖点击穿透）。

        色键透明已废、点击穿透在 3.6 老栈上有样式残留 bug，改用物理移出：
        窗口不可见也不挡住下层软件的点击，鼠标回到原区域再移回。
        """
        if sys.platform != 'win32' or not self._hwnd:
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            rect = wintypes.RECT()
            if not user32.GetWindowRect(self._hwnd, ctypes.byref(rect)):
                return
            self._stash_rect = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
            SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
            user32.SetWindowPos(self._hwnd, 0, -32000, -32000, 0, 0,
                                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        except Exception:
            pass

    def _restore_window(self):
        """把移出屏幕的窗口放回原位置（幂等：未 stash 时无操作）"""
        if sys.platform != 'win32' or not self._hwnd or not self._stash_rect:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            x, y = self._stash_rect[0], self._stash_rect[1]
            self._stash_rect = None
            SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
            user32.SetWindowPos(self._hwnd, 0, x, y, 0, 0,
                                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
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
                if self._stash_rect:
                    # 窗口已移出屏幕：用移出前的矩形判定鼠标是否回到原区域
                    sx, sy, sw, sh = self._stash_rect
                    inside = sx <= pt.x < sx + sw and sy <= pt.y < sy + sh
                else:
                    if not user32.GetWindowRect(self._hwnd, ctypes.byref(rect)):
                        continue
                    inside = rect.left <= pt.x < rect.right and rect.top <= pt.y < rect.bottom
                now = time.time()
                if inside:
                    out_since = None
                    if hidden:
                        # 鼠标回到原区域：先把窗口移回原位，再淡入，滚动缓冲后恢复
                        self._restore_window()
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
                        # 离开超过宽限期：JS 淡出+暂停，窗口整体移出屏幕
                        self._eval_js('moyuSenseHide()')
                        self._stash_window()
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
        let currentPage = 0;
        let totalPages = 0;
        let pageHeight = 0;
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
                updatePageInfo();
            }

            indicator.classList.add('show');
            setTimeout(() => indicator.classList.remove('show'), 1500);
        }

        function updatePageInfo() {
            if (!isAutoMode && content) {
                pageHeight = document.getElementById('text-display').offsetHeight;
                const contentHeight = document.getElementById('text-content').offsetHeight;
                totalPages = Math.ceil(contentHeight / pageHeight);
                currentPage = Math.floor(currentPosition / pageHeight);
            }
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
                currentPage = Math.max(0, currentPage - 1);
                updatePagePosition();
                saveProgress();
            }
        }

        function pageDown() {
            if (!isAutoMode && content) {
                currentPage = Math.min(totalPages - 1, currentPage + 1);
                updatePagePosition();
                saveProgress();
            }
        }

        function updatePagePosition() {
            currentPosition = currentPage * pageHeight;
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
                    document.getElementById('text-content').style.transform = `translateY(-${currentPosition}px)`;

                    startAutoSave();

                    if (isAutoMode) {
                        startScroll();
                    } else {
                        updatePageInfo();
                        currentPage = Math.floor(currentPosition / pageHeight);
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
            if (!isAutoMode && !settingsOpen) {
                updatePageInfo();
                currentPage = Math.floor(currentPosition / pageHeight);
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
        easy_drag=True,
        on_top=True,
        transparent=True
    )
    # before_show runs on the GUI thread after the native handle is available.
    if hasattr(window.events, 'before_show'):
        window.events.before_show += enable_windows_transparency
    api._window = window

    def _on_shown():
        window.resize(cfg['width'], cfg['height'])
        _ensure_topmost()
        api.sense.attach(window)
        # pywebview 3.6（Win7 构建）没有 before_show：shown 后补挂 DWM 透明
        enable_windows_transparency(window)
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
