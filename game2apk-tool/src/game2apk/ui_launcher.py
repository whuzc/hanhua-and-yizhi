"""Browser-UI launcher for the portable Windows release.

``game2apk-ui.exe`` is intentionally a very small process: it starts the
adjacent console backend, waits for its loopback-only readiness message, opens
the URL in the user's default browser, and owns the child process lifetime.
It contains no build or signing code itself.  That keeps ``game2apk-tool.exe``
usable as a headless CLI/backend while the browser owns all visible UI.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import TextIO
from urllib.parse import urlparse


class LauncherError(RuntimeError):
    """The browser frontend could not be started safely."""


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _backend_command(port: int, parent_pid: int) -> list[str]:
    """Return the safe, fixed backend invocation for this installation."""

    common = ["--backend", "--port", str(port), "--parent-pid", str(parent_pid)]
    if _is_frozen():
        backend = Path(sys.executable).resolve().parent / "game2apk-tool.exe"
        if not backend.is_file():
            raise LauncherError(f"找不到同目录后台程序：{backend}")
        return [str(backend), *common]
    return [sys.executable, "-m", "game2apk.portable_entry", *common]


def _backend_environment() -> dict[str, str]:
    """Make ``python -m`` source launches work without changing global PATH."""

    environment = os.environ.copy()
    if not _is_frozen():
        src_root = str(Path(__file__).resolve().parents[1])
        inherited = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = src_root if not inherited else src_root + os.pathsep + inherited
    return environment


def _creation_flags() -> int:
    # The backend is a console executable so its ``--cli`` mode remains useful.
    # The frontend launcher deliberately hides that console during normal use.
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0


def _start_backend(port: int = 0) -> subprocess.Popen[str]:
    return subprocess.Popen(
        _backend_command(port, os.getpid()),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_creation_flags(),
        env=_backend_environment(),
    )


def _drain_lines(stream: TextIO, destination: queue.Queue[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            destination.put(line.rstrip("\r\n"))
    finally:
        stream.close()


def _ready_url_from_line(line: str) -> str | None:
    """Accept only the backend's documented loopback readiness JSON."""

    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or str(payload.get("event", "")).casefold() != "ready":
        return None
    url = payload.get("url")
    if not isinstance(url, str):
        raise LauncherError("后台就绪消息缺少 URL")
    parsed = urlparse(url)
    try:
        local_port = parsed.port
    except ValueError as exc:
        raise LauncherError("后台返回了无效端口") from exc
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or not local_port:
        raise LauncherError("后台返回了非本机前端地址，已拒绝打开")
    return url


def _wait_for_ready(process: subprocess.Popen[str], timeout_seconds: float = 15.0) -> tuple[str, queue.Queue[str]]:
    if process.stdout is None:
        raise LauncherError("后台启动时没有可读取的状态输出")
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=_drain_lines, args=(process.stdout, lines), daemon=True, name="game2apk-backend-output").start()
    deadline = time.monotonic() + timeout_seconds
    diagnostics: list[str] = []
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
        except queue.Empty:
            if process.poll() is not None:
                detail = "\n".join(diagnostics[-6:]) or f"退出码 {process.returncode}"
                raise LauncherError(f"后台未能启动：{detail}")
            continue
        url = _ready_url_from_line(line)
        if url:
            return url, lines
        if line:
            diagnostics.append(line)
    detail = "\n".join(diagnostics[-6:])
    raise LauncherError(f"等待本地后台就绪超时（15 秒）{(': ' + detail) if detail else ''}")


def _stop_backend(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _show_error(message: str) -> None:
    """Surface a launch failure even though the release launcher has no console."""

    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "Game2APK UI 无法启动", 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the Game2APK browser frontend and its local backend")
    parser.add_argument("--no-browser", action="store_true", help="start the backend but do not open the default browser")
    parser.add_argument("--startup-timeout", type=float, default=15.0, help="backend ready timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.startup_timeout <= 0 or args.startup_timeout > 120:
        _show_error("启动超时必须在 0 到 120 秒之间")
        return 2
    process: subprocess.Popen[str] | None = None
    try:
        process = _start_backend()
        url, _lines = _wait_for_ready(process, args.startup_timeout)
        if not args.no_browser and not webbrowser.open(url, new=1):
            raise LauncherError(f"无法打开默认浏览器。请手动打开：{url}")
        # The backend receives the launcher's PID and independently stops if
        # this process disappears.  It also accepts an in-page shutdown when
        # the browser tab closes, so this wait normally ends without force.
        while process.poll() is None:
            time.sleep(0.25)
        return int(process.returncode or 0)
    except (LauncherError, OSError) as exc:
        _show_error(str(exc))
        return 2
    except KeyboardInterrupt:
        return 130
    finally:
        if process is not None:
            _stop_backend(process)


if __name__ == "__main__":
    raise SystemExit(main())
