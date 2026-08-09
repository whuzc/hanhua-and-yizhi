# PyInstaller directory build: no game assets, state, credentials or signing materials.
from pathlib import Path
import sys


ROOT = Path(SPEC).resolve().parents[1]

runtime_roots = [Path(sys.base_prefix), Path(sys.executable).resolve().parent.parent]
tk_datas = []
tk_binaries = []
for runtime_root in runtime_roots:
    tcl_dir = runtime_root / "tcl" / "tcl8.6"
    tk_dir = runtime_root / "tcl" / "tk8.6"
    tkinter_dir = runtime_root / "Lib" / "tkinter"
    if tkinter_dir.is_dir() and not any(destination == "tkinter" for _, destination in tk_datas):
        # Some embeddable/uv Python distributions make Tcl discovery fail at
        # analysis time.  Keep the pure-Python tkinter package as portable data
        # so the bundled Tcl/Tk runtime can still import the GUI on the target.
        tk_datas.append((str(tkinter_dir), "tkinter"))
    if tcl_dir.is_dir() and not any(destination == "_tcl_data" for _, destination in tk_datas):
        tk_datas.append((str(tcl_dir), "_tcl_data"))
    if tk_dir.is_dir() and not any(destination == "_tk_data" for _, destination in tk_datas):
        tk_datas.append((str(tk_dir), "_tk_data"))
    for binary_name in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll"):
        binary_path = runtime_root / "DLLs" / binary_name
        if binary_path.is_file() and not any(Path(source).name.casefold() == binary_name.casefold() for source, _ in tk_binaries):
            tk_binaries.append((str(binary_path), "."))

# The optional browser shell is static HTML/CSS/JS.  It is copied to the
# release root by build-portable.ps1 as well, so ``--web`` works in both a
# source checkout and a frozen one-folder release.
frontend_dir = ROOT / "frontend"
if frontend_dir.is_dir():
    tk_datas.append((str(frontend_dir), "frontend"))

a = Analysis(
    [str(ROOT / "src" / "game2apk" / "portable_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=tk_binaries,
    datas=tk_datas,
    hiddenimports=["game2apk.gui", "game2apk.web_frontend", "tkinter", "tkinter.ttk", "_tkinter"],
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
    [],
    exclude_binaries=True,
    name="game2apk-tool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # The backend deliberately remains a console executable: its --cli mode
    # is supported for automation and game2apk-ui.exe consumes its structured
    # --backend readiness line through stdout.  The UI launcher starts it with
    # CREATE_NO_WINDOW, so normal users never see a background terminal.
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="game2apk-tool",
)
