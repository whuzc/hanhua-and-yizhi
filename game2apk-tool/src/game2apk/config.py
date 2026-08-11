"""Versioned Android control configuration and build settings."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .cheat_catalog import normalize_advanced_cheat_variable_ids
from .errors import ConfigurationError
from .models import BuildConfig
from .security import assert_no_secrets, atomic_write_json


CONFIG_SCHEMA_VERSION = 1
_APPLICATION_ID = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+$")
_CUSTOM_BUTTON_ID = re.compile(r"^custom_[a-z0-9][a-z0-9_-]{0,31}$")
_BUTTON_CONTRACT = {
    "up": (38, "hold"),
    "down": (40, "hold"),
    "left": (37, "hold"),
    "right": (39, "hold"),
    "confirm": (13, "tap"),
    "cancel": (88, "tap"),
    "esc": (27, "tap"),
    "portrait": (65, "tap"),
}


def default_control_config() -> dict[str, Any]:
    return {
        "schemaVersion": CONFIG_SCHEMA_VERSION,
        "touch": {"cancelKeyCode": 27, "twoFingerWindowMs": 250, "touchSlopPx": 24},
        "overlay": {"opacity": 0.38, "hiddenByDefault": False},
        "buttons": [
            {"id": "left", "label": "\u2190", "keyCode": 37, "mode": "hold", "x": 0.04, "y": 0.80, "width": 0.10, "height": 0.12},
            {"id": "up", "label": "\u2191", "keyCode": 38, "mode": "hold", "x": 0.15, "y": 0.67, "width": 0.10, "height": 0.12},
            {"id": "down", "label": "\u2193", "keyCode": 40, "mode": "hold", "x": 0.15, "y": 0.82, "width": 0.10, "height": 0.12},
            {"id": "right", "label": "\u2192", "keyCode": 39, "mode": "hold", "x": 0.26, "y": 0.80, "width": 0.10, "height": 0.12},
            {"id": "confirm", "label": "OK", "keyCode": 13, "mode": "tap", "x": 0.67, "y": 0.58, "width": 0.14, "height": 0.10},
            {"id": "cancel", "label": "X", "keyCode": 88, "mode": "tap", "x": 0.83, "y": 0.58, "width": 0.14, "height": 0.10},
            {"id": "esc", "label": "ESC", "keyCode": 27, "mode": "tap", "x": 0.67, "y": 0.71, "width": 0.14, "height": 0.10},
            {"id": "portrait", "label": "A", "keyCode": 65, "mode": "tap", "x": 0.83, "y": 0.71, "width": 0.14, "height": 0.10},
        ],
    }


def default_application_id(project_id: str) -> str:
    suffix = re.sub(r"[^a-z0-9]", "", project_id.lower()) or "game"
    return f"com.game2apk.{suffix}"


def build_config(
    app_name: str = "仙肴圣餐超魔改 Ver22",
    application_id: str = "com.game2apk.xianyaoshengcanver22",
    # Keep these defaults monotonic with the released 1.0.3 build. Android
    # accepts an in-place update only when the package/signing identity stays
    # the same and versionCode increases.
    version_code: int = 9,
    version_name: str = "1.4.0",
    icon_path: str | None = None,
    control: dict[str, Any] | None = None,
    advanced_cheat_variable_ids: list[str] | None = None,
) -> dict[str, Any]:
    control_data = control if control is not None else default_control_config()
    validate_control_config(control_data)
    if not app_name.strip():
        raise ConfigurationError("application display name must not be empty")
    if not _APPLICATION_ID.fullmatch(application_id):
        raise ConfigurationError("applicationId must be a lowercase Android package name")
    if isinstance(version_code, bool) or not isinstance(version_code, int) or version_code < 1 or version_code > 2_147_483_647:
        raise ConfigurationError("versionCode must be positive")
    if not version_name.strip():
        raise ConfigurationError("versionName must not be empty")
    data = {
        "schemaVersion": CONFIG_SCHEMA_VERSION,
        "appName": app_name,
        "applicationId": application_id,
        "versionCode": int(version_code),
        "versionName": version_name,
        "control": control_data,
        "advancedCheatVariableIds": normalize_advanced_cheat_variable_ids(
            advanced_cheat_variable_ids
        ),
    }
    if icon_path:
        data["iconName"] = Path(icon_path).name
    assert_no_secrets(data)
    return data


def validate_control_config(data: dict[str, Any]) -> None:
    if not isinstance(data, dict) or data.get("schemaVersion") != CONFIG_SCHEMA_VERSION:
        raise ConfigurationError(f"unsupported control schemaVersion; expected {CONFIG_SCHEMA_VERSION}")
    if "tap" in data or "joystick" in data:
        raise ConfigurationError("legacy tap/joystick controls are not supported; use touch and four-way buttons")
    touch = data.get("touch")
    overlay = data.get("overlay")
    buttons = data.get("buttons")
    if not isinstance(touch, dict) or not isinstance(overlay, dict) or not isinstance(buttons, list):
        raise ConfigurationError("control config is missing a required object or buttons array")
    cancel_key = touch.get("cancelKeyCode")
    if isinstance(cancel_key, bool) or not isinstance(cancel_key, int) or cancel_key != 27:
        raise ConfigurationError("control.touch.cancelKeyCode must be 27")
    window = touch.get("twoFingerWindowMs")
    if isinstance(window, bool) or not isinstance(window, int) or not 50 <= window <= 1000:
        raise ConfigurationError("control.touch.twoFingerWindowMs must be an integer between 50 and 1000")
    slop = touch.get("touchSlopPx")
    if isinstance(slop, bool) or not isinstance(slop, (int, float)) or not 1 <= slop <= 128:
        raise ConfigurationError("control.touch.touchSlopPx must be between 1 and 128")
    opacity = overlay.get("opacity")
    if isinstance(opacity, bool) or not isinstance(opacity, (int, float)) or not 0 <= opacity <= 1:
        raise ConfigurationError("overlay.opacity must be in [0, 1]")
    if not isinstance(overlay.get("hiddenByDefault"), bool):
        raise ConfigurationError("overlay.hiddenByDefault must be boolean")
    if len(buttons) < len(_BUTTON_CONTRACT) or len(buttons) > len(_BUTTON_CONTRACT) + 32:
        raise ConfigurationError("control.buttons must contain the eight required buttons and at most 32 custom buttons")

    seen: set[str] = set()
    rects: list[tuple[str, float, float, float, float]] = []
    for button in buttons:
        if not isinstance(button, dict) or not isinstance(button.get("id"), str) or not isinstance(button.get("label"), str):
            raise ConfigurationError("every button needs id and label")
        button_id = button["id"]
        if button_id in seen:
            raise ConfigurationError(f"duplicate button id: {button_id}")
        seen.add(button_id)
        if button_id not in _BUTTON_CONTRACT and not _CUSTOM_BUTTON_ID.fullmatch(button_id):
            raise ConfigurationError(f"unsupported button id: {button_id}")
        key_code = button.get("keyCode")
        if isinstance(key_code, bool) or not isinstance(key_code, int) or not 0 <= key_code <= 512:
            raise ConfigurationError(f"button {button_id} keyCode must be between 0 and 512")
        mode = button.get("mode")
        if mode not in {"tap", "hold"}:
            raise ConfigurationError(f"button {button_id} mode must be tap or hold")
        visible = button.get("visible", True)
        if not isinstance(visible, bool):
            raise ConfigurationError(f"button {button_id} visible must be boolean")
        if len(button["label"].strip()) > 40:
            raise ConfigurationError(f"button {button_id} label is too long")
        if not all(key in button for key in ("x", "y", "width", "height")):
            raise ConfigurationError(f"button layout requires x, y, width and height: {button_id}")
        values = [button[key] for key in ("x", "y", "width", "height")]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            raise ConfigurationError(f"button layout must contain numeric values: {button_id}")
        x, y, width, height = (float(value) for value in values)
        if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > 1 or y + height > 1:
            raise ConfigurationError(f"button layout must fit normalized screen: {button_id}")
        if visible:
            rects.append((button_id, x, y, x + width, y + height))

    if not set(_BUTTON_CONTRACT).issubset(seen):
        raise ConfigurationError("control.buttons must include up/down/left/right/confirm/cancel/esc/portrait")
    for index, (name, left, top, right, bottom) in enumerate(rects):
        for other, other_left, other_top, other_right, other_bottom in rects[index + 1:]:
            if left < other_right and other_left < right and top < other_bottom and other_top < bottom:
                raise ConfigurationError(f"button layouts overlap: {name} and {other}")


def write_android_config(path: str | Path, data: dict[str, Any]) -> Path:
    # The Windows-side build model may wrap the Android contract in a
    # ``control`` field together with app metadata. The Android template
    # intentionally consumes the contract at the top level.
    control = data.get("control") if isinstance(data.get("control"), dict) else data
    if control.get("schemaVersion") != CONFIG_SCHEMA_VERSION:
        raise ConfigurationError("refusing to write unknown config schema")
    validate_control_config(control)
    assert_no_secrets(data)
    return atomic_write_json(path, control)


def load_android_config(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"unable to read config: {path}") from exc
    control = data.get("control") if isinstance(data.get("control"), dict) else data
    if control.get("schemaVersion") != CONFIG_SCHEMA_VERSION:
        raise ConfigurationError(f"unsupported config schemaVersion: {control.get('schemaVersion')!r}")
    validate_control_config(control)
    assert_no_secrets(data)
    return control
