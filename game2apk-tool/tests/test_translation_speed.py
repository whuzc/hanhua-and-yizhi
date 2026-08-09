from __future__ import annotations

import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from game2apk.errors import CancelledError
from game2apk.translation import DEFAULT_TRANSLATION_MODEL, TranslationService, choose_model, normalize_model


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

    def test_v4_flash_non_thinking_parallel_and_duplicate_reuse(self) -> None:
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
                self.assertEqual(payload["thinking"], {"type": "disabled"})
                self.assertEqual(payload["response_format"], {"type": "json_object"})

            data = json.loads((www / "data" / "Map001.json").read_text(encoding="utf-8"))
            values = [command["parameters"][0] for command in data["events"][1]["pages"][0]["list"] if command["code"] == 401]
            self.assertEqual(values, ["One [zh]", "Two [zh]", "Repeat [zh]", "Repeat [zh]", "Five [zh]", "Six [zh]"])

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
