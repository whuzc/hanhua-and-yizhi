"""Loopback-only backend for the browser desktop frontend.

The executable deliberately keeps the Android pipeline in Python and exposes a
small localhost API to a separate browser/WebView surface.  It never listens
on a LAN interface, never writes request bodies to logs, and does not persist
DeepSeek or signing secrets.  The frontend is served by the same process so a
short-lived HttpOnly session cookie can protect the mutation endpoints without
placing a token in a URL or command line.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import os
import secrets
import sys
import threading
import time
import uuid
import webbrowser
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, TypeAlias
from urllib.parse import urlparse

from .config import build_config, default_control_config
from .errors import CancelledError, ConfigurationError, Game2ApkError
from .models import BuildConfig
from .pipeline import PipelineService
from .security import now_utc, redact_text
from .toolchain import COMPONENTS, discover_configured, download_component, load_config, missing_components, save_config
from .translation import (
    DEFAULT_TRANSLATION_REASONING_EFFORT,
    DEFAULT_TRANSLATION_THINKING_ENABLED,
    normalize_reasoning_effort,
)


MAX_REQUEST_BYTES = 128 * 1024
MAX_JOB_MESSAGE_CHARS = 1200
DEFAULT_IDLE_TIMEOUT_SECONDS = 30.0
SESSION_COOKIE_NAME = "game2apk_session"
REQUEST_HEADER = "X-Game2Apk-Request"

_BROWSE_TITLES = {
    "source": "选择 RPG Maker MV 游戏根目录或 www 目录",
    "template": "选择 Android 模板目录",
    "sdk": "选择 Android SDK 目录",
    "jdk": "选择 JDK 目录",
    "gradle": "选择 Gradle 用户缓存目录",
    "download": "选择 Android 工具下载/安装目录",
}


def _json_safe(value: Any) -> dict[str, Any]:
    """Convert project reports without accidentally serialising a secret object."""

    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    # JSON round-tripping also gives callers a detached copy before a job puts
    # a report into its public state.
    return json.loads(json.dumps(value, ensure_ascii=False))


def _path_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ConfigurationError(f"{field_name} must be a text path")
    text = value.strip()
    if not text:
        raise ConfigurationError(f"{field_name} is required")
    if "\x00" in text or len(text) > 32_000:
        raise ConfigurationError(f"{field_name} is not a valid local path")
    return text


def _existing_directory(value: Any, field_name: str) -> Path:
    text = _path_text(value, field_name)
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        raise ConfigurationError(f"{field_name} must be an absolute path")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"{field_name} cannot be resolved") from exc
    if not resolved.is_dir():
        raise ConfigurationError(f"{field_name} must point to an existing directory")
    return resolved


def _optional_secret(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"{field_name} must be text when supplied")
    if "\x00" in value or len(value) > 16_384:
        raise ConfigurationError(f"{field_name} is invalid")
    return value or None


def _payload_value(payload: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    return default


def _payload_bool(payload: dict[str, Any], *names: str, default: bool = False) -> bool:
    value = _payload_value(payload, *names, default=default)
    if not isinstance(value, bool):
        joined = "/".join(names)
        raise ConfigurationError(f"{joined} must be true or false")
    return value


@dataclass(frozen=True)
class BuildRequest:
    """Validated job input.  Secret fields are intentionally never serialised."""

    source: Path
    template: Path
    config: BuildConfig
    translate: bool
    confirm: bool
    api_key: str | None = field(repr=False)
    sign_password: str | None = field(repr=False)
    thinking_enabled: bool = DEFAULT_TRANSLATION_THINKING_ENABLED
    reasoning_effort: str = DEFAULT_TRANSLATION_REASONING_EFFORT

    @classmethod
    def from_payload(cls, payload: dict[str, Any], tool_root: Path) -> "BuildRequest":
        source = _existing_directory(_payload_value(payload, "source"), "source")
        template_value = _payload_value(payload, "template", "template_path", default=str(tool_root / "templates" / "android-rpgmv"))
        template = _existing_directory(template_value, "template")
        app_name = _payload_value(payload, "app_name", "appName", default="RPG Maker MV")
        application_id = _payload_value(payload, "application_id", "applicationId", default="com.game2apk.app")
        version_name = _payload_value(payload, "version_name", "versionName", "version", default="1.0.0")
        version_code_raw = _payload_value(payload, "version_code", "versionCode", default=1)
        if isinstance(version_code_raw, bool):
            raise ConfigurationError("version_code must be an integer")
        try:
            version_code = int(version_code_raw)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("version_code must be an integer") from exc
        if not isinstance(app_name, str) or not isinstance(application_id, str) or not isinstance(version_name, str):
            raise ConfigurationError("app_name, application_id and version_name must be text")
        data = build_config(
            app_name=app_name,
            application_id=application_id,
            version_code=version_code,
            version_name=str(version_name),
            control=default_control_config(),
        )
        config = BuildConfig(
            data["appName"],
            data["applicationId"],
            data["versionCode"],
            data["versionName"],
            control_config=data["control"],
        )
        translate = _payload_bool(payload, "translate", default=False)
        confirm = _payload_bool(payload, "confirm", "confirm_third_party", default=False)
        if translate and not confirm:
            raise ConfigurationError("translation requires explicit third-party confirmation")
        thinking_enabled = _payload_bool(
            payload,
            "thinking_enabled",
            "thinkingEnabled",
            default=DEFAULT_TRANSLATION_THINKING_ENABLED,
        )
        reasoning_effort = normalize_reasoning_effort(
            _payload_value(payload, "reasoning_effort", "reasoningEffort", default=DEFAULT_TRANSLATION_REASONING_EFFORT)
        )
        return cls(
            source=source,
            template=template,
            config=config,
            translate=translate,
            confirm=confirm,
            api_key=_optional_secret(_payload_value(payload, "api_key", "apiKey"), "api_key"),
            sign_password=_optional_secret(_payload_value(payload, "sign_password", "signPassword"), "sign_password"),
            thinking_enabled=thinking_enabled,
            reasoning_effort=reasoning_effort,
        )


@dataclass
class Job:
    job_id: str
    kind: str
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    status: str = "queued"
    stage: str = "queued"
    fraction: float = 0.0
    message: str = "queued"
    created_at_utc: str = field(default_factory=now_utc)
    started_at_utc: str | None = None
    finished_at_utc: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    future: Future[None] | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _terminal(self) -> bool:
        return self.status in {"completed", "failed", "cancelled"}

    def mark_running(self) -> bool:
        with self._lock:
            if self._terminal() or self.cancel_event.is_set():
                return False
            self.status = "running"
            self.stage = "starting"
            self.message = "starting local task"
            self.started_at_utc = now_utc()
            return True

    def update_progress(self, stage: str, fraction: float, message: str, secrets: tuple[str, ...] = ()) -> None:
        with self._lock:
            if self._terminal():
                return
            self.stage = str(stage)[:80]
            self.fraction = max(0.0, min(1.0, float(fraction)))
            self.message = redact_text(message, secrets)[:MAX_JOB_MESSAGE_CHARS]

    def set_result(self, result: dict[str, Any]) -> None:
        with self._lock:
            self.result = _json_safe(result)

    def finish_completed(self, message: str) -> None:
        with self._lock:
            if self._terminal():
                return
            self.status = "completed"
            self.stage = "complete"
            self.fraction = 1.0
            self.message = message
            self.finished_at_utc = now_utc()

    def finish_failed(self, message: str, secrets: tuple[str, ...] = ()) -> None:
        with self._lock:
            if self._terminal():
                return
            self.status = "failed"
            self.stage = "failed"
            self.message = "task failed"
            self.error = redact_text(message, secrets)[:MAX_JOB_MESSAGE_CHARS]
            self.finished_at_utc = now_utc()

    def finish_cancelled(self) -> None:
        with self._lock:
            if self._terminal():
                return
            self.status = "cancelled"
            self.stage = "cancelled"
            self.message = "cancellation requested"
            self.finished_at_utc = now_utc()

    def to_public(self) -> dict[str, Any]:
        with self._lock:
            value: dict[str, Any] = {
                "id": self.job_id,
                "kind": self.kind,
                "status": self.status,
                "stage": self.stage,
                "fraction": self.fraction,
                "message": self.message,
                "createdAtUtc": self.created_at_utc,
                "startedAtUtc": self.started_at_utc,
                "finishedAtUtc": self.finished_at_utc,
            }
            if self.result is not None:
                value["result"] = _json_safe(self.result)
            if self.error:
                value["error"] = self.error
            return value


PipelineFactory: TypeAlias = Callable[..., PipelineService]


class JobManager:
    """Single-flight local job queue shared by the browser frontend."""

    def __init__(
        self,
        tool_root: str | Path,
        *,
        pipeline_factory: PipelineFactory = PipelineService,
        toolchain_discoverer: Callable[[str | Path], Any] = discover_configured,
    ):
        self.tool_root = Path(tool_root).resolve()
        self._pipeline_factory = pipeline_factory
        self._toolchain_discoverer = toolchain_discoverer
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="game2apk-backend")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._closed = False

    def _new_job(self, kind: str) -> Job:
        with self._lock:
            if self._closed:
                raise Game2ApkError("local backend is shutting down")
            if any(not existing._terminal() for existing in self._jobs.values()):
                raise Game2ApkError("another local task is already running")
            job = Job(uuid.uuid4().hex, kind)
            self._jobs[job.job_id] = job
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def submit_inspect(self, source: str | Path) -> Job:
        source_path = _existing_directory(str(source), "source")
        job = self._new_job("inspect")

        def runner() -> None:
            if not job.mark_running():
                job.finish_cancelled()
                return
            try:
                service = self._pipeline_factory(
                    self.tool_root,
                    progress=lambda stage, fraction, message: job.update_progress(stage, fraction, message),
                    cancel_event=job.cancel_event,
                )
                if job.cancel_event.is_set():
                    raise CancelledError("inspection cancelled")
                report = service.inspect(source_path)
                if job.cancel_event.is_set():
                    raise CancelledError("inspection cancelled")
                job.set_result({"inspection": _json_safe(report), "buildReady": not report.blocked})
                job.finish_completed("inspection completed" if not report.blocked else "inspection completed with blocking findings")
            except CancelledError:
                job.finish_cancelled()
            except Exception as exc:  # Errors stay user-visible but never include request secrets.
                job.finish_failed(str(exc))

        job.future = self._executor.submit(runner)
        return job

    def submit_build(self, request: BuildRequest) -> Job:
        job = self._new_job("build")
        secrets_to_redact = tuple(secret for secret in (request.api_key, request.sign_password) if secret)

        def progress(stage: str, fraction: float, message: str) -> None:
            job.update_progress(stage, fraction, message, secrets_to_redact)

        def runner() -> None:
            if not job.mark_running():
                job.finish_cancelled()
                return
            try:
                service = self._pipeline_factory(self.tool_root, progress=progress, cancel_event=job.cancel_event)
                if job.cancel_event.is_set():
                    raise CancelledError("build cancelled")
                inspection = service.inspect(request.source)
                if job.cancel_event.is_set():
                    raise CancelledError("build cancelled")
                job.set_result({"inspection": _json_safe(inspection)})
                if inspection.blocked:
                    raise Game2ApkError("RPG Maker MV inspection did not pass; inspect report is available")

                if job.cancel_event.is_set():
                    raise CancelledError("build cancelled")
                stage = service.stage(inspection)
                if job.cancel_event.is_set():
                    raise CancelledError("build cancelled")
                service.patch(stage, request.config)
                if job.cancel_event.is_set():
                    raise CancelledError("build cancelled")
                partial = {"inspection": _json_safe(inspection), "stage": {"projectId": stage.project_id, "sourceUnchanged": stage.source_unchanged}}
                if request.translate:
                    if not request.confirm:
                        raise ConfigurationError("translation requires explicit third-party confirmation")
                    translation = service.translate(
                        stage,
                        api_key=request.api_key,
                        confirmed_third_party=True,
                        force=True,
                        thinking_enabled=request.thinking_enabled,
                        reasoning_effort=request.reasoning_effort,
                    )
                    if job.cancel_event.is_set():
                        raise CancelledError("build cancelled")
                    partial["translation"] = _json_safe(translation)
                job.set_result(partial)

                if job.cancel_event.is_set():
                    raise CancelledError("build cancelled")
                configured_tools = self._toolchain_discoverer(str(request.template))
                missing = [item for item in missing_components(configured_tools) if item != "adb"]
                if missing:
                    raise Game2ApkError("Android toolchain is not ready: " + ", ".join(missing))
                result = service.build(
                    str(request.template),
                    stage,
                    request.config,
                    toolchain=configured_tools,
                    api_key=request.api_key,
                )
                partial["build"] = _json_safe(result)
                job.set_result(partial)
                if result.return_code != 0 or not result.apk_path:
                    raise Game2ApkError(f"Gradle build failed with exit code {result.return_code}")

                if job.cancel_event.is_set():
                    raise CancelledError("build cancelled")
                signing = service.sign(result, request.config, password=request.sign_password)
                if job.cancel_event.is_set():
                    raise CancelledError("build cancelled")
                verification = service.verify(result, request.config, install=False)
                promoted = service.promote(verification, request.config) if verification.signature_candidate else None
                partial.update(
                    {
                        "signing": _json_safe(signing),
                        "verification": _json_safe(verification),
                        "distApkPath": str(promoted) if promoted else None,
                    }
                )
                job.set_result(partial)
                job.finish_completed("build and static verification completed" if verification.passed else "build completed; static verification needs review")
            except CancelledError:
                job.finish_cancelled()
            except Exception as exc:
                job.finish_failed(str(exc), secrets_to_redact)

        job.future = self._executor.submit(runner)
        return job

    def submit_download(self, component: str, destination: str | Path) -> Job:
        """Download one approved toolchain component after frontend consent."""

        if component not in COMPONENTS:
            raise ConfigurationError("unsupported toolchain component")
        destination_path = _existing_directory(str(destination), "destination")
        job = self._new_job("download")

        def progress(done: int, total: int) -> None:
            if job.cancel_event.is_set():
                raise CancelledError("toolchain download cancelled")
            fraction = (float(done) / float(total)) if total else 0.0
            label = COMPONENTS[component]["label"]
            message = f"downloading {label}: {done // (1024 * 1024)} MiB"
            if total:
                message += f" / {total // (1024 * 1024)} MiB"
            job.update_progress("download", fraction, message)

        def runner() -> None:
            if not job.mark_running():
                job.finish_cancelled()
                return
            try:
                result = download_component(
                    component,
                    destination_path,
                    # Consent is collected in the browser immediately before
                    # this request; the backend never downloads on startup.
                    confirm=lambda _message: True,
                    progress=progress,
                )
                if job.cancel_event.is_set():
                    raise CancelledError("toolchain download cancelled")
                preferences = load_config()
                preference_key = "sdk_dir" if component == "android_cmdline_tools" else "jdk_dir"
                preferences[preference_key] = str(result.extracted_to)
                save_config(preferences)
                job.set_result(
                    {
                        "component": result.component,
                        "archive": str(result.archive),
                        "extractedTo": str(result.extracted_to),
                        "health": health_payload(self.tool_root),
                    }
                )
                job.finish_completed("toolchain download and extraction completed")
            except CancelledError:
                job.finish_cancelled()
            except Exception as exc:
                job.finish_failed(str(exc))

        job.future = self._executor.submit(runner)
        return job

    def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is None:
            return None
        job.cancel_event.set()
        future = job.future
        if future and future.cancel():
            job.finish_cancelled()
        return job

    def close(self) -> None:
        with self._lock:
            self._closed = True
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel_event.set()
        self._executor.shutdown(wait=False, cancel_futures=True)


def health_payload(tool_root: str | Path) -> dict[str, Any]:
    root = Path(tool_root).resolve()
    try:
        info = discover_configured(root / "templates" / "android-rpgmv")
        missing = missing_components(info)
        return {
            "ready": not missing,
            "missing": missing,
            "sdk_dir": info.sdk_dir or "",
            "jdk_dir": info.jdk_dir or "",
            "gradle_user_home": info.gradle_user_home or "",
            "wrapper": info.wrapper or "",
            "server": "loopback",
        }
    except Exception as exc:
        return {
            "ready": False,
            "missing": ["toolchain check failed"],
            "sdk_dir": "",
            "jdk_dir": "",
            "gradle_user_home": "",
            "server": "loopback",
            "error": redact_text(str(exc)),
        }


def save_toolchain_payload(payload: dict[str, Any], tool_root: str | Path) -> dict[str, Any]:
    current = load_config()
    updated = dict(current)
    for key in ("sdk_dir", "jdk_dir", "gradle_user_home"):
        if key not in payload:
            continue
        value = payload[key]
        if value is None or value == "":
            updated.pop(key, None)
            continue
        updated[key] = str(_existing_directory(value, key))
    save_config(updated)
    return health_payload(tool_root)


def native_choose_directory(kind: str, initial_dir: str | None = None) -> str | None:
    """Open the operating system directory picker without exposing file input.

    Tk's native dialog is created lazily on the request thread so ``--backend``
    does not initialise any visible desktop UI until the user presses Browse.
    This keeps the backend useful to a WebView launcher while retaining the
    normal Windows folder chooser rather than browser sandbox file APIs.
    """

    try:
        title = _BROWSE_TITLES[kind]
    except KeyError as exc:
        raise ConfigurationError("unsupported directory picker") from exc
    if sys.platform != "win32":
        raise Game2ApkError("native directory selection is only available on Windows")
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
            root.update_idletasks()
            chosen = filedialog.askdirectory(parent=root, title=title, initialdir=initial_dir or "")
        finally:
            root.destroy()
    except Exception as exc:
        raise Game2ApkError("native directory picker could not be opened") from exc
    if not chosen:
        return None
    return str(_existing_directory(chosen, "selected directory"))


class LocalBackendServer(ThreadingHTTPServer):
    """Threaded loopback server with its own short-lived frontend session."""

    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self,
        address: tuple[str, int],
        tool_root: str | Path,
        *,
        frontend_root: str | Path | None = None,
        idle_timeout_seconds: float | None = DEFAULT_IDLE_TIMEOUT_SECONDS,
        pipeline_factory: PipelineFactory = PipelineService,
        toolchain_discoverer: Callable[[str | Path], Any] = discover_configured,
    ):
        self.tool_root = str(Path(tool_root).resolve())
        self.frontend_root = str(Path(frontend_root or Path(self.tool_root) / "frontend").resolve())
        self.session_token = secrets.token_urlsafe(32)
        self.jobs = JobManager(self.tool_root, pipeline_factory=pipeline_factory, toolchain_discoverer=toolchain_discoverer)
        self.dialog_lock = threading.Lock()
        self.idle_timeout_seconds = max(0.0, float(idle_timeout_seconds or 0.0))
        self.browser_session_seen = False
        self.last_heartbeat = time.monotonic()
        super().__init__(address, _Handler)

    def note_browser_session(self) -> None:
        self.browser_session_seen = True
        self.last_heartbeat = time.monotonic()

    def note_heartbeat(self) -> None:
        self.last_heartbeat = time.monotonic()

    def should_idle_shutdown(self) -> bool:
        return bool(
            self.browser_session_seen
            and self.idle_timeout_seconds > 0
            and time.monotonic() - self.last_heartbeat > self.idle_timeout_seconds
        )

    def close_jobs(self) -> None:
        self.jobs.close()


class _Handler(BaseHTTPRequestHandler):
    """HTTP surface for static frontend files and the intentionally small API."""

    server_version = "game2apk-local-backend/2"

    @property
    def root(self) -> Path:
        return Path(self.server.frontend_root).resolve()  # type: ignore[attr-defined]

    @property
    def tool_root(self) -> Path:
        return Path(self.server.tool_root).resolve()  # type: ignore[attr-defined]

    def log_message(self, _format: str, *_args: object) -> None:
        # Request paths and bodies are never written to a console/log file.
        return

    def _json(self, payload: dict[str, Any], status: int = 200, *, cookie: str | None = None) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ConfigurationError("invalid request length") from exc
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ConfigurationError("request body is too large")
        try:
            raw = self.rfile.read(length)
            value = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError) as exc:
            raise ConfigurationError("request body must be a JSON object") from exc
        if not isinstance(value, dict):
            raise ConfigurationError("request body must be a JSON object")
        return value

    def _expected_origin(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def _session_authorized(self, *, allow_beacon: bool = False) -> bool:
        token = getattr(self.server, "session_token", None)
        if not isinstance(token, str):
            return False
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            supplied = cookies.get(SESSION_COOKIE_NAME)
            supplied_value = supplied.value if supplied is not None else ""
        except CookieError:
            return False
        if not hmac.compare_digest(supplied_value, token):
            return False
        origin = self.headers.get("Origin")
        expected_origin = self._expected_origin()
        if origin and not hmac.compare_digest(origin, expected_origin):
            return False
        # Read-only job polling uses the HttpOnly same-origin cookie. A
        # custom request header is required only for mutating requests, so
        # normal browser GETs remain simple and do not trigger a preflight.
        if self.command in {"GET", "HEAD"}:
            return True
        if hmac.compare_digest(self.headers.get(REQUEST_HEADER, ""), "1"):
            return True
        # sendBeacon cannot set a custom header. It is accepted only for a
        # same-origin shutdown POST with the HttpOnly session cookie.
        return bool(allow_beacon and origin and hmac.compare_digest(origin, expected_origin))

    def _require_session(self, *, allow_beacon: bool = False) -> bool:
        if self._session_authorized(allow_beacon=allow_beacon):
            return True
        self._json({"error": "local backend session is not authorized"}, 403)
        return False

    def _session_cookie(self) -> str | None:
        if not hasattr(self.server, "session_token"):
            return None
        return f"{SESSION_COOKIE_NAME}={self.server.session_token}; Path=/; HttpOnly; SameSite=Strict"

    def _jobs(self) -> JobManager:
        jobs = getattr(self.server, "jobs", None)
        if not isinstance(jobs, JobManager):
            raise Game2ApkError("job backend is not configured")
        return jobs

    def _serve_file(self, request_path: str) -> None:
        candidate = self.root / request_path.lstrip("/")
        try:
            candidate = candidate.resolve()
            candidate.relative_to(self.root)
        except (OSError, ValueError):
            self._json({"error": "invalid path"}, 400)
            return
        if not candidate.is_file():
            self._json({"error": "not found"}, 404)
            return
        try:
            data = candidate.read_bytes()
        except OSError:
            self._json({"error": "not found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'")
        cookie = self._session_cookie()
        if cookie:
            self.send_header("Set-Cookie", cookie)
            note_session = getattr(self.server, "note_browser_session", None)
            if callable(note_session):
                note_session()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(health_payload(self.tool_root))
            return
        if path.startswith("/api/jobs/"):
            if not self._require_session():
                return
            job_id = path.removeprefix("/api/jobs/")
            if "/" in job_id or not job_id:
                self._json({"error": "not found"}, 404)
                return
            job = self._jobs().get(job_id)
            if job is None:
                self._json({"error": "job not found"}, 404)
                return
            self._json({"job": job.to_public()})
            return
        if path in {"", "/"}:
            path = "/index.html"
        self._serve_file(path)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == "/api/shutdown":
            if not self._require_session(allow_beacon=True):
                return
            self._json({"accepted": True})
            threading.Thread(target=self.server.shutdown, daemon=True, name="game2apk-http-shutdown").start()
            return
        if not self._require_session():
            return
        try:
            if path == "/api/heartbeat":
                # A heartbeat does not need a body and exists only to let a
                # front-end launcher reclaim this local process after closure.
                try:
                    length = int(self.headers.get("Content-Length", "0") or 0)
                except ValueError as exc:
                    raise ConfigurationError("invalid heartbeat length") from exc
                if length < 0 or length > MAX_REQUEST_BYTES:
                    raise ConfigurationError("heartbeat body is too large")
                self.rfile.read(length)
                note_heartbeat = getattr(self.server, "note_heartbeat", None)
                if callable(note_heartbeat):
                    note_heartbeat()
                self._json({"ok": True})
                return
            payload = self._read_json()
            if path == "/api/browse":
                kind = _payload_value(payload, "kind")
                if not isinstance(kind, str) or kind not in _BROWSE_TITLES:
                    raise ConfigurationError("unsupported directory picker")
                initial_dir = _payload_value(payload, "initial_dir", "initialDir")
                if initial_dir is not None and isinstance(initial_dir, str):
                    try:
                        initial_dir = str(_existing_directory(initial_dir, "initial_dir"))
                    except ConfigurationError:
                        initial_dir = None
                else:
                    initial_dir = None
                lock = getattr(self.server, "dialog_lock", None)
                if lock is None:
                    selected = native_choose_directory(kind, initial_dir)
                else:
                    with lock:
                        selected = native_choose_directory(kind, initial_dir)
                self._json({"selected": bool(selected), "path": selected or ""})
                return
            if path == "/api/toolchain":
                self._json(save_toolchain_payload(payload, self.tool_root))
                return
            if path == "/api/inspect":
                source = _existing_directory(_payload_value(payload, "source"), "source")
                job = self._jobs().submit_inspect(source)
                self._json({"job": job.to_public()}, 202)
                return
            if path == "/api/build":
                request = BuildRequest.from_payload(payload, self.tool_root)
                job = self._jobs().submit_build(request)
                self._json({"job": job.to_public()}, 202)
                return
            if path == "/api/download":
                component = _payload_value(payload, "component")
                if not isinstance(component, str) or component not in COMPONENTS:
                    raise ConfigurationError("unsupported toolchain component")
                confirmed = _payload_bool(payload, "confirm", default=False)
                if not confirmed:
                    raise ConfigurationError("toolchain download requires explicit confirmation")
                destination = _existing_directory(_payload_value(payload, "destination"), "destination")
                job = self._jobs().submit_download(component, destination)
                self._json({"job": job.to_public()}, 202)
                return
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job_id = path[len("/api/jobs/") : -len("/cancel")].rstrip("/")
                if not job_id or "/" in job_id:
                    self._json({"error": "job not found"}, 404)
                    return
                job = self._jobs().cancel(job_id)
                if job is None:
                    self._json({"error": "job not found"}, 404)
                    return
                self._json({"job": job.to_public()})
                return
            self._json({"error": "endpoint not found"}, 404)
        except Game2ApkError as exc:
            self._json({"error": redact_text(str(exc))}, 400)
        except (OSError, ValueError, KeyError) as exc:
            self._json({"error": redact_text(str(exc))}, 400)

    def do_OPTIONS(self) -> None:  # noqa: N802 - no CORS preflight support by design
        self._json({"error": "cross-origin requests are not supported"}, 405)


def create_server(
    tool_root: str | Path,
    *,
    port: int = 0,
    idle_timeout_seconds: float | None = DEFAULT_IDLE_TIMEOUT_SECONDS,
    pipeline_factory: PipelineFactory = PipelineService,
    toolchain_discoverer: Callable[[str | Path], Any] = discover_configured,
) -> LocalBackendServer:
    root = Path(tool_root).resolve()
    frontend_root = root / "frontend"
    if not frontend_root.is_dir():
        raise FileNotFoundError(f"frontend assets are missing: {frontend_root}")
    if not 0 <= int(port) <= 65_535:
        raise ValueError("port must be between 0 and 65535")
    return LocalBackendServer(
        ("127.0.0.1", int(port)),
        root,
        frontend_root=frontend_root,
        idle_timeout_seconds=idle_timeout_seconds,
        pipeline_factory=pipeline_factory,
        toolchain_discoverer=toolchain_discoverer,
    )


def _parent_is_alive(parent_pid: int) -> bool:
    if parent_pid <= 0:
        return True
    if os.name == "nt":
        # Windows' ``os.kill(pid, 0)`` is not a reliable existence check: it
        # can report success for an already-exited process while its PID slot
        # is still retained.  Query the kernel process handle and inspect its
        # exit code instead, which is the same lifetime signal used by native
        # Windows process supervisors.
        try:
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            still_active = 259
            error_access_denied = 5
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(process_query_limited_information, False, parent_pid)
            if not handle:
                # A protected process can be alive but not queryable by the
                # current user.  Treat only access denial as alive; a missing
                # process must not keep the loopback backend running.
                return ctypes.get_last_error() == error_access_denied
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            # If a constrained Windows runtime unexpectedly lacks the API,
            # fail closed for process cleanup rather than creating an orphaned
            # backend.  The explicit heartbeat timeout remains a second path.
            return False
    try:
        # POSIX supports signal 0 as a process-existence check without sending
        # a signal. Permission failures mean it is still alive.
        os.kill(parent_pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _start_lifecycle_monitor(server: LocalBackendServer, parent_pid: int | None) -> threading.Thread | None:
    if not parent_pid and not server.idle_timeout_seconds:
        return None

    def monitor() -> None:
        while True:
            time.sleep(1.0)
            if parent_pid and not _parent_is_alive(parent_pid):
                server.shutdown()
                return
            if server.should_idle_shutdown():
                server.shutdown()
                return

    thread = threading.Thread(target=monitor, daemon=True, name="game2apk-backend-lifecycle")
    thread.start()
    return thread


def main(
    tool_root: str | Path,
    *,
    open_browser: bool = False,
    port: int = 0,
    parent_pid: int | None = None,
    idle_timeout_seconds: float | None = DEFAULT_IDLE_TIMEOUT_SECONDS,
) -> int:
    """Run the local backend until explicit shutdown, parent exit or idle expiry."""

    server = create_server(tool_root, port=port, idle_timeout_seconds=idle_timeout_seconds)
    url = f"http://127.0.0.1:{server.server_port}/"
    # This is deliberately the only startup stdout line: native launchers can
    # parse it without exposing a bearer/session token anywhere.
    print(json.dumps({"event": "READY", "url": url, "port": server.server_port}, ensure_ascii=False), flush=True)
    _start_lifecycle_monitor(server, parent_pid)
    if open_browser:
        webbrowser.open(url, new=1)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.close_jobs()
        server.server_close()
    return 0
