"""Path and secret handling shared by all pipeline stages."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .errors import BlockedError, ConfigurationError


TOOL_MARKER = ".game2apk-work-marker.json"
TOOL_NAME = "game2apk-tool"
_SECRET_NAME = re.compile(r"(?:api[_-]?key|access[_-]?token|secret|password|passphrase|private[_-]?key|keystore)", re.I)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_DEEPSEEK_KEY = re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{8,}\b")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_path(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def is_within(child: str | os.PathLike[str], parent: str | os.PathLike[str]) -> bool:
    child_path = resolve_path(child)
    parent_path = resolve_path(parent)
    try:
        child_path.relative_to(parent_path)
        return True
    except ValueError:
        return False


def require_within(child: str | os.PathLike[str], parent: str | os.PathLike[str], label: str = "path") -> Path:
    child_path = resolve_path(child)
    if not is_within(child_path, parent):
        raise BlockedError(f"{label} escapes the permitted directory: {child_path}")
    return child_path


def stable_project_id(source_root: str | os.PathLike[str]) -> str:
    normalized = str(resolve_path(source_root)).casefold().replace("\\", "/")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"project-{digest[:16]}"


def redact_text(value: Any, secrets: Iterable[str] = ()) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    text = _BEARER.sub(r"\1<redacted>", text)
    text = _DEEPSEEK_KEY.sub("<redacted>", text)
    return text


def validate_secret_env_name(name: str, label: str = "secret environment variable") -> str:
    """Validate a variable *name* without ever treating it as a secret value."""

    if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
        raise ConfigurationError(f"{label} must be a valid environment variable name")
    return name


def read_secret_source(
    *,
    kind: str,
    env_name: str | None = None,
    from_stdin: bool = False,
    prompt: bool = False,
    default_env_name: str | None = None,
    input_stream=None,
    prompt_function=None,
) -> str | None:
    """Read a secret from an explicitly selected non-argv source.

    ``env_name`` is intentionally a variable name, never an environment value.
    When no source is selected, ``default_env_name`` may provide a documented
    variable name (for example ``DEEPSEEK_API_KEY``).  The default is otherwise
    ``None`` so signing can prefer its application-specific DPAPI credential.
    """

    selected = sum(bool(item) for item in (env_name, from_stdin, prompt))
    if selected > 1:
        raise ConfigurationError(f"choose one {kind} source: environment name, stdin, or prompt")
    if env_name is None and not from_stdin and not prompt:
        env_name = default_env_name
    if env_name is not None:
        variable = validate_secret_env_name(env_name, f"{kind} environment variable")
        value = os.environ.get(variable)
        if value:
            return value
        raise ConfigurationError(f"{kind} environment variable is unset or empty: {variable}")
    if from_stdin:
        stream = input_stream
        if stream is None:
            import sys

            stream = sys.stdin
        value = stream.readline()
        if value.endswith("\n"):
            value = value[:-1]
        if value.endswith("\r"):
            value = value[:-1]
        if value:
            return value
        raise ConfigurationError(f"{kind} stdin source was empty")
    if prompt:
        if prompt_function is None:
            import getpass

            prompt_function = getpass.getpass
        value = prompt_function(f"{kind}: ")
        if value:
            return value
        raise ConfigurationError(f"{kind} prompt source was empty")
    return None


def sanitized_child_environment(extra_secret_names: Iterable[str] = ()) -> dict[str, str]:
    """Return an environment that does not inherit unrelated credential values."""

    blocked_names = {name.casefold() for name in extra_secret_names}
    return {
        name: value
        for name, value in os.environ.items()
        if name.casefold() not in blocked_names and not is_secret_name(name)
    }


def is_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME.search(name))


def assert_no_secrets(value: Any, path: str = "root") -> None:
    """Reject likely credentials before a dict can enter APK-facing config."""

    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if is_secret_name(key_text) and item not in (None, "", False):
                raise BlockedError(f"secret-like configuration field is not allowed: {path}.{key_text}")
            assert_no_secrets(item, f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_no_secrets(item, f"{path}[{index}]")
    elif isinstance(value, str) and (_DEEPSEEK_KEY.search(value) or "BEGIN PRIVATE KEY" in value):
        raise BlockedError(f"secret-like value is not allowed in {path}")


def atomic_write_text(path: str | os.PathLike[str], text: str, encoding: str = "utf-8") -> Path:
    destination = resolve_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return destination


def atomic_write_json(path: str | os.PathLike[str], data: Any) -> Path:
    return atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def create_work_marker(work_dir: str | os.PathLike[str], project_id: str, source_root: str | os.PathLike[str]) -> Path:
    path = resolve_path(work_dir)
    path.mkdir(parents=True, exist_ok=True)
    marker_path = path / TOOL_MARKER
    if marker_path.exists():
        try:
            existing = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BlockedError(f"existing work marker is invalid: {marker_path}") from exc
        if existing.get("tool") != TOOL_NAME or existing.get("project_id") != project_id:
            raise BlockedError(f"work directory belongs to another project: {path}")
        return marker_path
    return atomic_write_json(
        marker_path,
        {
            "tool": TOOL_NAME,
            "marker_version": 1,
            "project_id": project_id,
            "source_root": str(resolve_path(source_root)),
            "created_at_utc": now_utc(),
        },
    )


def safe_remove_workdir(work_dir: str | os.PathLike[str], work_base: str | os.PathLike[str], project_id: str) -> None:
    """Delete only a marked, project-matching child of the tool work area."""

    target = require_within(work_dir, work_base, "work directory")
    base = resolve_path(work_base)
    if target == base or target.parent != base:
        raise BlockedError("refusing to remove a non-project work directory")
    marker_path = target / TOOL_MARKER
    if not marker_path.is_file():
        raise BlockedError("refusing to remove an unmarked work directory")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BlockedError("refusing to remove a work directory with an unreadable marker") from exc
    if marker.get("tool") != TOOL_NAME or marker.get("project_id") != project_id:
        raise BlockedError("refusing to remove a work directory with a mismatched marker")
    shutil.rmtree(target)


def safe_cleanup_run_artifacts(
    run_dir: str | os.PathLike[str],
    work_base: str | os.PathLike[str],
    project_id: str,
    *,
    remove_staged: bool,
) -> tuple[str, ...]:
    """Remove only regenerable game copies from one owned build run.

    A run keeps its small audit files (manifest, build log, signing report and
    verification report), while the large ``staged/www``, generated Android
    project and external resource-pack directories are disposable.  The
    marker/manifest checks deliberately happen before any delete so a forged
    report cannot turn cleanup into an arbitrary path removal.

    ``remove_staged=False`` is used after a failed/cancelled build: the staged
    tree is the resumable checkpoint.  A successful promoted build can remove
    it as well because the signed APK/resource pack now live in ``dist``.
    """

    raw_target = Path(run_dir).expanduser()
    if raw_target.is_symlink():
        raise BlockedError("refusing to clean a symlinked build run")
    target = require_within(raw_target, work_base, "build run")
    base = resolve_path(work_base)
    project_dir = target.parent.parent if target.parent.name == "runs" else target.parent
    if target == base or project_dir.parent != base or project_dir.name != project_id or target.parent.name != "runs":
        raise BlockedError("refusing to clean a run outside its marked project")

    marker_path = project_dir / TOOL_MARKER
    if not marker_path.is_file():
        raise BlockedError("refusing to clean a run without a project marker")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BlockedError("refusing to clean a run with an unreadable marker") from exc
    if marker.get("tool") != TOOL_NAME or marker.get("project_id") != project_id:
        raise BlockedError("refusing to clean a run with a mismatched project marker")

    manifest_path = target / "stage-manifest.json"
    if not manifest_path.is_file():
        raise BlockedError("refusing to clean a run without a stage manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BlockedError("refusing to clean a run with an unreadable stage manifest") from exc
    if not isinstance(manifest, dict):
        raise BlockedError("refusing to clean a run with an invalid stage manifest")
    if manifest.get("schemaVersion") != 1 or manifest.get("projectId") != project_id or manifest.get("runId") != target.name:
        raise BlockedError("refusing to clean a run with a mismatched stage manifest")
    if manifest.get("manifestPath") != str(manifest_path.resolve()):
        raise BlockedError("refusing to clean a run whose manifest path is not self-identifying")

    names = ["android", "resource-pack"]
    if remove_staged:
        names.append("staged")
    removed: list[str] = []
    for name in names:
        child = target / name
        if not child.exists() and not child.is_symlink():
            continue
        if child.is_symlink():
            raise BlockedError(f"refusing to clean a symlinked run artifact: {child}")
        require_within(child, target, f"run artifact {name}")
        shutil.rmtree(child)
        removed.append(name)
    return tuple(removed)
