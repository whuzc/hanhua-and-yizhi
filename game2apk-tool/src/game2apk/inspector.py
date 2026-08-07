"""Strict RPG Maker MV inspection with static Android compatibility gates."""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .errors import BlockedError
from .models import InspectionReport, Risk


REQUIRED_FILES = ("index.html", "js/rpg_core.js", "data/System.json")
MV_VERSION_RE = re.compile(r"(?:RPG Maker MV\s*(?:v|version\s*)?|rpg_core\.js\s+v)([0-9]+(?:\.[0-9]+){1,2})", re.I)
DIMENSION_RE = re.compile(r"(?:screen|graphics|width|height|resolution)[^\n]{0,80}?([0-9]{3,5})", re.I)
RESOURCE_RE = re.compile(r"(?i)(?:^|[\"'`\s(])((?:[A-Za-z0-9_.\-/]+)\.(?:png|ogg|m4a|webm|rpgmvp|rpgmvo|rpgmvm))(?=$|[\"'`\s),])")
RISK_PATTERNS = {
    "require": re.compile(r"\brequire\s*\(", re.I),
    "fs": re.compile(r"\bfs\b", re.I),
    "path": re.compile(r"\bpath\b", re.I),
    "process": re.compile(r"\bprocess\b", re.I),
    "nw.gui": re.compile(r"\bnw\.gui\b", re.I),
}


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(_read_text(path))
    except (OSError, ValueError) as exc:
        raise BlockedError(f"invalid JSON: {path}") from exc


def _parse_plugins(path: Path) -> list[dict[str, Any]]:
    text = _read_text(path)
    marker = text.find("[")
    if marker < 0:
        raise BlockedError(f"plugins.js has no $plugins array: {path}")
    try:
        value, _ = json.JSONDecoder().raw_decode(text[marker:])
    except json.JSONDecodeError as exc:
        raise BlockedError(f"plugins.js cannot be parsed as JSON: {path}") from exc
    if not isinstance(value, list):
        raise BlockedError(f"plugins.js $plugins value is not an array: {path}")
    return [item for item in value if isinstance(item, dict)]


def _walk_files(root: Path) -> Iterable[tuple[Path, str]]:
    """Yield files without following symlinks, with POSIX relative paths."""

    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            if entry.is_symlink():
                yield path, relative
            elif entry.is_dir(follow_symlinks=False):
                stack.append(path)
            elif entry.is_file(follow_symlinks=False):
                yield path, relative


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    match = re.search(r"-?\d+", str(value))
    return int(match.group(0)) if match else None


def _find_dimension(params: dict[str, Any], axis: str) -> int | None:
    candidates: list[tuple[int, str, Any]] = []
    for key, value in params.items():
        key_text = str(key).lower().replace("_", " ")
        if axis not in key_text:
            continue
        score = 0
        if "screen" in key_text:
            score += 3
        if "resolution" in key_text or "graphics" in key_text:
            score += 2
        if "width" == key_text.strip() or "height" == key_text.strip():
            score += 1
        candidates.append((score, key_text, value))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return _parse_int(candidates[0][2])


def _find_yep_resolution(www: Path, plugins: list[dict[str, Any]], default: tuple[int, int]) -> tuple[int, int, bool]:
    width, height = default
    found = False
    yep = next(
        (
            plugin
            for plugin in plugins
            if str(plugin.get("name", "")).casefold() == "yep_coreengine" and bool(plugin.get("status"))
        ),
        None,
    )
    if yep is None:
        return width, height, False
    params = yep.get("parameters") or yep.get("params") or {}
    if isinstance(params, dict):
        configured_width = _find_dimension(params, "width")
        configured_height = _find_dimension(params, "height")
        if configured_width and configured_height:
            width, height, found = configured_width, configured_height, True
    if not found:
        plugin_name = str(yep.get("name", "YEP_CoreEngine"))
        source = www / "js" / "plugins" / f"{plugin_name}.js"
        if source.is_file():
            text = _read_text(source)
            width_match = re.search(r"(?:screenWidth|width)\s*[:=]\s*(?:Number\()?\s*[\"']?(\d{3,5})", text, re.I)
            height_match = re.search(r"(?:screenHeight|height)\s*[:=]\s*(?:Number\()?\s*[\"']?(\d{3,5})", text, re.I)
            if width_match and height_match:
                width, height, found = int(width_match.group(1)), int(height_match.group(1)), True
    return width, height, found


def _custom_keys(www: Path, plugins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for plugin in plugins:
        if not plugin.get("status"):
            continue
        name = str(plugin.get("name", ""))
        params = plugin.get("parameters") or plugin.get("params") or {}
        if not isinstance(params, dict):
            continue
        for raw_key, raw_value in params.items():
            key = str(raw_key).strip()
            normalized = re.sub(r"[^a-z]", "", key.casefold())
            key_name: str | None = None
            if key.casefold() in {"a", "keya", "buttona", "akey"} or normalized in {"a", "keya", "buttona", "akey"}:
                key_name = "A"
            elif key.casefold() in {"w", "keyw", "buttonw", "wkey"} or normalized in {"w", "keyw", "buttonw", "wkey"}:
                key_name = "W"
            elif "ctrl" in key.casefold() or "control" in key.casefold():
                key_name = "Ctrl"
            if key_name is None:
                continue
            event_id = _parse_int(raw_value)
            if event_id is None:
                continue
            result.append({"key": key_name, "common_event_id": event_id, "plugin": name, "source": "plugins.js"})
        if name.casefold() == "uta_messageskip":
            skip_key = str(params.get("Skip Key", "")).casefold()
            if skip_key in {"control", "ctrl", "17"}:
                result.append({"key": "Ctrl", "action": "skip", "plugin": name, "source": "plugins.js"})
        if name.casefold() == "tmcommoneventkey":
            for raw_key, raw_value in params.items():
                match = re.fullmatch(r"commonKey([A-Z])", str(raw_key))
                event_id = _parse_int(raw_value)
                if not match or not event_id:
                    continue
                key_name = match.group(1)
                if key_name in {"A", "W"}:
                    result.append({"key": key_name, "common_event_id": event_id, "plugin": name, "source": "plugins.js"})
    # Some MV plugin configurations use a list of entries instead of named keys.
    if any(item.get("name") == "TMCommonEventKey" and item.get("status") for item in plugins):
        source = www / "js" / "plugins" / "TMCommonEventKey.js"
        if source.is_file():
            text = _read_text(source)
            for key_name, code in (("A", 65), ("W", 87), ("Ctrl", 17)):
                if not any(item["key"] == key_name for item in result):
                    match = re.search(rf"{code}\D{{0,80}}(?:common|event)\D{{0,20}}(\d+)", text, re.I)
                    if match:
                        result.append(
                            {
                                "key": key_name,
                                "common_event_id": int(match.group(1)),
                                "plugin": "TMCommonEventKey",
                                "source": "TMCommonEventKey.js",
                            }
                        )
    # Stable display order is useful in both the GUI and acceptance reports.
    return sorted(result, key=lambda item: (item["key"], item.get("common_event_id", -1), item.get("action", ""), item["plugin"]))


def _json_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _json_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _json_strings(item)


def _missing_references(www: Path, paths: set[str]) -> list[str]:
    missing: set[str] = set()
    for file_path, relative in _walk_files(www):
        if file_path.is_symlink() or file_path.suffix.casefold() != ".json":
            continue
        try:
            data = _read_json(file_path)
        except BlockedError:
            continue
        for text in _json_strings(data):
            for match in RESOURCE_RE.finditer(text):
                ref = match.group(1).replace("\\", "/").lstrip("./")
                candidates = {ref}
                if ref.casefold().endswith(".png"):
                    candidates.add(ref[:-4] + ".rpgmvp")
                elif ref.casefold().endswith(".ogg"):
                    candidates.add(ref[:-4] + ".rpgmvo")
                if not any(candidate in paths for candidate in candidates):
                    missing.add(f"{relative}: {ref}")
    return sorted(missing)


def inspect_game(source: str | os.PathLike[str]) -> InspectionReport:
    selected = Path(source).expanduser().resolve(strict=False)
    if (selected / "index.html").is_file() and selected.name.casefold() == "www":
        source_root = selected.parent
        www = selected
    elif (selected / "www").is_dir():
        source_root = selected
        www = selected / "www"
    else:
        source_root = selected
        www = selected / "www"

    required = [relative for relative in REQUIRED_FILES if not (www / relative).is_file()]
    risks: list[Risk] = []
    if required:
        risks.append(Risk("unknown-engine", "block", "input is not a complete unpacked RPG Maker MV project", required))
        return InspectionReport(
            source_root=str(source_root),
            www_root=str(www),
            engine="unknown",
            engine_version=None,
            title=None,
            effective_width=None,
            effective_height=None,
            mv_default_width=None,
            mv_default_height=None,
            outer_window_width=None,
            outer_window_height=None,
            has_encrypted_images=False,
            has_encrypted_audio=False,
            encryption_key_present=False,
            file_count=0,
            total_bytes=0,
            extensions={},
            enabled_plugins=[],
            disabled_plugins=[],
            custom_keys=[],
            risks=risks,
            missing_required=required,
            status="blocked",
        )

    core_path = www / "js" / "rpg_core.js"
    system_path = www / "data" / "System.json"
    package_path = www / "package.json"
    plugins_path = www / "js" / "plugins.js"
    core_text = _read_text(core_path)
    system = _read_json(system_path)
    package = _read_json(package_path) if package_path.is_file() else {}
    plugins = _parse_plugins(plugins_path) if plugins_path.is_file() else []
    if not plugins_path.is_file():
        risks.append(Risk("plugins-missing", "warning", "js/plugins.js is absent; enabled plugin inventory is incomplete"))

    version_match = MV_VERSION_RE.search(core_text)
    engine_version = version_match.group(1) if version_match else None
    if not version_match:
        risks.append(Risk("mv-version-unresolved", "warning", "RPG Maker MV version string was not found in rpg_core.js"))

    default_width, default_height = 816, 624
    core_width = re.search(r"(?:_defaultWidth|width)\s*=\s*(\d{3,5})", core_text, re.I)
    core_height = re.search(r"(?:_defaultHeight|height)\s*=\s*(\d{3,5})", core_text, re.I)
    if core_width and core_height:
        default_width, default_height = int(core_width.group(1)), int(core_height.group(1))

    outer_window = package.get("window") if isinstance(package, dict) else {}
    if not isinstance(outer_window, dict):
        outer_window = {}
    outer_width = _parse_int(outer_window.get("width"))
    outer_height = _parse_int(outer_window.get("height"))
    effective_width, effective_height, yep_override = _find_yep_resolution(www, plugins, (default_width, default_height))
    if not yep_override and outer_width and outer_height:
        # Outer NW metadata is not substituted for the MV runtime size.
        risks.append(
            Risk(
                "resolution-metadata-difference",
                "warning",
                "outer package window dimensions differ from the effective MV runtime dimensions",
                [f"outer={outer_width}x{outer_height}", f"runtime={effective_width}x{effective_height}"],
            )
        )
    if yep_override:
        risks.append(
            Risk(
                "yep-runtime-resolution",
                "info",
                "YEP_CoreEngine parameters override the MV default; effective resolution is taken from the plugin",
                [f"effective={effective_width}x{effective_height}", f"default={default_width}x{default_height}"],
            )
        )

    enabled_plugins = sorted(str(item.get("name")) for item in plugins if item.get("status") and item.get("name"))
    disabled_plugins = sorted(str(item.get("name")) for item in plugins if not item.get("status") and item.get("name"))
    plugin_risks: dict[str, list[str]] = {}
    for plugin_name in enabled_plugins:
        plugin_path = www / "js" / "plugins" / f"{plugin_name}.js"
        if not plugin_path.is_file():
            risks.append(Risk("plugin-missing", "block", f"enabled plugin source is missing: {plugin_name}", [plugin_name]))
            continue
        plugin_text = _read_text(plugin_path)
        matches = [name for name, pattern in RISK_PATTERNS.items() if pattern.search(plugin_text)]
        if matches:
            plugin_risks[plugin_name] = matches
            risks.append(
                Risk(
                    "node-nw-risk",
                    "warning",
                    f"enabled plugin contains Node/NW-specific symbols: {plugin_name}",
                    matches,
                )
            )

    extension_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "bytes": 0})
    all_paths: set[str] = set()
    lower_paths: dict[str, list[str]] = defaultdict(list)
    long_paths: list[str] = []
    total_bytes = 0
    file_count = 0
    resource_headers: dict[str, int] = defaultdict(int)
    for path, relative in _walk_files(www):
        if path.is_symlink():
            risks.append(Risk("symlink", "block", "symlinked source content is not copied", [relative]))
            continue
        try:
            size = path.stat().st_size
        except OSError:
            risks.append(Risk("stat-failed", "block", "unable to stat source file", [relative]))
            continue
        file_count += 1
        total_bytes += size
        suffix = path.suffix.casefold() or "<none>"
        extension_stats[suffix]["count"] += 1
        extension_stats[suffix]["bytes"] += size
        all_paths.add(relative)
        lower_paths[relative.casefold()].append(relative)
        absolute_text = str(path)
        if len(absolute_text) > 240 or any(len(part) > 120 for part in Path(relative).parts):
            long_paths.append(relative)
        if suffix in {".rpgmvp", ".rpgmvo", ".rpgmvm"}:
            try:
                with path.open("rb") as handle:
                    header_ok = handle.read(4) == b"RPGM"
                resource_headers["valid" if header_ok else "invalid"] += 1
            except OSError:
                resource_headers["invalid"] += 1

    case_collisions = sorted(values for values in lower_paths.values() if len(values) > 1)
    if case_collisions:
        risks.append(Risk("case-collision", "block", "Android case-sensitive assets have colliding paths", case_collisions[:20]))
    if long_paths:
        risks.append(Risk("long-path", "warning", "one or more asset paths are close to Windows path limits", long_paths[:20]))
    if resource_headers.get("invalid"):
        risks.append(Risk("encrypted-header", "warning", "some encrypted resource files do not have the RPGMV header", [str(resource_headers["invalid"])]))

    has_images = bool(system.get("hasEncryptedImages"))
    has_audio = bool(system.get("hasEncryptedAudio"))
    key_present = bool(system.get("encryptionKey"))
    if has_images or has_audio:
        risks.append(Risk("encrypted-assets", "info", "RPG Maker encrypted assets will be preserved; no decryption is performed"))

    source_writable = os.access(source_root, os.W_OK) or os.access(www, os.W_OK)
    if source_writable:
        risks.append(Risk("source-writable", "warning", "source appears writable; the stage service will still never write to it"))

    missing_references = _missing_references(www, all_paths)
    if missing_references:
        risks.append(Risk("missing-reference", "warning", "some explicit asset references do not resolve case-sensitively", missing_references[:20]))

    title = system.get("gameTitle") if isinstance(system, dict) else None
    if not title and isinstance(package, dict):
        title = package.get("name")
    custom_keys = _custom_keys(www, plugins)
    if any(item.get("key") == "A" and item.get("common_event_id") == 25 for item in custom_keys):
        pass
    if any(item.get("key") == "W" and item.get("common_event_id") == 294 for item in custom_keys):
        pass
    if any(item.get("key") == "Ctrl" for item in custom_keys):
        pass

    status = "blocked" if any(risk.level == "block" for risk in risks) else ("needs-patch" if any(risk.level == "warning" for risk in risks) else "compatible")
    return InspectionReport(
        source_root=str(source_root),
        www_root=str(www),
        engine="RPG Maker MV",
        engine_version=engine_version,
        title=str(title) if title is not None else None,
        effective_width=effective_width,
        effective_height=effective_height,
        mv_default_width=default_width,
        mv_default_height=default_height,
        outer_window_width=outer_width,
        outer_window_height=outer_height,
        has_encrypted_images=has_images,
        has_encrypted_audio=has_audio,
        encryption_key_present=key_present,
        file_count=file_count,
        total_bytes=total_bytes,
        extensions=dict(extension_stats),
        enabled_plugins=enabled_plugins,
        disabled_plugins=disabled_plugins,
        custom_keys=custom_keys,
        risks=risks,
        source_writable=source_writable,
        missing_references=missing_references,
        case_collisions=case_collisions,
        long_paths=long_paths,
        resource_headers=dict(resource_headers),
        plugin_risks=plugin_risks,
        status=status,
    )
