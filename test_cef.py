import webview

html = """
<!DOCTYPE html>
<html>
<body style="background: transparent;">
    <h1>CEF 后端测试</h1>
</body>
</html>
"""

window = webview.create_window(
    'Test CEF',
    html=html,
    width=400,
    height=200,
    frameless=True,
    transparent=True
)

# 尝试使用 CEF 后端而不是默认的 EdgeChromium
webview.start(gui='cef', debug=True)
