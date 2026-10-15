import webview
import sys
import os
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
            position: relative;
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
            transition: transform 0.3s ease;
        }

        #controls {
            display: none;
            position: fixed;
            top: 4px;
            right: 4px;
            padding: 8px;
            background: rgba(255, 255, 255, 0.95);
            border-radius: 6px;
            font-size: 12px;
            -webkit-app-region: no-drag;
            z-index: 1000;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
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
            margin: 2px;
            padding: 4px 10px;
            font-size: 11px;
            cursor: pointer;
            border: 1px solid #ddd;
            background: white;
            border-radius: 4px;
            transition: all 0.2s;
        }

        button:hover {
            background: #f5f5f5;
            border-color: #999;
        }

        button.active {
            background: #4CAF50;
            color: white;
            border-color: #4CAF50;
        }

        .control-group {
            margin: 4px 0;
            padding: 4px 0;
            border-bottom: 1px solid #eee;
        }

        .control-group:last-child {
            border-bottom: none;
        }

        .info {
            font-size: 10px;
            color: #666;
            margin-top: 4px;
        }
    </style>
</head>
<body>
    <div id="container">
        <div id="mode-indicator">自动滚动</div>
        <div id="controls">
            <div class="control-group">
                <button onclick="openFile()">📖 打开</button>
                <button id="mode-btn" onclick="toggleMode()" class="active">🔄 自动</button>
                <button id="pause-btn" onclick="togglePause()">⏸ 暂停</button>
                <button onclick="closeApp()">❌ 关闭</button>
            </div>
            <div class="control-group">
                <button onclick="adjustSpeed(-10)">速度−</button>
                <button onclick="adjustSpeed(10)">速度+</button>
                <span style="font-size: 10px; color: #666;">(<span id="speed-value">50</span>)</span>
            </div>
            <div class="info">
                <div style="font-size: 10px;">空格:暂停 | M:切模式 | ↑↓:翻页 | ESC:关闭</div>
            </div>
        </div>
        <div id="text-display" onclick="togglePause()">
            <div id="text-content">右键点击打开电子书开始摸鱼...</div>
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

        function startScroll() {
            if (!content || isPaused || !isAutoMode) return;
            requestAnimationFrame(scroll);
        }

        function scroll(timestamp) {
            if (!lastTimestamp) lastTimestamp = timestamp;
            const delta = timestamp - lastTimestamp;
            lastTimestamp = timestamp;

            if (!isPaused && content && isAutoMode) {
                currentPosition += (scrollSpeed / 1000) * delta;

                const textElement = document.getElementById('text-content');
                textElement.style.transform = `translateY(-${currentPosition}px)`;

                const displayHeight = document.getElementById('text-display').offsetHeight;
                const contentHeight = textElement.offsetHeight;

                if (currentPosition > contentHeight - displayHeight) {
                    currentPosition = contentHeight - displayHeight;
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
                modeBtn.textContent = '🔄 自动';
                modeBtn.classList.add('active');
                indicator.textContent = '自动滚动';
                lastTimestamp = 0;
                if (!isPaused) {
                    startScroll();
                }
            } else {
                modeBtn.textContent = '👆 手动';
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
                pauseBtn.textContent = '▶ 继续';
            } else {
                pauseBtn.textContent = '⏸ 暂停';
                if (isAutoMode) {
                    lastTimestamp = 0;
                    startScroll();
                }
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

        function adjustSpeed(delta) {
            scrollSpeed = Math.max(10, Math.min(200, scrollSpeed + delta));
            document.getElementById('speed-value').textContent = scrollSpeed;
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
                }
            });
        }

        function closeApp() {
            saveProgress();
            pywebview.api.close();
        }

        document.addEventListener('keydown', (e) => {
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

        document.getElementById('text-display').addEventListener('contextmenu', (e) => {
            e.preventDefault();
            openFile();
        });

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

    webview.start()
