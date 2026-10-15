# -*- mode: python ; coding: utf-8 -*-
# MoyuReader spec - single exe with integrated settings (PR #1)

a = Analysis(
    ['reader.py'],
    pathex=[],
    binaries=[],
    datas=[],
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
        # beautifulsoup4
        'bs4',
        'lxml',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim unused heavy modules (keep html/email/http - bs4 and bottle need them)
        'tkinter',
        'pydoc',
        'xmlrpc',
        'multiprocessing',
        'concurrent',
        # Unused webview backends (Windows uses edgechromium)
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
    name='MoyuReader',
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
