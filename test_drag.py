import webview

html = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body {
            margin: 0;
            padding: 20px;
            background: transparent;
            -webkit-app-region: drag;
            font-family: Arial;
            color: #333;
        }
        .content {
            background: rgba(255, 255, 255, 0.8);
            padding: 20px;
            border-radius: 8px;
        }
    </style>
</head>
<body>
    <div class="content">
        <h3>测试窗口</h3>
        <p>1. 这个窗口透明吗？</p>
        <p>2. 可以拖动吗？</p>
    </div>
</body>
</html>
"""

window = webview.create_window(
    'Drag Test',
    html=html,
    width=400,
    height=300,
    frameless=True,
    easy_drag=False,
    transparent=True,
    on_top=True
)

webview.start()
