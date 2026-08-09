"""PyInstaller entry point for the shareable desktop GUI release."""

from game2apk.cli import main
from game2apk.gui import main as gui_main
from game2apk.web_frontend import main as web_main
from pathlib import Path
import sys


if __name__ == "__main__":
    # Double-clicking the release opens the safe GUI.  Keep ``--cli`` as an
    # escape hatch for scripted users and support the source checkout too.
    if "--web" in sys.argv[1:]:
        sys.argv.remove("--web")
        tool_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
        # Browser shell owns the process until it is interrupted; never fall
        # through and open a second Tk window after it shuts down.
        raise SystemExit(web_main(tool_root))
    elif "--cli" in sys.argv[1:]:
        sys.argv.remove("--cli")
        raise SystemExit(main())
    tool_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    gui_main(tool_root)
