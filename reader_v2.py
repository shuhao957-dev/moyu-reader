import webview
import sys
import os
import threading
import time
from pathlib import Path
import json
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

class BookReader:
    def __init__(self):
        self.content = ""
        self.current_file = None
        self.progress_file = Path.home() / '.moyu_reader_progress.json'
        self.config_file = Path.home() / '.moyu_reader_config.json'
        self.progress = {}
        self._window = None
        self.sense = MouseSenseController(self)
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
                    'speed': 50,
                    'mouse_sense': False
                }
        except:
            self.config = {
                'window': {'width': 400, 'height': 60, 'x': 100, 'y': 100},
                'speed': 50,
                'mouse_sense': False
            }

    def sense_toggle(self):
        """Ctrl+H 兜底开关：运行时切换鼠标感应模式（不写配置文件）"""
        return self.sense.toggle()

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
        file_types = ('TXT文件 (*.txt)', 'EPUB文件 (*.epub)', '所有文件 (*.*)')
        result = window.create_file_dialog(webview.OPEN_DIALOG, file_types=file_types)

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


class MouseSenseController:
    """鼠标感应模式：鼠标在窗口内 = 正常显示；离开超过 0.5 秒 = 窗口淡出 + 暂停滚动 + 点击穿透。
    通过后台线程轮询全局鼠标坐标与窗口矩形判定，隐身（点击穿透）状态下仍能感知鼠标回来。"""

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
            pass

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
                style &= ~WS_EX_TRANSPARENT
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
                        self._eval_js('moyuSenseHide()')
                        self._set_click_through(True)
                        hidden = True
            except Exception:
                continue


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

        /* 鼠标感应模式：隐身时整体淡出 */
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
        let currentFile = '';
        // --- 鼠标感应模式状态（由 Python 端 MouseSenseController 驱动） ---
        let senseHidden = false;
        let sensePrevPaused = false;
        let senseResumePending = false;

        function startScroll() {
            if (!content || isPaused) return;
            requestAnimationFrame(scroll);
        }

        function scroll(timestamp) {
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
                requestAnimationFrame(scroll);
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
            senseResumePending = false;  // 手动/其他入口的暂停切换取消待恢复
            isPaused = !isPaused;
            const pauseBtn = document.getElementById('pause-btn');
            if (isPaused) {
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
            scrollSpeed = value;
            document.getElementById('speed-value').textContent = value;
        }

        function saveProgress() {
            if (currentFile && content) {
                pywebview.api.save_progress(currentFile, currentPosition);
            }
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
            saveProgress();
            pywebview.api.close();
        }

        document.addEventListener('keydown', (e) => {
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
            if (e.key === 'Escape') {
                closeApp();
            } else if (e.key === ' ') {
                e.preventDefault();
                togglePause();
            } else if (e.key === 'm' || e.key === 'M') {
                toggleMode();
            } else if (e.key === 'ArrowUp' || e.key === 'PageUp') {
                e.preventDefault();
                pageUp();
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
            if (!isAutoMode) {
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
            if (!isPaused) togglePause();
            hideControls();
            document.body.classList.add('sense-hidden');
        }
        function moyuSenseShow() {
            if (!senseHidden) return;
            senseHidden = false;
            senseResumePending = !sensePrevPaused;
            document.body.classList.remove('sense-hidden');
        }
        function moyuSenseResume() {
            if (senseHidden || !senseResumePending) return;
            senseResumePending = false;
            if (isPaused) togglePause();
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
            if (!isAutoMode) {
                updatePageInfo();
                currentPage = Math.floor(currentPosition / pageHeight);
            }
        });
    </script>
</body>
</html>
    """


if __name__ == '__main__':
    api = BookReader()
    api.close = lambda: window.destroy()

    cfg = api.config['window']

    window = webview.create_window(
        '摸鱼阅读器',
        html=get_html(),
        js_api=api,
        width=cfg['width'],
        height=cfg['height'],
        x=cfg['x'],
        y=cfg['y'],
        resizable=False,
        frameless=True,
        easy_drag=False,
        on_top=True,
        transparent=True
    )

    api._window = window

    def _on_shown():
        api.sense.attach(window)
        if api.config.get('mouse_sense'):
            api.sense.set_enabled(True)
    window.events.shown += _on_shown

    webview.start()
