import webview
import sys
import os
import subprocess
import tempfile
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
        self.load_progress()
        self.load_config()

    def load_config(self):
        """加载配置文件"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            else:
                self.config = {
                    'window': {'width': 400, 'height': 60, 'x': 100, 'y': 100},
                    'speed': 50
                }
        except:
            self.config = {
                'window': {'width': 400, 'height': 60, 'x': 100, 'y': 100},
                'speed': 50
            }

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
        """获取阅读进度"""
        return self.progress.get(file_path, 0)

    def get_config(self):
        return self.config

    def open_settings(self):
        if self._reader_size is None:
            self._reader_size = (self._window.width, self._window.height)
        self._window.resize(550, 600)
        return self.config

    def close_settings(self):
        if self._reader_size is not None:
            self._window.resize(*self._reader_size)
            self._reader_size = None

    def apply_settings(self, width, height, speed):
        try:
            width, height, speed = int(width), int(height), int(speed)
            if not (150 <= width <= 1200 and 20 <= height <= 600 and 10 <= speed <= 200):
                raise ValueError('设置超出允许范围')
        except (TypeError, ValueError, OverflowError):
            return {'success': False, 'message': '宽度须为 150–1200，高度须为 20–600，速度须为 10–200。'}

        config = {**self.config, 'window': {**self.config['window'], 'width': width, 'height': height}, 'speed': speed}
        try:
            self.config_file.write_text(json.dumps(config, indent=4, ensure_ascii=False), encoding='utf-8')
        except OSError as error:
            return {'success': False, 'message': f'保存失败：{error}'}
        self.config = config
        self._reader_size = (width, height)
        return {'success': True, 'config': config}

    def load_txt(self, file_path):
        """加载TXT文件，自动检测编码"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.content = f.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='gbk') as f:
                    self.content = f.read()
            except:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    self.content = f.read()

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
                    return {'success': True, 'content': self.content, 'filename': Path(file_path).name, 'position': saved_position}
            elif ext == '.epub':
                if self.load_epub(file_path):
                    saved_position = self.get_progress(file_path)
                    return {'success': True, 'content': self.content, 'filename': Path(file_path).name, 'position': saved_position}

            return {'success': False, 'error': '不支持的文件格式'}

        return {'success': False, 'error': '未选择文件'}


# ---------------------------------------------------------------------------
# Dependency self-check: auto-install WebView2 / .NET if missing
# ---------------------------------------------------------------------------

def _is_webview2_installed():
    """Check if WebView2 runtime is installed via Windows registry."""
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for wow64 in ('', 'WOW6432Node\\'):
                try:
                    key = winreg.OpenKey(
                        root,
                        rf'SOFTWARE\{wow64}Microsoft\EdgeUpdate\Clients'
                        r'\{F3017226-FE2A-4295-8BEB-3A2F0F6B5A7B}',
                    )
                    winreg.CloseKey(key)
                    return True
                except (FileNotFoundError, OSError):
                    continue
    except ImportError:
        pass
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
        }

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
            display: none;
            position: fixed;
            top: 0;
            right: 0;
            padding: 4px;
            background: rgba(255, 255, 255, 0.9);
            border-radius: 4px;
            font-size: 12px;
            -webkit-app-region: no-drag;
            z-index: 1000;
        }

        body:hover #controls {
            display: block;
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

        /* Progress bar — thin, always visible, clickable */
        #progress-bar {
            height: 3px;
            background: rgba(200, 200, 200, 0.3);
            cursor: pointer;
            -webkit-app-region: no-drag;
            position: relative;
            flex-shrink: 0;
        }

        #progress-bar:hover {
            height: 6px;
        }

        #progress-fill {
            height: 100%;
            background: rgba(76, 175, 80, 0.7);
            width: 0%;
            transition: width 0.2s;
            pointer-events: none;
        }

        #progress-bar:hover #progress-fill {
            background: rgba(76, 175, 80, 1);
        }

        #progress-tip {
            display: none;
            position: absolute;
            bottom: 8px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0, 0, 0, 0.75);
            color: #fff;
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 3px;
            white-space: nowrap;
            pointer-events: none;
        }

        #progress-bar:hover #progress-tip {
            display: block;
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
        <div id="progress-bar" onclick="jumpToProgress(event)" onmousemove="showProgressTip(event)" onmouseleave="hideProgressTip()">
            <div id="progress-fill"></div>
            <div id="progress-tip">0%</div>
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
        let currentFile = '';
        let scrollFrame = 0;
        let autoSaveInterval = null;

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

                saveProgress();
                updateProgressBar();
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
                updateProgressBar();
            }
        }

        function pageDown() {
            if (!isAutoMode && content) {
                currentPage = Math.min(totalPages - 1, currentPage + 1);
                updatePagePosition();
                saveProgress();
                updateProgressBar();
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
            if (currentFile && content) {
                pywebview.api.save_progress(currentFile, currentPosition);
            }
        }

        // --- Progress bar ---
        function updateProgressBar() {
            if (!content) return;
            const textElement = document.getElementById('text-content');
            const contentHeight = textElement.offsetHeight;
            const displayHeight = document.getElementById('text-display').offsetHeight;
            const maxScroll = Math.max(1, contentHeight - displayHeight);
            const pct = Math.min(100, Math.max(0, (currentPosition / maxScroll) * 100));
            document.getElementById('progress-fill').style.width = pct + '%';
        }

        function jumpToProgress(event) {
            if (!content) return;
            const bar = document.getElementById('progress-bar');
            const rect = bar.getBoundingClientRect();
            const pct = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));

            const textElement = document.getElementById('text-content');
            const contentHeight = textElement.offsetHeight;
            const displayHeight = document.getElementById('text-display').offsetHeight;
            const maxScroll = Math.max(0, contentHeight - displayHeight);

            currentPosition = pct * maxScroll;
            textElement.style.transform = `translateY(-${currentPosition}px)`;

            if (!isAutoMode) {
                updatePageInfo();
                currentPage = Math.floor(currentPosition / pageHeight);
            }
            saveProgress();
            updateProgressBar();
        }

        function showProgressTip(event) {
            if (!content) return;
            const bar = document.getElementById('progress-bar');
            const rect = bar.getBoundingClientRect();
            const pct = Math.max(0, Math.min(100, ((event.clientX - rect.left) / rect.width) * 100));
            const tip = document.getElementById('progress-tip');
            tip.textContent = Math.round(pct) + '%';
        }

        function hideProgressTip() {
            // tip hides via CSS :hover on parent
        }

        // --- Auto-save every 5 seconds ---
        function startAutoSave() {
            if (autoSaveInterval) clearInterval(autoSaveInterval);
            autoSaveInterval = setInterval(() => {
                if (currentFile && content) {
                    saveProgress();
                }
            }, 5000);
        }

        function openFile() {
            pywebview.api.open_file().then(result => {
                if (result.success) {
                    content = result.content;
                    currentFile = result.filename;
                    currentPosition = result.position || 0;
                    isPaused = false;
                    lastTimestamp = 0;

                    document.getElementById('text-content').textContent = content;
                    document.getElementById('text-content').style.transform = `translateY(-${currentPosition}px)`;

                    updateProgressBar();
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
            });
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
    window.events.before_show += enable_windows_transparency
    api._window = window
    window.events.shown += lambda: window.resize(cfg['width'], cfg['height'])
    api.close = lambda: window.destroy()
    return window


if __name__ == '__main__':
    if not ensure_dependencies():
        sys.exit(0)
    api = BookReader()
    window = create_reader_window(api)
    webview.start()
