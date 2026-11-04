# -*- mode: python ; coding: utf-8 -*-
# MoyuReader v3.2 spec - v3.1 + 三个小优化：
#   1) 鼠标感应"离开隐藏延迟"可调（设置面板，0~5s，0=立刻）
#   2) 鼠标感应模式下光标停留 3s 自动隐藏（避免挡字）
#   3) 窗口加 WS_EX_TOOLWINDOW，任务栏与 Alt+Tab 均不显示（降暴露风险）
# 基于 MoyuReader_v3.1.spec：仅输出名改为 v3.2，其余 hiddenimports/excludes/datas 不变。

a = Analysis(
    ['reader.py'],
    pathex=[],
    binaries=[],
    datas=[('virtual.js', '.')],
    hiddenimports=[
        # pywebview edgechromium renderer (Windows default)
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        # pythonnet / clr for DWM transparency (System.Drawing.Color)
        'clr',
        'System',
        'System.Drawing',
        'System.Windows.Forms',
        # ebooklib
        'ebooklib',
        'ebooklib.epub',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'pydoc',
        'xmlrpc',
        'multiprocessing',
        'concurrent',
        'webview.platforms.cocoa',
        'webview.platforms.gtk',
        'webview.platforms.qt',
        'webview.platforms.cef',
        'webview.platforms.android',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MoyuReader_v3.2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
