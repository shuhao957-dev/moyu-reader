import webview

html = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body {
            margin: 0;
            padding: 0;
            background: transparent;
            font-family: Arial;
            color: #333;
            overflow: hidden;
        }
        #drag-area {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 30px;
            background: rgba(200, 200, 200, 0.5);
            cursor: move;
            display: flex;
            align-items: center;
            padding: 0 10px;
        }
        #content {
            position: absolute;
            top: 30px;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255, 255, 255, 0.9);
            padding: 20px;
        }
    </style>
</head>
<body>
    <div id="drag-area">拖动这里移动窗口</div>
    <div id="content">
        <h3>测试</h3>
        <p>窗口透明吗？能拖动顶部灰色条吗？</p>
    </div>

    <script>
        let isDragging = false;
        let startX, startY;

        document.getElementById('drag-area').addEventListener('mousedown', (e) => {
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            pywebview.api.start_drag(e.screenX - e.clientX, e.screenY - e.clientY);
        });

        document.addEventListener('mousemove', (e) => {
            if (isDragging) {
                pywebview.api.move_window(e.screenX, e.screenY);
            }
        });

        document.addEventListener('mouseup', () => {
            isDragging = false;
        });
    </script>
</body>
</html>
"""

class API:
    def __init__(self, window):
        self.window = window
        self.offset_x = 0
        self.offset_y = 0

    def start_drag(self, x, y):
        self.offset_x = x
        self.offset_y = y

    def move_window(self, screen_x, screen_y):
        self.window.move(screen_x - self.offset_x, screen_y - self.offset_y)

window = webview.create_window(
    'JS Drag Test',
    html=html,
    width=400,
    height=300,
    frameless=True,
    easy_drag=False,
    transparent=True,
    on_top=True
)

api = API(window)
webview.start(api, gui='edgechromium')
