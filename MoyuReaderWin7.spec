# -*- mode: python ; coding: utf-8 -*-
# Win7 兼容版打包配置（PyInstaller 5.x + Python 3.8 + pywebview 3.6.3）
# _build_venv_win7 环境（NuGet Python 3.8.10）执行：
#   C:\Users\100000386\.workbuddy\binaries\python\versions\3.8.10\tools\python.exe -m PyInstaller --noconfirm MoyuReaderWin7.spec


a = Analysis(
    ['reader.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
        'webview.platforms.cef',
        'clr',
        'bottle',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MoyuReaderWin7',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
