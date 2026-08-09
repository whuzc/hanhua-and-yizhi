"""PyInstaller entry point for the shareable desktop GUI release."""

from game2apk.cli import main
from game2apk.gui import main as gui_main
from pathlib import Path
import sys


if __name__ == "__main__":
    # Double-clicking the release opens the safe GUI.  Keep ``--cli`` as an
    # escape hatch for scripted users and support the source checkout too.
    if "--cli" in sys.argv[1:]:
        sys.argv.remove("--cli")
        raise SystemExit(main())
    tool_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    gui_main(tool_root)
