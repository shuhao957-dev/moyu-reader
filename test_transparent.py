import webview

html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {
            margin: 0;
            padding: 0;
        }
        html, body {
            background: transparent;
            height: 100%;
        }
        body {
            font-family: "Microsoft YaHei", sans-serif;
            font-size: 16px;
            color: #333;
            padding: 10px;
        }
    </style>
</head>
<body>
    <h1>透明测试窗口</h1>
    <p>如果你能看到后面的桌面，说明透明功能正常。</p>
</body>
</html>
"""

if __name__ == '__main__':
    window = webview.create_window(
        '透明测试',
        html=html,
        width=400,
        height=200,
        frameless=True,
        transparent=True,
        on_top=True
    )
    webview.start()
