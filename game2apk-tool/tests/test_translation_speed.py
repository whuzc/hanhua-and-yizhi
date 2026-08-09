from __future__ import annotations

import json
import re
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from game2apk.errors import BlockedError, CancelledError, TranslationError
from game2apk.models import TranslationEntry
from game2apk.translation import (
    CHEAT_VISIBLE_SWITCH_LIMIT,
    CHEAT_VISIBLE_VARIABLE_LIMIT,
    CHEAT_LABEL_PROMPT_VERSION,
    DEFAULT_TRANSLATION_MODEL,
    TranslationMemory,
    TranslationService,
    cheat_label_needs_translation,
    choose_model,
    filter_cheat_label_entries,
    normalize_model,
    translation_memory_key,
    validate_simplified_chinese_label,
)


class _ParallelTransport:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def chat(self, payload: dict, _api_key: str) -> dict:
        with self.lock:
            self.calls.append(payload)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            # Make overlap observable without making the test slow.
            time.sleep(0.04)
            prompt = payload["messages"][-1]["content"]
            items = json.loads(prompt.split("INPUT=", 1)[1])
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "translations": [
                                        {"id": item["id"], "segments": [f"{segment} [zh]" for segment in item["segments"]]}
                                        for item in items
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        },
                    }
                ]
            }
        finally:
            with self.lock:
                self.active -= 1


class _FailFirstTransport(_ParallelTransport):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def chat(self, payload: dict, api_key: str) -> dict:
        if not self.failed:
            self.failed = True
            raise RuntimeError(f"synthetic provider failure for {api_key}")
        return super().chat(payload, api_key)


class _StrictChineseLabelTransport:
    """Offline provider that emits valid zh-CN labels and preserves controls."""

    def __init__(self, echo: bool = False) -> None:
        self.calls: list[dict] = []
        self.echo = echo

    def chat(self, payload: dict, _api_key: str) -> dict:
        self.calls.append(payload)
        prompt = payload["messages"][-1]["content"]
        items = json.loads(prompt.split("INPUT=", 1)[1])
        translations = []
        for item in items:
            segments = []
            for segment in item["segments"]:
                if self.echo:
                    segments.append(segment)
                    continue
                controls = re.findall(r"__G2A_TOKEN_\d+__", segment)
                latin = re.findall(r"[A-Za-z]+", segment)
                suffix = controls + latin
                segments.append("\u4e2d\u6587\u6807\u7b7e" + (" " + " ".join(suffix) if suffix else ""))
            translations.append({"id": item["id"], "segments": segments})
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"translations": translations}, ensure_ascii=False)},
                }
            ]
        }


class _SizeLimitedStrictTransport(_StrictChineseLabelTransport):
    """Simulate a provider truncating or rejecting an oversized JSON batch."""

    def __init__(self, limit: int = 8) -> None:
        super().__init__()
        self.limit = limit
        self.max_items = 0

    def chat(self, payload: dict, api_key: str) -> dict:
        prompt = payload["messages"][-1]["content"]
        items = json.loads(prompt.split("INPUT=", 1)[1])
        self.max_items = max(self.max_items, len(items))
        if len(items) > self.limit:
            raise TranslationError("DeepSeek response was not complete: length")
        return super().chat(payload, api_key)


class _RepairOnRetryTransport:
    """Echo the first thinking response, then repair singleton retries."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def chat(self, payload: dict, _api_key: str) -> dict:
        self.calls.append(payload)
        items = json.loads(payload["messages"][-1]["content"].split("INPUT=", 1)[1])
        if len(self.calls) == 1:
            translated = [{"id": item["id"], "segments": list(item["segments"])} for item in items]
        else:
            translated = [{"id": item["id"], "segments": ["中文标签"] * len(item["segments"])} for item in items]
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"translations": translated}, ensure_ascii=False)},
                }
            ]
        }


class TranslationSpeedTests(unittest.TestCase):
    def _www(self, root: Path) -> Path:
        www = root / "www"
        (www / "data").mkdir(parents=True)
        commands = []
        for text in ("One", "Two", "Repeat", "Repeat", "Five", "Six"):
            commands.extend(
                [
                    {"code": 101, "parameters": ["", 0, 0, 2]},
                    {"code": 401, "parameters": [text]},
                ]
            )
        (www / "data" / "Map001.json").write_text(
            json.dumps({"events": [None, {"pages": [{"list": commands}]}]}),
            encoding="utf-8",
        )
        return www

    def test_v4_flash_thinking_parallel_and_duplicate_reuse(self) -> None:
        with TemporaryDirectory() as temporary:
            www = self._www(Path(temporary))
            transport = _ParallelTransport()
            report = TranslationService().translate(
                www,
                api_key="not-a-real-key",
                transport=transport,
                memory_path=Path(temporary) / "memory.json",
                confirmed_third_party=True,
                force=True,
                batch_size=1,
                max_concurrency=3,
            )

            self.assertEqual(report.model, DEFAULT_TRANSLATION_MODEL)
            self.assertEqual(report.entries_total, 6)
            self.assertEqual(report.entries_applied, 6)
            self.assertLess(len(transport.calls), report.entries_total)
            self.assertGreaterEqual(transport.max_active, 2)
            for payload in transport.calls:
                self.assertEqual(payload["model"], DEFAULT_TRANSLATION_MODEL)
                self.assertEqual(payload["thinking"], {"type": "enabled"})
                self.assertEqual(payload["reasoning_effort"], "high")
                self.assertGreaterEqual(payload["max_tokens"], 2048)
                self.assertEqual(payload["response_format"], {"type": "json_object"})
                prompt = payload["messages"][-1]["content"]
                self.assertIn("one coherent dialogue or text block", prompt)
                self.assertIn("never translate word-by-word", prompt)
                self.assertIn("line boundary", prompt)

            data = json.loads((www / "data" / "Map001.json").read_text(encoding="utf-8"))
            values = [command["parameters"][0] for command in data["events"][1]["pages"][0]["list"] if command["code"] == 401]
            self.assertEqual(values, ["One [zh]", "Two [zh]", "Repeat [zh]", "Repeat [zh]", "Five [zh]", "Six [zh]"])

    def test_disabled_thinking_omits_reasoning_effort(self) -> None:
        with TemporaryDirectory() as temporary:
            www = self._www(Path(temporary))
            transport = _ParallelTransport()
            TranslationService().translate(
                www,
                api_key="not-a-real-key",
                transport=transport,
                memory_path=Path(temporary) / "memory.json",
                confirmed_third_party=True,
                force=True,
                batch_size=100,
                max_concurrency=1,
                thinking_enabled=False,
            )
            self.assertTrue(transport.calls)
            for payload in transport.calls:
                self.assertEqual(payload["thinking"], {"type": "disabled"})
                self.assertNotIn("reasoning_effort", payload)

    def test_cheat_label_scope_translates_system_labels_without_dialogue(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            www = self._www(root)
            (www / "data" / "System.json").write_text(
                json.dumps(
                    {
                        "gameTitle": "中文游戏",
                        "terms": {},
                        "variables": ["", "ステEXP淫乱", "已经中文"],
                        "switches": ["", "ギャラリー解放"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            transport = _StrictChineseLabelTransport()
            report = TranslationService().translate(
                www,
                api_key="not-a-real-key",
                transport=transport,
                memory_path=root / "memory.json",
                confirmed_third_party=True,
                force=True,
                entry_kinds={"system-variable", "system-switch"},
                batch_size=100,
                max_concurrency=1,
            )
            # Strict cheat-label scope bypasses the generic Han-ratio filter,
            # so an already-Chinese label is included as well.  This keeps
            # Kanji-only Japanese labels from being silently skipped.
            self.assertEqual(report.entries_total, 3)
            self.assertEqual(report.entries_applied, 3)
            self.assertTrue(transport.calls)
            self.assertIn("Simplified Chinese (zh-CN)", transport.calls[0]["messages"][1]["content"])
            system = json.loads((www / "data" / "System.json").read_text(encoding="utf-8"))
            self.assertEqual(system["variables"][1], "\u4e2d\u6587\u6807\u7b7e EXP")
            self.assertEqual(system["variables"][2], "\u4e2d\u6587\u6807\u7b7e")
            self.assertEqual(system["switches"][1], "\u4e2d\u6587\u6807\u7b7e")
            dialogue = json.loads((www / "data" / "Map001.json").read_text(encoding="utf-8"))
            values = [command["parameters"][0] for command in dialogue["events"][1]["pages"][0]["list"] if command["code"] == 401]
            self.assertEqual(values[0], "One")

    def test_strict_cheat_batches_are_bounded_for_provider_output_limits(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            www = self._www(root)
            (www / "data" / "System.json").write_text(
                json.dumps(
                    {
                        "gameTitle": "Demo",
                        "locale": "ja_JP",
                        "terms": {},
                        "variables": [""] + [f"発情メッセージ{i}" for i in range(1, 61)],
                        "switches": [""],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            transport = _SizeLimitedStrictTransport(limit=8)
            report = TranslationService().translate(
                www,
                api_key="not-a-real-key",
                transport=transport,
                memory_path=root / "memory.json",
                confirmed_third_party=True,
                force=True,
                entry_kinds={"system-variable", "system-switch"},
                batch_size=100,
                max_concurrency=4,
            )
            self.assertEqual(report.entries_total, 60)
            self.assertEqual(report.entries_applied, 60)
            self.assertFalse(report.failures)
            # The service caps the initial strict request at the safe batch
            # size, then recursively halves only when this synthetic provider
            # reports a truncated response.
            self.assertLessEqual(transport.max_items, 24)

    def test_invalid_thinking_labels_get_singleton_non_thinking_repair(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            www = self._www(root)
            (www / "data" / "System.json").write_text(
                json.dumps(
                    {"gameTitle": "Demo", "locale": "ja_JP", "terms": {}, "variables": ["", "濡れ", "発情中", "犯され中"], "switches": [""]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            transport = _RepairOnRetryTransport()
            report = TranslationService().translate(
                www,
                api_key="not-a-real-key",
                transport=transport,
                memory_path=root / "memory.json",
                confirmed_third_party=True,
                force=True,
                entry_kinds={"system-variable", "system-switch"},
                batch_size=100,
                max_concurrency=1,
            )
            self.assertEqual(report.entries_applied, 3)
            self.assertFalse(report.failures)
            self.assertEqual(len(transport.calls), 4)
            for payload in transport.calls[1:]:
                self.assertEqual(payload["thinking"], {"type": "disabled"})

    def test_pipeline_reports_first_cheat_label_failure_reason_without_key(self) -> None:
        from types import SimpleNamespace
        from game2apk.pipeline import PipelineService

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            www = self._www(root)
            (www / "data" / "System.json").write_text(
                json.dumps(
                    {"gameTitle": "Demo", "locale": "ja_JP", "terms": {}, "variables": ["", "発情中"], "switches": [""]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            class AlwaysFailTransport:
                def chat(self, _payload: dict, api_key: str) -> dict:
                    raise RuntimeError(f"synthetic provider failure for {api_key}")

            with self.assertRaises(BlockedError) as raised:
                PipelineService(root).translate_cheat_labels(
                    SimpleNamespace(staged_www=str(www), manifest_path=None),
                    api_key="secret-token",
                    transport=AlwaysFailTransport(),
                    confirmed_third_party=True,
                )
            message = str(raised.exception)
            self.assertIn("first failure", message)
            self.assertIn("synthetic provider failure", message)
            self.assertNotIn("secret-token", message)

    def test_strict_cheat_labels_reject_japanese_echo_but_preserve_english(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            www = self._www(root)
            (www / "data" / "System.json").write_text(
                json.dumps(
                    {
                        "gameTitle": "游戏",
                        "terms": {},
                        "variables": ["", "犯され中", "Gallery unlocked"],
                        "switches": [""],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report = TranslationService().translate(
                www,
                api_key="not-a-real-key",
                transport=_StrictChineseLabelTransport(echo=True),
                memory_path=root / "memory.json",
                confirmed_third_party=True,
                force=True,
                entry_kinds={"system-variable", "system-switch"},
                batch_size=100,
                max_concurrency=1,
            )
            self.assertEqual(report.entries_total, 2)
            self.assertEqual(report.entries_applied, 1)
            self.assertEqual(len(report.failures), 1)
            system = json.loads((www / "data" / "System.json").read_text(encoding="utf-8"))
            self.assertEqual(system["variables"][1], "犯され中")
            self.assertEqual(system["variables"][2], "Gallery unlocked")

    def test_strict_cache_namespace_does_not_reuse_generic_translation(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            www = self._www(root)
            (www / "data" / "System.json").write_text(
                json.dumps(
                    {"gameTitle": "游戏", "terms": {}, "variables": ["", "Gallery unlocked"], "switches": [""]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            memory_path = root / "memory.json"
            from game2apk.translation import extract_safe_entries

            entry = next(item for item in extract_safe_entries(www) if item.kind == "system-variable")
            memory = TranslationMemory(memory_path)
            memory.put(
                translation_memory_key(entry.source_text, "zh-CN", DEFAULT_TRANSLATION_MODEL),
                entry.entry_id,
                entry.source_sha256,
                ["Gallery unlocked"],
            )
            memory.save()
            transport = _StrictChineseLabelTransport()
            report = TranslationService().translate(
                www,
                api_key="not-a-real-key",
                transport=transport,
                memory_path=memory_path,
                confirmed_third_party=True,
                force=True,
                entry_kinds={"system-variable", "system-switch"},
                batch_size=100,
                max_concurrency=1,
            )
            self.assertEqual(report.entries_cached, 0)
            self.assertTrue(transport.calls)
            strict_key = translation_memory_key(
                entry.source_text,
                "zh-CN",
                DEFAULT_TRANSLATION_MODEL,
                prompt_version=CHEAT_LABEL_PROMPT_VERSION,
            )
            self.assertIn(strict_key, json.loads(memory_path.read_text(encoding="utf-8"))["entries"])

    def test_strict_validator_allows_game_code_tokens_and_english(self) -> None:
        self.assertTrue(validate_simplified_chinese_label("SE [自定义]", "SE [自定义] ")[0])
        self.assertTrue(validate_simplified_chinese_label("X/Y 12", "X/Y 12")[0])
        self.assertTrue(validate_simplified_chinese_label("Gallery unlocked", "Gallery unlocked")[0])
        self.assertTrue(validate_simplified_chinese_label("MAP:\u5f8c\u308d", "MAP:\u540e\u65b9")[0])
        self.assertFalse(validate_simplified_chinese_label("MAP:\u5f8c\u308d", "\u5730\u56fe:\u540e\u65b9")[0])
        self.assertFalse(validate_simplified_chinese_label("犯され中", "犯され中")[0])

    def test_cheat_scope_matches_runtime_limits_and_japanese_signals(self) -> None:
        variables = [
            TranslationEntry(
                f"v{i}", "data/System.json", "system-variable", "variables",
                [f"变量{i}"], [f"/variables/{i}"], str(i), [[]],
            )
            for i in range(CHEAT_VISIBLE_VARIABLE_LIMIT + 20)
        ]
        switches = [
            TranslationEntry(
                f"s{i}", "data/System.json", "system-switch", "switches",
                [f"开关{i}"], [f"/switches/{i}"], str(i), [[]],
            )
            for i in range(CHEAT_VISIBLE_SWITCH_LIMIT + 20)
        ]
        selected = filter_cheat_label_entries(variables + switches)
        self.assertEqual(sum(item.kind == "system-variable" for item in selected), CHEAT_VISIBLE_VARIABLE_LIMIT)
        self.assertEqual(sum(item.kind == "system-switch" for item in selected), CHEAT_VISIBLE_SWITCH_LIMIT)
        self.assertTrue(cheat_label_needs_translation("拘束距離"))
        self.assertFalse(cheat_label_needs_translation("Gallery unlocked"))
        self.assertFalse(cheat_label_needs_translation("SE"))

    def test_model_aliases_normalize_to_official_identifier(self) -> None:
        self.assertEqual(normalize_model("v4flash"), DEFAULT_TRANSLATION_MODEL)
        self.assertEqual(normalize_model("deepseek-v4flash"), DEFAULT_TRANSLATION_MODEL)
        self.assertEqual(normalize_model("custom-model"), "custom-model")
        self.assertEqual(choose_model(["v4flash"]), DEFAULT_TRANSLATION_MODEL)

    def test_cancellation_stops_waiting_for_parallel_batches(self) -> None:
        with TemporaryDirectory() as temporary:
            www = self._www(Path(temporary))
            transport = _ParallelTransport()
            cancel_event = threading.Event()

            def cancel() -> None:
                time.sleep(0.06)
                cancel_event.set()

            threading.Thread(target=cancel, daemon=True).start()
            started = time.monotonic()
            with self.assertRaises(CancelledError):
                TranslationService(cancel_event=cancel_event).translate(
                    www,
                    api_key="not-a-real-key",
                    transport=transport,
                    memory_path=Path(temporary) / "memory.json",
                    confirmed_third_party=True,
                    force=True,
                    batch_size=1,
                    max_concurrency=3,
                )
            self.assertLess(time.monotonic() - started, 1.0)

    def test_failed_batch_does_not_abort_later_batches_or_leak_key(self) -> None:
        with TemporaryDirectory() as temporary:
            www = self._www(Path(temporary))
            transport = _FailFirstTransport()
            report = TranslationService().translate(
                www,
                api_key="secret-token",
                transport=transport,
                memory_path=Path(temporary) / "memory.json",
                confirmed_third_party=True,
                force=True,
                batch_size=1,
                max_concurrency=1,
            )
            self.assertEqual(report.entries_total, 6)
            self.assertEqual(report.entries_applied, 5)
            self.assertTrue(report.failures)
            serialized = json.dumps(report.to_dict(), ensure_ascii=False)
            self.assertNotIn("secret-token", serialized)
            # One unique block failed; the remaining four unique blocks still
            # reached the transport after that failure.
            self.assertEqual(len(transport.calls), 4)


if __name__ == "__main__":
    unittest.main()
