"""Safe RPG Maker MV text extraction and optional DeepSeek pre-translation."""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from .errors import BlockedError, CancelledError, ConfigurationError, TranslationError
from .models import TranslationEntry, TranslationFailure, TranslationReport
from .security import atomic_write_json, redact_text


PROMPT_VERSION = "mv-safe-v2-non-chinese"
# The cheat-label pass has a stricter output contract than ordinary game
# dialogue.  Keep its cache namespace separate so a previously cached generic
# translation (which may contain Japanese/English) can never satisfy the
# mandatory Simplified-Chinese label pass.
CHEAT_LABEL_PROMPT_VERSION = "mv-safe-v2-cheat-label-zh-cn"
# DeepSeek V4 Flash is the current fast model used by the optional translation
# path; thinking is configurable and enabled by default. Keep the public
# spelling (including hyphens) in
# cache keys and reports: it is the identifier accepted by the OpenAI-compatible
# DeepSeek endpoint, while ``v4flash`` is accepted below as a convenience alias.
DEFAULT_TRANSLATION_MODEL = "deepseek-v4-flash"
DEFAULT_TRANSLATION_BATCH_SIZE = 20
DEFAULT_TRANSLATION_CONCURRENCY = 4
DEFAULT_TRANSLATION_THINKING_ENABLED = True
DEFAULT_TRANSLATION_REASONING_EFFORT = "high"
TRANSLATION_REASONING_EFFORTS = ("low", "high", "max")
MAX_TRANSLATION_BATCH_SIZE = 100
MAX_TRANSLATION_CONCURRENCY = 8
_TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}


def _retry_delay(attempt: int, retry_after: float | None = None) -> float:
    """Return a short exponential backoff with bounded jitter."""

    base = retry_after if retry_after is not None else min(2.0**attempt, 8.0)
    # A little jitter prevents several concurrent batches from retrying in a
    # thundering herd after the same 429/5xx response.
    return max(0.0, min(base, 30.0)) + random.uniform(0.0, min(0.5, max(0.05, base * 0.2)))


def _wait_for_retry(cancel_event: Any, delay: float) -> None:
    """Sleep while remaining responsive to the pipeline cancellation event."""

    if cancel_event is not None and hasattr(cancel_event, "wait"):
        if cancel_event.wait(delay):
            raise CancelledError("translation cancelled")
    else:
        time.sleep(delay)


def _setting_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read an optional integer tuning knob without trusting environment input."""

    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def normalize_reasoning_effort(value: str | None) -> str:
    """Validate the V4 Flash thinking effort accepted by the API."""

    if value is None:
        return DEFAULT_TRANSLATION_REASONING_EFFORT
    if not isinstance(value, str):
        raise ConfigurationError("reasoning_effort must be low, high, or max")
    normalized = value.strip().casefold()
    if normalized not in TRANSLATION_REASONING_EFFORTS:
        choices = ", ".join(TRANSLATION_REASONING_EFFORTS)
        raise ConfigurationError(f"reasoning_effort must be one of: {choices}")
    return normalized
_CONTROL_RE = re.compile(r"\\[A-Za-z]+(?:\[[^\]]*\])?|%\d+|\{\d+\}|\{\{[^{}]+\}\}|<[^>]+>|\\[nrt\\\"']")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_HAN_RUN_RE = re.compile(r"[\u3400-\u9fff]+")
_HIRAGANA_RE = re.compile(r"[\u3040-\u309f]")
_KATAKANA_RE = re.compile(r"[\u30a0-\u30ff\u31f0-\u31ff]")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z]+")
# Common RPG/plugin abbreviations are intentionally allowed to remain (the
# user-facing contract is to translate definite English words, not familiar
# stat codes).  Other English words such as ``Gallery`` or ``unlocked`` still
# fail validation and must be translated.
_CHEAT_CODE_TOKENS = frozenset(
    {"atk", "bgm", "bgs", "def", "exp", "hp", "id", "lv", "mp", "se", "sfx", "sp", "x", "y"}
)
# Unicode cannot distinguish all Japanese Kanji from Chinese Han.  These are
# common Japanese shinjitai characters whose simplified-Chinese forms differ;
# an unchanged label containing one is not accepted as a completed translation.
_JAPANESE_ONLY_HINTS = frozenset("辺駅験経発時離処気戦円楽応県単覧続広絵図売働変帰後")
CHEAT_LABEL_KINDS = frozenset({"system-variable", "system-switch", "cheat-field"})
# The runtime cheat panel exposes the first N non-empty labels, not the whole
# 2,000-entry System.json arrays.  Keeping this scope bounded saves API calls
# and makes the build contract match the actual menu.
CHEAT_VISIBLE_VARIABLE_LIMIT = 256
CHEAT_VISIBLE_SWITCH_LIMIT = 128
_TEXT_KEYS = {
    "name",
    "description",
    "profile",
    "nickname",
    "message1",
    "message2",
    "message3",
    "message4",
    "help",
    "text",
    "displayname",
    "display_name",
}


def json_pointer(*parts: str | int) -> str:
    encoded = []
    for part in parts:
        text = str(part).replace("~", "~0").replace("/", "~1")
        encoded.append(text)
    return "/" + "/".join(encoded)


def pointer_parts(pointer: str) -> list[str]:
    if pointer in {"", "/"}:
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"not a JSON pointer: {pointer}")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def get_pointer(data: Any, pointer: str) -> Any:
    current = data
    for part in pointer_parts(pointer):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def set_pointer(data: Any, pointer: str, value: Any) -> None:
    parts = pointer_parts(pointer)
    if not parts:
        raise ValueError("root replacement is not supported")
    current = data
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    last = parts[-1]
    if isinstance(current, list):
        current[int(last)] = value
    else:
        current[last] = value


def placeholder_tokens(text: str) -> list[str]:
    return _CONTROL_RE.findall(text)


def protect_text(text: str) -> tuple[str, list[str]]:
    tokens: list[str] = []

    def replace(match: re.Match[str]) -> str:
        tokens.append(match.group(0))
        return f"__G2A_TOKEN_{len(tokens) - 1:03d}__"

    return _CONTROL_RE.sub(replace, text), tokens


def validate_placeholders(original: str, translated: str) -> tuple[bool, str]:
    expected = placeholder_tokens(original)
    actual = placeholder_tokens(translated)
    if expected != actual:
        return False, f"placeholder mismatch: expected {expected!r}, got {actual!r}"
    # A response containing a transport marker rather than the original token is
    # not accepted even when the marker count is accidentally correct.
    if "__G2A_TOKEN_" in translated:
        return False, "translation still contains an internal protected-token marker"
    return True, "ok"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TranslationError(f"unable to read translation JSON: {path}") from exc


def _entry_id(relative_file: str, field: str, locations: list[str]) -> str:
    seed = "|".join([relative_file, field, *locations])
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _make_entry(relative_file: str, kind: str, field: str, segments: list[str], locations: list[str]) -> TranslationEntry | None:
    if not segments or len(segments) != len(locations) or not any(segment.strip() for segment in segments):
        return None
    normalized = [str(segment) for segment in segments]
    return TranslationEntry(
        entry_id=_entry_id(relative_file, field, locations),
        relative_file=relative_file,
        kind=kind,
        field=field,
        segments=normalized,
        locations=list(locations),
        source_sha256=_sha256("\n".join(normalized)),
        placeholder_tokens=[placeholder_tokens(segment) for segment in normalized],
    )


def _walk_event_lists(value: Any, pointer: str = "") -> Iterable[tuple[list[Any], str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            child_pointer = json_pointer(*pointer_parts(pointer), key)
            if key == "list" and isinstance(item, list) and all(isinstance(command, dict) for command in item):
                yield item, child_pointer
            else:
                yield from _walk_event_lists(item, child_pointer)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_event_lists(item, json_pointer(*pointer_parts(pointer), index))


def _extract_event_list(relative_file: str, event_list: list[Any], list_pointer: str) -> list[TranslationEntry]:
    result: list[TranslationEntry] = []
    index = 0
    while index < len(event_list):
        command = event_list[index]
        if not isinstance(command, dict):
            index += 1
            continue
        code = command.get("code")
        params = command.get("parameters") if isinstance(command.get("parameters"), list) else []
        if code in {101, 105}:
            continuation_code = 401 if code == 101 else 405
            continuation = index + 1
            segments: list[str] = []
            locations: list[str] = []
            while continuation < len(event_list):
                next_command = event_list[continuation]
                if not isinstance(next_command, dict) or next_command.get("code") != continuation_code:
                    break
                next_params = next_command.get("parameters") if isinstance(next_command.get("parameters"), list) else []
                if not next_params or not isinstance(next_params[0], str):
                    break
                segments.append(next_params[0])
                locations.append(json_pointer(*pointer_parts(list_pointer), continuation, "parameters", 0))
                continuation += 1

            if code == 101:
                # Some message plugins append speakerName as parameter 4. It
                # is metadata, not the message body; the real body is still
                # the following 401 command block.
                if len(params) >= 5 and isinstance(params[4], str):
                    speaker = _make_entry(
                        relative_file,
                        "speaker-name",
                        "speakerName",
                        [params[4]],
                        [json_pointer(*pointer_parts(list_pointer), index, "parameters", 4)],
                    )
                    if speaker:
                        result.append(speaker)
                entry = _make_entry(relative_file, "message", "message", segments, locations)
            else:
                entry = _make_entry(relative_file, "scroll-text", "scrollText", segments, locations)
            if entry:
                result.append(entry)
            if continuation > index + 1:
                index = continuation
                continue
        elif code == 102 and params and isinstance(params[0], list):
            choices = [choice for choice in params[0] if isinstance(choice, str)]
            locations = [
                json_pointer(*pointer_parts(list_pointer), index, "parameters", 0, choice_index)
                for choice_index, choice in enumerate(params[0])
                if isinstance(choice, str)
            ]
            entry = _make_entry(relative_file, "choice", "choices", choices, locations)
            if entry:
                result.append(entry)
        index += 1
    return result


def _extract_system(relative_file: str, data: dict[str, Any]) -> list[TranslationEntry]:
    result: list[TranslationEntry] = []
    if isinstance(data.get("gameTitle"), str):
        location = json_pointer("gameTitle")
        entry = _make_entry(relative_file, "system-title", "gameTitle", [data["gameTitle"]], [location])
        if entry:
            result.append(entry)
    terms = data.get("terms")
    for pointer, value in _walk_allowed_strings(terms, json_pointer("terms")):
        entry = _make_entry(relative_file, "system-term", pointer_parts(pointer)[-1], [value], [pointer])
        if entry:
            result.append(entry)

    # RPG Maker stores the editor-facing variable and switch labels in
    # System.json.  They are displayed by the dynamic cheat panel, so they
    # must travel through the same opt-in translation path as dialogue and
    # choices.  Only the label arrays are allowed here; numeric game state and
    # executable/plugin fields are never sent to the provider.
    for key, kind in (("variables", "system-variable"), ("switches", "system-switch")):
        values = data.get(key)
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            if not isinstance(value, str) or not value.strip():
                continue
            pointer = json_pointer(key, index)
            entry = _make_entry(relative_file, kind, key, [value], [pointer])
            if entry:
                result.append(entry)
    return result


def _walk_allowed_strings(value: Any, pointer: str) -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield pointer, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_allowed_strings(item, json_pointer(*pointer_parts(pointer), key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_allowed_strings(item, json_pointer(*pointer_parts(pointer), index))


def _extract_database_fields(relative_file: str, data: Any) -> list[TranslationEntry]:
    result: list[TranslationEntry] = []

    def visit(value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child = json_pointer(*pointer_parts(pointer), key)
                key_folded = str(key).casefold()
                if key_folded in _TEXT_KEYS and isinstance(item, str):
                    entry = _make_entry(relative_file, "database-field", str(key), [item], [child])
                    if entry:
                        result.append(entry)
                elif key_folded not in {"note", "notes", "script", "filename", "file", "path", "url", "image", "charactername", "face"}:
                    visit(item, child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, json_pointer(*pointer_parts(pointer), index))

    visit(data, "")
    return result


def extract_safe_entries(www: str | Path) -> list[TranslationEntry]:
    root = Path(www).resolve(strict=True)
    result: list[TranslationEntry] = []
    for path in sorted(root.rglob("*.json"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        try:
            data = _load_json(path)
        except TranslationError:
            continue
        if path.name.casefold() == "system.json" and isinstance(data, dict):
            result.extend(_extract_system(relative, data))
        elif path.name.casefold().startswith("map") and path.name.casefold().endswith(".json"):
            for event_list, pointer in _walk_event_lists(data):
                result.extend(_extract_event_list(relative, event_list, pointer))
            # MapInfos and a few custom projects contain display names outside event lists.
            if path.name.casefold() == "mapinfos.json":
                result.extend(_extract_database_fields(relative, data))
        elif path.name.casefold() == "commonevents.json":
            for event_list, pointer in _walk_event_lists(data):
                result.extend(_extract_event_list(relative, event_list, pointer))
        else:
            result.extend(_extract_database_fields(relative, data))
    return sorted(result, key=lambda entry: (entry.relative_file.casefold(), entry.locations, entry.entry_id))


def _script_flags(text: str, threshold: float = 0.30) -> dict[str, Any]:
    """Return the explainable script signals used for source filtering."""

    cjk = len(_CJK_RE.findall(text))
    kana = len(_HIRAGANA_RE.findall(text)) + len(_KATAKANA_RE.findall(text))
    latin_or_digits = len(re.findall(r"[A-Za-z0-9]", text))
    denominator = cjk + kana + latin_or_digits
    kana_ratio = kana / max(1, denominator)
    han_ratio = cjk / max(1, denominator)
    likely_japanese = kana >= 2 and kana_ratio >= 0.02
    likely_chinese = cjk > 0 and not likely_japanese and han_ratio >= threshold
    return {
        "han": cjk,
        "kana": kana,
        "latinOrDigits": latin_or_digits,
        "denominator": denominator,
        "hanRatio": han_ratio,
        "likelyJapanese": likely_japanese,
        "likelyChinese": likely_chinese,
    }


def _has_translatable_script(text: str) -> bool:
    """Ignore punctuation/number-only strings which are not translatable text."""

    return bool(re.search(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]", text))


def _segment_has_non_chinese_text(text: str, threshold: float = 0.30) -> bool:
    """Whether a segment contains text that is eligible for translation.

    A segment containing Han and Latin characters is retained as a mixed
    context segment.  Its Han runs are protected before it reaches the
    provider and restored byte-for-byte after the response.  This lets a
    coherent dialogue block provide context without rewriting existing
    Chinese text.
    """

    if not _has_translatable_script(text):
        return False
    return not bool(_script_flags(text, threshold=threshold)["likelyChinese"])


def filter_non_chinese_entries(
    entries: Iterable[TranslationEntry], threshold: float = 0.30
) -> list[TranslationEntry]:
    """Select blocks with at least one non-Chinese segment.

    Whole dialogue/message blocks remain intact so the model sees all lines
    together.  Purely Chinese blocks are never sent to DeepSeek.  Mixed blocks
    are allowed as context, but their Han runs are protected by the request
    and application paths below.
    """

    return [
        entry
        for entry in entries
        if any(_segment_has_non_chinese_text(segment, threshold=threshold) for segment in entry.segments)
    ]


def _cheat_label_latin_tokens(text: str) -> list[str]:
    """Return Latin words in a dynamic cheat label, excluding controls."""

    # Control codes and tags are executable/display syntax, not translatable
    # English.  Removing them before tokenising also keeps the validator from
    # treating a plugin command such as ``\\C[1]`` as a failed label.
    protected, _tokens = protect_text(text)
    protected = re.sub(r"__G2A_TOKEN_\d+__", "", protected)
    return _LATIN_TOKEN_RE.findall(protected)


def cheat_label_needs_translation(text: str) -> bool:
    """Whether a dynamic cheat label contains Japanese or natural-language Latin.

    Han characters are shared by Chinese and Japanese, so a Han-only label is
    intentionally left alone unless it also carries a Japanese kana signal or
    a non-code Latin word.  This avoids sending already-Chinese labels to the
    provider while still catching labels such as ``ステEXP淫乱`` and
    ``Gallery unlocked``.  ASCII identifiers/abbreviations (SE, EXP, HP,
    X/Y, numbers, etc.) are allowed and remain byte-for-byte intact.
    """

    if _HIRAGANA_RE.search(text) or _KATAKANA_RE.search(text):
        return True
    if any(char in _JAPANESE_ONLY_HINTS for char in text):
        return True
    return any(token.casefold() not in _CHEAT_CODE_TOKENS for token in _cheat_label_latin_tokens(text))


def filter_cheat_label_entries(entries: Iterable[TranslationEntry]) -> list[TranslationEntry]:
    """Select all non-empty dynamic labels for strict zh-CN normalization.

    This intentionally does not call :func:`filter_non_chinese_entries` (or
    even rely solely on :func:`cheat_label_needs_translation`): Japanese
    Kanji-only labels have no Unicode signal that distinguishes them from
    Chinese.  The strict prompt/response validator decides whether an already
    Chinese label can remain unchanged.
    """

    candidates = [entry for entry in entries if any(segment.strip() for segment in entry.segments)]
    selected_ids: set[str] = set()
    limits = {
        "system-variable": CHEAT_VISIBLE_VARIABLE_LIMIT,
        "system-switch": CHEAT_VISIBLE_SWITCH_LIMIT,
    }
    for kind, limit in limits.items():
        kind_entries = [entry for entry in candidates if entry.kind == kind]

        def numeric_location(entry: TranslationEntry) -> tuple[int, str]:
            try:
                return int(entry.locations[0].rsplit("/", 1)[-1]), entry.entry_id
            except (IndexError, ValueError):
                return 2**31 - 1, entry.entry_id

        selected_ids.update(entry.entry_id for entry in sorted(kind_entries, key=numeric_location)[:limit])
    # Keep extractor order for stable reports, but choose the same numeric
    # indices as the JavaScript discover() loop rather than lexicographic
    # JSON-pointer order (where /variables/10 precedes /variables/2).
    return [
        entry
        for entry in candidates
        if entry.kind not in limits or entry.entry_id in selected_ids
    ]


def _is_simplified_chinese_target(target_language: str) -> bool:
    normalized = str(target_language).strip().casefold().replace("_", "-")
    return normalized in {"zh", "zh-cn", "zh-hans", "简体中文", "simplified-chinese"}


def validate_simplified_chinese_label(original: str, translated: str) -> tuple[bool, str]:
    """Validate the strict output contract for a cheat-menu label.

    This is deliberately conservative: Japanese kana and natural-language
    Latin words are never accepted, while known game/plugin identifiers and
    one-letter coordinates remain valid.  A candidate that needed translation
    must contain at least one Han character after translation, preventing a
    provider response such as ``Gallery unlocked`` or ``One [zh]`` from being
    applied as if it were Chinese.
    """

    if _HIRAGANA_RE.search(translated) or _KATAKANA_RE.search(translated):
        return False, "cheat label still contains Japanese kana"
    latin_tokens = _cheat_label_latin_tokens(translated)
    unexpected = [token for token in latin_tokens if token.casefold() not in _CHEAT_CODE_TOKENS]
    if unexpected:
        return False, f"cheat label still contains untranslated Latin word(s): {unexpected!r}"
    if cheat_label_needs_translation(original) and not _CJK_RE.search(translated):
        return False, "cheat label translation is not Simplified Chinese"
    # A provider may echo a candidate verbatim while removing/altering a
    # marker.  Reject exact echoes for a label that was known to need work;
    # code-only labels never enter the strict candidate set.
    if cheat_label_needs_translation(original) and original.strip() == translated.strip():
        return False, "cheat label was returned unchanged"
    return True, "ok"


def translation_language_profile(entries: Iterable[TranslationEntry], threshold: float = 0.30) -> dict[str, Any]:
    """Return a small, explainable language signal for the inspection UI.

    Han characters are shared by Chinese and Japanese, so this deliberately
    reports a heuristic rather than claiming a perfect language classifier.
    Kana is treated as a Japanese signal; a Han-heavy project with little or
    no kana is labelled likely Chinese.  The result contains no source text.
    """

    values = list(entries)
    text = "\n".join(entry.source_text for entry in values)
    flags = _script_flags(text, threshold=threshold)
    cjk = flags["han"]
    kana = flags["kana"]
    latin_or_digits = flags["latinOrDigits"]
    denominator = flags["denominator"]
    # Han characters occur in both Chinese and Japanese. A meaningful *share*
    # of hiragana/katakana is therefore a Japanese signal. A small amount of
    # kana in a predominantly Chinese project (for example plugin labels or
    # retained names) must not force an unnecessary third-party translation.
    han_ratio = flags["hanRatio"]
    likely_japanese = flags["likelyJapanese"]
    likely_chinese = flags["likelyChinese"]
    return {
        "entries": len(values),
        "characters": len(text),
        "hanCharacters": cjk,
        "kanaCharacters": kana,
        "latinOrDigitCharacters": latin_or_digits,
        "hanRatio": round(han_ratio, 4),
        "likelyChinese": likely_chinese,
        "likelyJapanese": likely_japanese,
        "predominantlyChinese": likely_chinese,
        "translationRecommended": bool(denominator > 0 and not likely_chinese),
        "defaultTranslate": False,
    }


def recommend_skip_translation(entries: Iterable[TranslationEntry], threshold: float = 0.30) -> bool:
    profile = translation_language_profile(entries, threshold=threshold)
    return bool(profile["predominantlyChinese"])


def translation_memory_key(
    source: str,
    target_language: str,
    model: str,
    prompt_version: str = PROMPT_VERSION,
    glossary_hash: str = "",
) -> str:
    return _sha256("\0".join([source, target_language, model, prompt_version, glossary_hash]))


class TranslationMemory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, Any] = {"schemaVersion": 1, "entries": {}}
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if loaded.get("schemaVersion") == 1 and isinstance(loaded.get("entries"), dict):
                    self.data = loaded
            except (OSError, ValueError):
                # A corrupt cache is ignored; the original text remains the fallback.
                pass

    def get(self, key: str) -> list[str] | None:
        item = self.data["entries"].get(key)
        if isinstance(item, dict) and isinstance(item.get("segments"), list) and all(isinstance(v, str) for v in item["segments"]):
            return list(item["segments"])
        return None

    def put(self, key: str, entry_id: str, source_sha256: str, segments: list[str]) -> None:
        self.data["entries"][key] = {
            "id": entry_id,
            "sourceSha256": source_sha256,
            "segments": list(segments),
            "updatedAt": time.time(),
        }

    def save(self) -> None:
        atomic_write_json(self.path, self.data)


class TranslationTransport(Protocol):
    def list_models(self, api_key: str) -> list[str]: ...

    def chat(self, payload: dict[str, Any], api_key: str) -> dict[str, Any]: ...


class DeepSeekHTTPError(TranslationError):
    def __init__(self, status: int, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        # Retry-After is provider-controlled input.  Keep it bounded and
        # numeric so a malformed response cannot make a local build sleep for
        # an unbounded amount of time.
        try:
            candidate = float(retry_after) if retry_after is not None else None
        except (TypeError, ValueError):
            candidate = None
        self.retry_after = (
            max(0.0, min(candidate, 30.0))
            if candidate is not None and math.isfinite(candidate)
            else None
        )


class DeepSeekTransport:
    """Small stdlib transport; no key is persisted or printed."""

    def __init__(self, base_url: str = "https://api.deepseek.com", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, endpoint: str, api_key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url + endpoint
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except OSError:
                detail = "HTTP error"
            retry_after: float | None = None
            try:
                header = exc.headers.get("Retry-After") if exc.headers is not None else None
                if header is not None:
                    retry_after = float(header)
            except (TypeError, ValueError):
                # HTTP-date values and malformed headers are intentionally
                # ignored; exponential backoff remains the safe fallback.
                retry_after = None
            raise DeepSeekHTTPError(
                exc.code,
                f"DeepSeek HTTP {exc.code}: {redact_text(detail)}",
                retry_after=retry_after,
            ) from exc
        except urllib.error.URLError as exc:
            raise TranslationError(f"DeepSeek connection failed: {redact_text(exc.reason)}") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise TranslationError("DeepSeek returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise TranslationError("DeepSeek returned a non-object JSON response")
        return data

    def list_models(self, api_key: str) -> list[str]:
        last_error: DeepSeekHTTPError | None = None
        for attempt in range(3):
            try:
                data = self._request("GET", "/models", api_key)
                break
            except DeepSeekHTTPError as exc:
                last_error = exc
                if exc.status not in _TRANSIENT_HTTP_STATUSES or attempt == 2:
                    raise
                _wait_for_retry(None, _retry_delay(attempt, exc.retry_after))
        else:
            raise TranslationError(str(last_error or "DeepSeek /models failed"))
        models = data.get("data")
        if not isinstance(models, list):
            raise TranslationError("DeepSeek /models response has no data array")
        result = []
        for item in models:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                result.append(item["id"])
        return sorted(set(result))

    def chat(self, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        return self._request("POST", "/chat/completions", api_key, payload)


class FakeTransport:
    """Deterministic offline transport used by tests and local demonstrations."""

    def __init__(self, models: list[str] | None = None, responder: Callable[[dict[str, Any]], dict[str, Any]] | None = None):
        self.models = models or ["deepseek-v4-flash"]
        self.responder = responder or self._default_response
        self.calls: list[dict[str, Any]] = []

    def list_models(self, api_key: str) -> list[str]:
        return list(self.models)

    def chat(self, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        self.calls.append(payload)
        return self.responder(payload)

    @staticmethod
    def _default_response(payload: dict[str, Any]) -> dict[str, Any]:
        request_text = payload["messages"][-1]["content"]
        items = json.loads(request_text.split("INPUT=", 1)[1])
        translations = []
        for item in items:
            translations.append({"id": item["id"], "segments": item["segments"]})
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"translations": translations}, ensure_ascii=False)}}]}


def normalize_model(model: str | None) -> str | None:
    """Normalize friendly V4 Flash spellings to the official API identifier."""

    if model is None:
        return None
    text = model.strip()
    aliases = {
        "v4flash": DEFAULT_TRANSLATION_MODEL,
        "v4-flash": DEFAULT_TRANSLATION_MODEL,
        "deepseek-v4flash": DEFAULT_TRANSLATION_MODEL,
        "deepseek_v4_flash": DEFAULT_TRANSLATION_MODEL,
    }
    return aliases.get(text.casefold(), text)


def choose_model(models: list[str], requested: str | None = None) -> str:
    requested = normalize_model(requested)
    if requested:
        return requested
    if not models:
        raise ConfigurationError("no DeepSeek model is available; specify a model manually")
    preferred = [name for name in models if normalize_model(name) == DEFAULT_TRANSLATION_MODEL]
    if preferred:
        return normalize_model(preferred[0]) or DEFAULT_TRANSLATION_MODEL
    non_reasoning = [name for name in models if "reason" not in name.casefold() and "think" not in name.casefold()]
    return sorted(non_reasoning or models)[0]


def _content_from_response(data: dict[str, Any]) -> tuple[str, str]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise TranslationError("DeepSeek response has no choices")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise TranslationError("DeepSeek response choice is invalid")
    reason = str(choice.get("finish_reason") or "")
    if reason in {"length", "content_filter"}:
        raise TranslationError(f"DeepSeek response was not complete: {reason}")
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise TranslationError("DeepSeek response content is empty")
    return content, reason


def _protect_provider_segment(text: str, preserve_han: bool = True) -> str:
    """Protect controls and existing Han runs while retaining context.

    The marker format is intentionally opaque and independent from MV control
    markers.  It is only used in the provider payload; the original runs are
    recovered from the corresponding source segment when the response is
    applied.
    """

    protected, _tokens = protect_text(text)

    if not preserve_han:
        # Japanese Kanji are indistinguishable from Chinese Han by Unicode
        # alone.  The strict cheat-label pass therefore lets the provider see
        # all Han when a label is being normalized to zh-CN; only executable MV
        # control markers remain protected.
        return protected

    counter = [0]

    def replace_han(match: re.Match[str]) -> str:
        # The index is assigned by the run order in this segment and keeps the
        # serialized marker deterministic.
        index = counter[0]
        counter[0] += 1
        return f"__G2A_KEEP_HAN_{index:03d}__"

    return _HAN_RUN_RE.sub(replace_han, protected)


def _restore_protected_segment(
    original: str,
    translated: str,
    preserve_han: bool = True,
) -> tuple[str | None, str | None]:
    """Restore Han runs and MV controls, rejecting a changed marker safely."""

    original_han = _HAN_RUN_RE.findall(original) if preserve_han else []
    restored = translated
    for index, run in enumerate(original_han):
        marker = f"__G2A_KEEP_HAN_{index:03d}__"
        if marker not in restored:
            return None, "protected Chinese text marker missing or changed"
        restored = restored.replace(marker, run, 1)
    protected_original, original_tokens = protect_text(original)
    # A response that invents an extra protected Han marker is not safe to
    # apply, even if all expected markers are present.
    if "__G2A_KEEP_HAN_" in restored:
        return None, "translation contains an unexpected protected Chinese marker"
    for token_index, original_token in enumerate(original_tokens):
        marker = f"__G2A_TOKEN_{token_index:03d}__"
        if marker not in restored:
            return None, "protected MV token marker missing or changed"
        restored = restored.replace(marker, original_token, 1)
    # ``protected_original`` is intentionally computed above to keep the
    # control-token contract explicit; validate_placeholders performs the
    # canonical comparison after restoration.
    _ = protected_original
    return restored, None


def _han_runs_preserved(original: str, translated: str) -> bool:
    """Guard against a provider rewriting Chinese in a mixed segment."""

    original_runs = _HAN_RUN_RE.findall(original)
    # A non-Chinese source segment is expected to gain Han text when the
    # target language is Chinese.  Only compare runs when the source already
    # contained Han text that must be preserved.
    return not original_runs or original_runs == _HAN_RUN_RE.findall(translated)


def _parse_translation_json(content: str, expected_ids: set[str]) -> dict[str, list[str]]:
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise TranslationError("DeepSeek JSON Output could not be parsed") from exc
    items = data.get("translations") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise TranslationError("translation JSON must contain a translations array")
    result: dict[str, list[str]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("segments"), list):
            raise TranslationError("translation item must contain id and segments")
        item_id = item["id"]
        if item_id in result or item_id not in expected_ids:
            raise TranslationError("translation IDs are duplicated or unexpected")
        if not all(isinstance(segment, str) for segment in item["segments"]):
            raise TranslationError("translation segments must be strings")
        result[item_id] = list(item["segments"])
    if set(result) != expected_ids:
        raise TranslationError("translation IDs do not match the requested block")
    return result


def _request_batch(
    transport: TranslationTransport,
    api_key: str,
    model: str,
    target_language: str,
    entries: list[TranslationEntry],
    thinking_enabled: bool,
    reasoning_effort: str,
    cancel_event=None,
    strict_simplified_chinese: bool = False,
) -> dict[str, list[str]]:
    request_items = []
    for entry in entries:
        protected_segments = [
            _protect_provider_segment(segment, preserve_han=not strict_simplified_chinese)
            for segment in entry.segments
        ]
        request_items.append({"id": entry.entry_id, "segments": protected_segments})
    if strict_simplified_chinese:
        prompt = (
            "Translate every supplied RPG Maker MV cheat-menu label into Simplified Chinese (zh-CN). "
            "This is a mandatory label-normalization pass, not a word lookup: translate Japanese Kanji, "
            "hiragana, katakana, and natural-language English into natural Simplified Chinese. "
            "Do not leave Japanese or English words in the result. Preserve only game/plugin identifiers "
            "and coordinate/code tokens such as SE, EXP, HP, MP, ATK, DEF, X, Y, IDs, numbers, and "
            "MV control markers. Return JSON exactly as {\"translations\":[{\"id\":string,\"segments\":string[]}]}. "
            "Read all segments of one item together, keep the segments array length/order and line boundaries, "
            "and do not translate markers, code, paths, or tags.\n"
        )
    else:
        prompt = (
            "Translate only the supplied RPG Maker MV display text into the requested target language. "
            "Return JSON exactly as {\"translations\":[{\"id\":string,\"segments\":string[]}]}. "
            "Treat every INPUT item as one coherent dialogue or text block: read all of its segments together "
            "to preserve context, pronouns, tone, and terminology; never translate word-by-word or as unrelated fragments. "
            "Existing Chinese (Han) runs are marked __G2A_KEEP_HAN_NNN__ and MUST be copied byte-for-byte; "
            "translate only the surrounding non-Chinese text. Keep every protected marker unchanged, "
            "keep each segments array length and order unchanged, "
            "and preserve the line boundary of every segment. "
            "Do not translate markers, code, paths, or tags.\n"
        )
    prompt += f"TARGET_LANGUAGE={target_language}\nINPUT=" + json.dumps(request_items, ensure_ascii=False)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a constrained game-text translation engine."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        # V4 models default to thinking mode. The user can disable it for speed
        # or select the requested reasoning effort when it is enabled.
        "thinking": {"type": "enabled" if thinking_enabled else "disabled"},
        "temperature": 0.1,
        "stream": False,
    }
    if thinking_enabled:
        payload["reasoning_effort"] = reasoning_effort
    # Keep output bounded to the amount of text requested while leaving room
    # for JSON punctuation, target-language expansion, and V4 reasoning tokens.
    estimated_chars = sum(len(segment) for entry in entries for segment in entry.segments)
    effort_floor = {"low": 1024, "high": 2048, "max": 4096}[reasoning_effort] if thinking_enabled else 512
    payload["max_tokens"] = min(131072, max(effort_floor, estimated_chars * 2 + 512))
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("translation cancelled")
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            data = transport.chat(payload, api_key)
            content, _ = _content_from_response(data)
            return _parse_translation_json(content, {entry.entry_id for entry in entries})
        except DeepSeekHTTPError as exc:
            last_error = exc
            if exc.status not in _TRANSIENT_HTTP_STATUSES or attempt == 2:
                raise
            _wait_for_retry(cancel_event, _retry_delay(attempt, exc.retry_after))
        except TranslationError as exc:
            last_error = exc
            raise
    raise TranslationError(str(last_error or "translation request failed"))


def apply_translations(www: str | Path, entries: list[TranslationEntry], translations: dict[str, list[str]]) -> list[TranslationFailure]:
    root = Path(www).resolve(strict=True)
    grouped: dict[str, list[tuple[TranslationEntry, list[str]]]] = {}
    failures: list[TranslationFailure] = []
    for entry in entries:
        candidate = translations.get(entry.entry_id)
        if candidate is None:
            continue
        if len(candidate) != len(entry.segments):
            failures.append(TranslationFailure(entry.entry_id, "segment count mismatch", entry.source_text))
            continue
        valid = True
        reason = ""
        for original, translated in zip(entry.segments, candidate):
            valid, reason = validate_placeholders(original, translated)
            if not valid:
                break
        if not valid:
            failures.append(TranslationFailure(entry.entry_id, reason, entry.source_text))
            continue
        grouped.setdefault(entry.relative_file, []).append((entry, candidate))

    for relative, items in grouped.items():
        path = root / Path(relative)
        data = _load_json(path)
        for entry, candidate in items:
            current = [get_pointer(data, location) for location in entry.locations]
            if _sha256("\n".join(str(value) for value in current)) != entry.source_sha256:
                failures.append(TranslationFailure(entry.entry_id, "source changed since extraction", entry.source_text))
                continue
            for location, translated in zip(entry.locations, candidate):
                set_pointer(data, location, translated)
        if not all(failure.entry_id not in {entry.entry_id for entry, _ in items} for failure in failures):
            # At least one entry in this file failed; the successful entries are
            # still safe and are intentionally applied, while failed entries stay original.
            pass
        # Re-read failed locations from the original snapshot is unnecessary: we
        # only set locations after validation and source checks above.
        atomic_write_json(path, data)
    return failures


class TranslationService:
    def __init__(self, progress=None, cancel_event=None):
        self.progress = progress or (lambda *_args, **_kwargs: None)
        self.cancel_event = cancel_event

    def translate(
        self,
        www: str | Path,
        target_language: str = "zh-CN",
        model: str | None = None,
        api_key: str | None = None,
        transport: TranslationTransport | None = None,
        memory_path: str | Path | None = None,
        confirmed_third_party: bool = False,
        force: bool = False,
        batch_size: int = DEFAULT_TRANSLATION_BATCH_SIZE,
        max_concurrency: int = DEFAULT_TRANSLATION_CONCURRENCY,
        thinking_enabled: bool = DEFAULT_TRANSLATION_THINKING_ENABLED,
        reasoning_effort: str = DEFAULT_TRANSLATION_REASONING_EFFORT,
        entry_kinds: set[str] | None = None,
    ) -> TranslationReport:
        batch_size = _setting_int(
            "GAME2APK_TRANSLATION_BATCH_SIZE",
            batch_size,
            1,
            MAX_TRANSLATION_BATCH_SIZE,
        )
        max_concurrency = _setting_int(
            "GAME2APK_TRANSLATION_CONCURRENCY",
            max_concurrency,
            1,
            MAX_TRANSLATION_CONCURRENCY,
        )
        if not isinstance(thinking_enabled, bool):
            raise ConfigurationError("thinking_enabled must be true or false")
        reasoning_effort = normalize_reasoning_effort(reasoning_effort)
        model = normalize_model(model)
        source_entries = extract_safe_entries(www)
        allowed_kinds: set[str] | None = None
        if entry_kinds is not None:
            allowed_kinds = {str(kind) for kind in entry_kinds}
            source_entries = [entry for entry in source_entries if entry.kind in allowed_kinds]
        strict_simplified_chinese = bool(
            allowed_kinds
            and allowed_kinds <= CHEAT_LABEL_KINDS
            and _is_simplified_chinese_target(target_language)
        )
        # Translation is opt-in, but even an explicit opt-in must never send
        # already-Chinese-only blocks for rewriting.  Mixed blocks remain
        # coherent context and have Han runs protected in _request_batch.
        # Cheat labels use a stricter selector: a Japanese label containing
        # only Kanji is indistinguishable from Chinese at the Unicode level,
        # so the caller's explicit cheat-label scope must bypass the general
        # Han-ratio heuristic entirely.  Every non-empty variable/switch label
        # is sent through the strict zh-CN contract; already-Chinese labels are
        # accepted unchanged by the validator, while Japanese/English labels
        # cannot pass unless the provider returns Chinese.
        entries = (
            filter_cheat_label_entries(source_entries)
            if strict_simplified_chinese
            else filter_non_chinese_entries(source_entries)
        )
        candidate_ids = {entry.entry_id for entry in entries}
        skipped_chinese = sum(
            1
            for entry in source_entries
            if entry.entry_id not in candidate_ids
            and any(_CJK_RE.search(segment) for segment in entry.segments)
        )
        skipped_non_text = max(0, len(source_entries) - len(entries) - skipped_chinese)
        recommended = False if strict_simplified_chinese else recommend_skip_translation(source_entries)
        report = TranslationReport(
            schema_version=1,
            source_language="zh-CN" if recommended else "unknown",
            target_language=target_language,
            model=model or DEFAULT_TRANSLATION_MODEL,
            entries_total=len(entries),
            entries_applied=0,
            entries_cached=0,
            thinking_enabled=thinking_enabled,
            reasoning_effort=reasoning_effort,
            skipped_recommended=recommended and not force,
            live_api_used=False,
            source_entries_total=len(source_entries),
            entries_skipped_chinese=skipped_chinese,
            entries_skipped_non_text=skipped_non_text,
        )
        if not entries:
            self.progress(
                "translate",
                1.0,
                f"no non-Chinese text selected; preserved {skipped_chinese} Chinese blocks and {skipped_non_text} non-text blocks",
            )
            return report
        if recommended and not force and not strict_simplified_chinese:
            self.progress(
                "translate",
                1.0,
                f"source is predominantly Chinese; translation skipped ({skipped_chinese} Chinese blocks preserved)",
            )
            return report
        if not confirmed_third_party:
            raise BlockedError("translation requires explicit confirmation before sending selected text to DeepSeek")
        transport = transport or DeepSeekTransport()
        if api_key is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY")
        if api_key is None:
            raise ConfigurationError("DeepSeek API key must be provided in memory or DEEPSEEK_API_KEY")
        # V4 Flash is an official stable model identifier.  Avoid a separate
        # /models round-trip for every build; callers can still explicitly pass
        # another model when they need one.
        model = model or DEFAULT_TRANSLATION_MODEL
        report.model = model
        memory = TranslationMemory(memory_path or (Path(www).parent / ".state" / "translation-memory.json"))
        memory_prompt_version = CHEAT_LABEL_PROMPT_VERSION if strict_simplified_chinese else PROMPT_VERSION
        translations: dict[str, list[str]] = {}
        # Group identical source blocks before making requests.  RPG Maker
        # projects often repeat common labels; translating one representative
        # and reusing it preserves order while removing duplicate API work.
        pending_groups: dict[str, list[TranslationEntry]] = {}
        for entry in entries:
            key = translation_memory_key(
                entry.source_text,
                target_language,
                model,
                prompt_version=memory_prompt_version,
            )
            cached = memory.get(key)
            if cached is not None and len(cached) == len(entry.segments) and all(
                validate_placeholders(original, translated)[0]
                and (
                    validate_simplified_chinese_label(original, translated)[0]
                    if strict_simplified_chinese
                    else _han_runs_preserved(original, translated)
                )
                for original, translated in zip(entry.segments, cached)
            ):
                translations[entry.entry_id] = cached
                report.entries_cached += 1
            else:
                pending_groups.setdefault(key, []).append(entry)

        pending = [(key, group) for key, group in pending_groups.items()]
        duplicate_count = sum(max(0, len(group) - 1) for _key, group in pending)
        if pending:
            self.progress(
                "translate",
                report.entries_cached / max(1, len(entries)),
                f"translation queued: {len(pending)} unique blocks ({duplicate_count} duplicates reused)",
            )

        batches = [pending[offset : offset + batch_size] for offset in range(0, len(pending), batch_size)]
        executor: ThreadPoolExecutor | None = None
        futures: list[Any] = []
        cancelled = False
        processed_entries = 0
        try:
            if batches:
                executor = ThreadPoolExecutor(
                    max_workers=min(max_concurrency, len(batches)),
                    thread_name_prefix="game2apk-translate",
                )
                futures = [
                    executor.submit(
                        _request_batch,
                        transport,
                        api_key,
                        model,
                        target_language,
                        [group[0] for _key, group in batch],
                        thinking_enabled,
                        reasoning_effort,
                        self.cancel_event,
                        strict_simplified_chinese,
                    )
                    for batch in batches
                ]

                def record_batch_failure(batch, reason: str) -> None:
                    safe_reason = redact_text(reason, (api_key,))
                    for _key, group in batch:
                        for duplicate in group:
                            report.failures.append(
                                TranslationFailure(duplicate.entry_id, safe_reason, duplicate.source_text)
                            )

                # Consume futures in submission order.  Requests run in
                # parallel, but applying results in source order keeps output,
                # reports, cache writes, and progress deterministic.
                for batch, future in zip(batches, futures):
                    batch_translations: dict[str, list[str]] | None = None
                    while True:
                        if self.cancel_event is not None and self.cancel_event.is_set():
                            raise CancelledError("translation cancelled")
                        try:
                            batch_translations = future.result(timeout=0.2)
                            break
                        except FutureTimeout:
                            continue
                        except CancelledError:
                            raise
                        except Exception as exc:
                            # A transport failure belongs to this batch only;
                            # continue consuming later batches in source order.
                            record_batch_failure(batch, str(exc))
                            processed_entries += sum(len(group) for _key, group in batch)
                            memory.save()
                            completed = report.entries_cached + processed_entries
                            self.progress(
                                "translate",
                                min(1.0, completed / max(1, len(entries))),
                                f"translated {min(len(entries), completed)}/{len(entries)} blocks",
                            )
                            break
                    if batch_translations is None:
                        continue
                    try:
                        for key, group in batch:
                            entry = group[0]
                            candidate = batch_translations.get(entry.entry_id)
                            if candidate is None or len(candidate) != len(entry.segments):
                                record_batch_failure([(key, group)], "missing or mismatched response entry")
                                continue
                            restored: list[str] = []
                            for original, translated in zip(entry.segments, candidate):
                                restored_segment, protected_error = _restore_protected_segment(
                                    original,
                                    translated,
                                    preserve_han=not strict_simplified_chinese,
                                )
                                if protected_error or restored_segment is None:
                                    invalid_reason = protected_error or "protected text restoration failed"
                                    break
                                if not strict_simplified_chinese and not _han_runs_preserved(original, restored_segment):
                                    invalid_reason = "Chinese text changed in provider response"
                                    break
                                if strict_simplified_chinese:
                                    valid_label, label_reason = validate_simplified_chinese_label(
                                        original,
                                        restored_segment,
                                    )
                                    if not valid_label:
                                        invalid_reason = label_reason
                                        break
                                restored.append(restored_segment)
                            else:
                                invalid_reason = next(
                                    (
                                        reason
                                        for original, translated in zip(entry.segments, restored)
                                        if not (ok := validate_placeholders(original, translated))[0]
                                        for reason in [ok[1]]
                                    ),
                                    None,
                                )
                            if invalid_reason:
                                record_batch_failure([(key, group)], invalid_reason)
                                continue
                            for duplicate in group:
                                translations[duplicate.entry_id] = list(restored)
                            memory.put(key, entry.entry_id, entry.source_sha256, restored)
                    except (AttributeError, KeyError, TypeError, ValueError) as exc:
                        # A malformed provider payload must not abort unrelated
                        # batches; report it against this batch without exposing
                        # the API key.
                        record_batch_failure(batch, str(exc))
                    except TranslationError as exc:
                        # Transport errors are isolated to this batch.  Other
                        # concurrently running requests remain useful.
                        record_batch_failure(batch, str(exc))
                    processed_entries += sum(len(group) for _key, group in batch)
                    memory.save()
                    completed = report.entries_cached + processed_entries
                    self.progress(
                        "translate",
                        min(1.0, completed / max(1, len(entries))),
                        f"translated {min(len(entries), completed)}/{len(entries)} blocks",
                    )
        except CancelledError:
            cancelled = True
            for future in futures:
                future.cancel()
            raise
        finally:
            if executor is not None:
                executor.shutdown(wait=not cancelled, cancel_futures=cancelled)

        if self.cancel_event is not None and self.cancel_event.is_set():
            raise CancelledError("translation cancelled")
        apply_failures = apply_translations(www, entries, translations)
        report.failures.extend(apply_failures)
        report.entries_applied = len(translations) - len(apply_failures)
        report.live_api_used = isinstance(transport, DeepSeekTransport) and bool(pending)
        failed_ids = {failure.entry_id for failure in apply_failures}
        report.modified_files = sorted(
            {
                entry.relative_file
                for entry in entries
                if entry.entry_id in translations and entry.entry_id not in failed_ids
            }
        )
        for entry in entries:
            candidate = translations.get(entry.entry_id)
            if candidate is None:
                continue
            report.diffs.append(
                {
                    "id": entry.entry_id,
                    "file": entry.relative_file,
                    "diff": "\n".join(
                        difflib.unified_diff(entry.segments, candidate, fromfile="original", tofile="translation", lineterm="")
                    ),
                }
            )
        report_path = Path(memory_path or (Path(www).parent / ".state" / "translation-memory.json")).with_name("translation-report.json")
        report.report_path = str(atomic_write_json(report_path, report.to_dict()))
        self.progress("translate", 1.0, "translation complete")
        return report
