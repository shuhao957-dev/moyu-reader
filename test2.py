import webview

html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
</head>
<body style="background: transparent;">
    <h1>透明测试</h1>
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
        transparent=True
    )
    webview.start()
