import webview

html = """
<!DOCTYPE html>
<html>
<body>
    <h1>测试</h1>
</body>
</html>
"""

window = webview.create_window(
    'Test',
    html=html,
    width=400,
    height=200,
    frameless=True,
    transparent=True
)

webview.start()
