"""Safe discovery and selection contract for advanced cheat variables.

Only named RPG Maker MV variables from ``data/System.json`` are eligible.
The numeric ``variable:N`` identifier is stable across label translation, so
the desktop UI can preserve a user's choices while translated labels arrive.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from .errors import ConfigurationError
from .security import require_within


ADVANCED_CHEAT_VARIABLE_LIMIT = 256
_VARIABLE_ID = re.compile(r"^variable:([1-9][0-9]*)$")


def normalize_advanced_cheat_variable_ids(value: Any) -> list[str] | None:
    """Validate, de-duplicate and deterministically order selected IDs.

    ``None`` deliberately means "use the legacy default: every discoverable
    variable".  An explicit empty list means "show no advanced variables".
    This distinction preserves existing CLI/GUI/build callers while allowing
    the browser frontend to opt out of every item.
    """

    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise ConfigurationError("advancedCheatVariableIds must be an array or null")
    if len(value) > ADVANCED_CHEAT_VARIABLE_LIMIT:
        raise ConfigurationError(
            f"advancedCheatVariableIds cannot contain more than {ADVANCED_CHEAT_VARIABLE_LIMIT} entries"
        )
    selected: set[int] = set()
    for item in value:
        if not isinstance(item, str):
            raise ConfigurationError("every advanced cheat variable ID must be text")
        match = _VARIABLE_ID.fullmatch(item)
        if match is None:
            raise ConfigurationError("advanced cheat variable IDs must use the form variable:N")
        index = int(match.group(1))
        if index > 2_147_483_647:
            raise ConfigurationError("advanced cheat variable ID is outside the supported integer range")
        selected.add(index)
    if len(selected) > ADVANCED_CHEAT_VARIABLE_LIMIT:
        raise ConfigurationError(
            f"advancedCheatVariableIds cannot contain more than {ADVANCED_CHEAT_VARIABLE_LIMIT} unique entries"
        )
    return [f"variable:{index}" for index in sorted(selected)]


def _system_data(www_root: str | Path) -> dict[str, Any]:
    root = Path(www_root).resolve(strict=True)
    system_path = (root / "data" / "System.json").resolve(strict=True)
    require_within(system_path, root, "RPG Maker System.json")
    try:
        data = json.loads(system_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("unable to read RPG Maker data/System.json") from exc
    if not isinstance(data, dict) or not isinstance(data.get("variables"), list):
        raise ConfigurationError("RPG Maker data/System.json has no valid variables array")
    return data


def discover_advanced_cheat_variables(www_root: str | Path) -> list[tuple[int, str]]:
    """Return the first 256 named variables, matching the Android runtime."""

    values = _system_data(www_root)["variables"]
    discovered: list[tuple[int, str]] = []
    for index, raw_label in enumerate(values):
        if index <= 0 or not isinstance(raw_label, str):
            continue
        label = raw_label.strip()
        if not label:
            continue
        discovered.append((index, label))
        if len(discovered) >= ADVANCED_CHEAT_VARIABLE_LIMIT:
            break
    return discovered


def advanced_cheat_catalog(
    source_www: str | Path,
    *,
    translated_www: str | Path | None = None,
    status: str = "discovered",
) -> dict[str, Any]:
    """Build the JSON-safe UI catalog without exposing any other game data."""

    source_items = discover_advanced_cheat_variables(source_www)
    translated_by_id: dict[int, str] = {}
    if translated_www is not None:
        translated_by_id = dict(discover_advanced_cheat_variables(translated_www))
    items: list[dict[str, Any]] = []
    for index, source_label in source_items:
        translated_label = translated_by_id.get(index) if translated_www is not None else None
        display_label = translated_label or source_label
        items.append(
            {
                "id": f"variable:{index}",
                "kind": "variable",
                "index": index,
                "sourceLabel": source_label,
                "translatedLabel": translated_label,
                "displayLabel": display_label,
            }
        )
    return {"status": status, "items": items}


def validate_advanced_cheat_selection(
    www_root: str | Path,
    selected_ids: Iterable[str] | None,
) -> list[str] | None:
    """Validate an explicit selection against the staged runtime catalog."""

    normalized = normalize_advanced_cheat_variable_ids(
        None if selected_ids is None else list(selected_ids)
    )
    if normalized is None:
        return None
    discoverable = {
        f"variable:{index}" for index, _label in discover_advanced_cheat_variables(www_root)
    }
    unknown = [item for item in normalized if item not in discoverable]
    if unknown:
        preview = ", ".join(unknown[:8])
        suffix = " ..." if len(unknown) > 8 else ""
        raise ConfigurationError(
            f"advanced cheat variable selection contains IDs not discoverable in staged System.json: {preview}{suffix}"
        )
    return normalized
