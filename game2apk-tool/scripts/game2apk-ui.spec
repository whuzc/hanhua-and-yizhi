# PyInstaller one-file browser launcher.  The actual pipeline remains in the
# sibling game2apk-tool.exe backend so this binary carries no game assets,
# Android SDK/JDK, credentials, state, or static frontend bundle.
from pathlib import Path


ROOT = Path(SPEC).resolve().parents[1]

a = Analysis(
    [str(ROOT / "src" / "game2apk" / "ui_launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    a.datas,
    [],
    name="game2apk-ui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
