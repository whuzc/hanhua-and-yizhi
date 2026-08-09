"""PyInstaller entry point for the shareable desktop and browser releases."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from game2apk.cli import main as cli_main
from game2apk.web_frontend import main as backend_main


def _tool_root() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]


def _backend_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True, prog="game2apk-tool.exe --backend")
    parser.add_argument("--port", type=int, default=0, help="loopback port; 0 selects a random available port")
    parser.add_argument("--parent-pid", type=int, default=None, help="stop when the native frontend parent exits")
    parser.add_argument("--idle-timeout", type=float, default=30.0, help="seconds after frontend heartbeat stops; 0 disables idle shutdown")
    return parser


if __name__ == "__main__":
    # ``--backend`` is deliberately UI-free: a native WebView/frontend
    # launches it hidden, parses its one READY JSON line and navigates to the
    # loopback URL.  ``--web`` remains a compatibility alias which opens the
    # system browser after the backend starts.
    raw_args = list(sys.argv[1:])
    backend_mode = "--backend" in raw_args or "--server" in raw_args or "--web" in raw_args
    if backend_mode:
        open_browser = "--web" in raw_args
        cleaned = [arg for arg in raw_args if arg not in {"--backend", "--server", "--web"}]
        options = _backend_parser().parse_args(cleaned)
        raise SystemExit(
            backend_main(
                _tool_root(),
                open_browser=open_browser,
                port=options.port,
                parent_pid=options.parent_pid,
                idle_timeout_seconds=options.idle_timeout,
            )
        )
    if "--cli" in raw_args:
        raw_args.remove("--cli")
        raise SystemExit(cli_main(raw_args))
    # The backend executable is intentionally UI-free.  The separately built
    # ``game2apk-ui.exe`` owns the browser surface and starts this sibling
    # process with a parent PID.  Keep an explicit escape hatch for developers
    # who still need the legacy Tk wizard, without importing Tk in the normal
    # backend path.
    if "--legacy-gui" in raw_args:
        from game2apk.gui import main as gui_main

        gui_main(_tool_root())
    else:
        # A bare backend executable must remain headless.  The browser
        # launcher supplies the explicit ``--backend`` flags above; a direct
        # launch is still useful for diagnostics, but must not fall back to
        # the old Tk window or inherit an undefined parser state.
        raise SystemExit(
            backend_main(
                _tool_root(),
                open_browser=False,
                port=0,
                parent_pid=None,
                idle_timeout_seconds=0,
            )
        )
