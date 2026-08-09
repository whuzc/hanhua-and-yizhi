"""Application service facade shared by the CLI and Tkinter GUI."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .builder import BuildService
from .config import build_config, default_control_config
from .errors import BlockedError
from .inspector import inspect_game
from .models import BuildConfig, BuildResult, InspectionReport, StageManifest, ToolchainInfo, TranslationReport, VerificationReport
from .patcher import patch_staged_www
from .security import atomic_write_json, atomic_write_text, now_utc, redact_text
from .signing import SigningService
from .staging import StageService
from .translation import (
    CHEAT_LABEL_MAX_BATCH_SIZE,
    CHEAT_LABEL_MAX_CONCURRENCY,
    TranslationService,
    cheat_label_needs_translation,
    extract_safe_entries,
    filter_cheat_label_entries,
    filter_non_chinese_entries,
    recommend_skip_translation,
)
from .verifier import VerificationService


def stage_manifest_from_dict(data: dict[str, Any]) -> StageManifest:
    return StageManifest(
        schema_version=int(data.get("schemaVersion", 1)),
        project_id=str(data["projectId"]),
        source_root=str(data["sourceRoot"]),
        staged_www=str(data["stagedWww"]),
        source_file_count=int(data["sourceFileCount"]),
        source_bytes=int(data["sourceBytes"]),
        copied_file_count=int(data["copiedFileCount"]),
        copied_bytes=int(data["copiedBytes"]),
        excluded_file_count=int(data["excludedFileCount"]),
        excluded_bytes=int(data["excludedBytes"]),
        source_snapshot_sha256=str(data["sourceSnapshotSha256"]),
        staged_snapshot_sha256=str(data["stagedSnapshotSha256"]),
        excluded_examples=list(data.get("excludedExamples", [])),
        copied_files=list(data.get("copiedFiles", [])),
        excluded_files=list(data.get("excludedFiles", [])),
        source_unchanged=bool(data.get("sourceUnchanged")),
        manifest_path=data.get("manifestPath"),
        run_id=data.get("runId"),
        source_snapshot_after_sha256=data.get("sourceSnapshotAfterSha256"),
        allowed_modified_files=list(data.get("allowedModifiedFiles", [])),
        resume_key=data.get("resumeKey"),
        prepared_snapshot_sha256=data.get("preparedSnapshotSha256"),
    )


class PipelineService:
    def __init__(self, root: str | Path, progress: Callable[[str, float, str], None] | None = None, cancel_event: threading.Event | None = None):
        self.root = Path(root).resolve(strict=False)
        self.work_root = self.root / ".work"
        self.state_root = self.root / ".state"
        self.progress = progress or (lambda *_args, **_kwargs: None)
        self.cancel_event = cancel_event or threading.Event()

    def inspect(self, source: str | Path) -> InspectionReport:
        self.progress("inspect", 0.1, "reading RPG Maker MV metadata")
        report = inspect_game(source)
        self.progress("inspect", 1.0, f"inspection status: {report.status}")
        return report

    def stage(
        self,
        report: InspectionReport,
        minimum_free_bytes: int | None = None,
        *,
        resume: bool = False,
        resume_key: str | None = None,
    ) -> StageManifest:
        return StageService(self.progress, self.cancel_event).stage(
            report,
            self.work_root,
            minimum_free_bytes=minimum_free_bytes,
            resume=resume,
            resume_key=resume_key,
        )

    def build_resume_key(
        self,
        report: InspectionReport,
        template: str | Path,
        config: BuildConfig,
        *,
        translate: bool,
        thinking_enabled: bool,
        reasoning_effort: str,
    ) -> str:
        """Fingerprint non-secret choices that affect the prepared stage.

        API keys and signing passwords are intentionally excluded: they do not
        change staged files, and a retry must be allowed to supply a new key.
        """

        payload = {
            "schema": "prepared-stage-v1",
            "sourceRoot": str(Path(report.source_root).resolve()),
            "template": str(Path(template).resolve()),
            "config": config.to_dict(),
            "translate": bool(translate),
            "thinkingEnabled": bool(thinking_enabled),
            "reasoningEffort": str(reasoning_effort),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def mark_prepared(self, stage: StageManifest) -> StageManifest:
        return StageService.mark_prepared(stage, self.cancel_event)

    def patch(self, stage: StageManifest, config: BuildConfig) -> dict[str, str | int]:
        self.progress("patch", 0.1, "injecting staged input bridge")
        result = patch_staged_www(stage.staged_www, config)
        self.progress("patch", 1.0, "input bridge and versioned config written")
        return result

    def translation_recommendation(self, stage: StageManifest) -> bool:
        entries = [
            entry
            for entry in extract_safe_entries(stage.staged_www)
            if entry.kind not in {"system-variable", "system-switch"}
        ]
        return recommend_skip_translation(entries)

    def translate(self, stage: StageManifest, **kwargs: Any) -> TranslationReport:
        report = TranslationService(self.progress, self.cancel_event).translate(
            stage.staged_www,
            memory_path=self.state_root / "translation-memory.json",
            **kwargs,
        )
        self._record_translation_modifications(stage, report)
        return report

    def cheat_labels_need_translation(self, stage: StageManifest) -> bool:
        """Return whether the mandatory cheat-menu label pass has work."""

        labels = [
            entry
            for entry in extract_safe_entries(stage.staged_www)
            if entry.kind in {"system-variable", "system-switch"}
        ]
        # The injected menu exposes a bounded, per-kind subset of System.json.
        # Use the same selector as the strict translation pass; the generic
        # Han-ratio heuristic incorrectly treats Japanese Kanji-only labels as
        # already-Chinese and would skip the mandatory pass entirely.
        visible = filter_cheat_label_entries(labels)
        locale_is_japanese = False
        system_path = Path(stage.staged_www) / "data" / "System.json"
        try:
            system_data = json.loads(system_path.read_text(encoding="utf-8"))
            locale_is_japanese = str(system_data.get("locale", "")).casefold().replace("_", "-").startswith("ja")
        except (OSError, ValueError, TypeError):
            pass
        if locale_is_japanese and visible:
            # Japanese Kanji-only labels can be byte-for-byte identical to
            # Chinese after normalization, so locale is the only reliable
            # signal for this edge case.  The strict validator still permits
            # genuinely Chinese labels to remain unchanged.
            return True
        return any(
            cheat_label_needs_translation(segment)
            for entry in visible
            for segment in entry.segments
        )

    def translate_cheat_labels(self, stage: StageManifest, **kwargs: Any) -> TranslationReport:
        """Translate only the labels exposed by the dynamic cheat menu.

        This pass is intentionally separate from optional game-text
        translation: a user may keep the game's existing Chinese dialogue,
        while the cheat controls still receive Chinese labels.
        """

        # This pass is always explicit and must not be accidentally disabled
        # by a caller forwarding the optional full-text ``force`` setting.
        kwargs.pop("force", None)
        # Keep the mandatory label pass below V4 Flash's response truncation
        # threshold. TranslationService also enforces these caps for direct
        # callers, but setting them here makes the pipeline contract explicit.
        kwargs.setdefault("batch_size", CHEAT_LABEL_MAX_BATCH_SIZE)
        kwargs.setdefault("max_concurrency", CHEAT_LABEL_MAX_CONCURRENCY)
        report = TranslationService(self.progress, self.cancel_event).translate(
            stage.staged_www,
            memory_path=self.state_root / "translation-memory.json",
            entry_kinds={"system-variable", "system-switch"},
            force=True,
            **kwargs,
        )
        self._record_translation_modifications(stage, report)
        if report.failures or report.entries_applied < report.entries_total:
            failed_count = max(len(report.failures), report.entries_total - report.entries_applied)
            first_reason = "no successful response was applied"
            if report.failures:
                first_reason = str(report.failures[0].reason)
            api_key = str(kwargs.get("api_key") or "")
            first_reason = redact_text(first_reason, (api_key,))[:240]
            reason_counts = Counter(str(failure.reason) for failure in report.failures)
            repeated = ""
            if reason_counts:
                repeated = f"; reason count: {reason_counts.most_common(1)[0][1]}"
            report_hint = f"; report: {report.report_path}" if report.report_path else ""
            raise BlockedError(
                "mandatory cheat-label translation did not complete; "
                f"{failed_count} label block(s) failed; first failure: {first_reason}"
                f"{repeated}{report_hint}"
            )
        return report

    def _record_translation_modifications(self, stage: StageManifest, report: TranslationReport) -> None:
        """Record only successful translation edits in the stage manifest.

        The verifier still hashes every staged asset.  Data JSON and the MV
        package metadata changed by the explicitly enabled translation pass
        are the sole additional exceptions, and they must be copied files
        from this same stage.
        """

        if not report.modified_files or not stage.manifest_path:
            return
        manifest_path = Path(stage.manifest_path).resolve(strict=False)
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BlockedError(f"cannot update stage manifest after translation: {exc}") from exc
        copied = data.get("copiedFiles")
        if not isinstance(copied, list):
            raise BlockedError("stage manifest copiedFiles is invalid")
        copied_paths = {
            str(item.get("path", "")).replace("\\", "/").lstrip("/")
            for item in copied
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        safe: set[str] = set()
        for raw in report.modified_files:
            relative = str(raw).replace("\\", "/").lstrip("/")
            if (
                not relative
                or relative.startswith("../")
                or "/../" in relative
                or not (relative.casefold().startswith("data/") or relative.casefold() == "package.json")
                or not relative.casefold().endswith(".json")
                or relative not in copied_paths
            ):
                raise BlockedError(f"translation modified file is outside the safe data allowlist: {relative}")
            safe.add(relative)
        existing = data.get("allowedModifiedFiles", [])
        if existing is None:
            existing = []
        if not isinstance(existing, list) or any(not isinstance(item, str) for item in existing):
            raise BlockedError("stage manifest allowedModifiedFiles is invalid")
        combined = set()
        for raw in existing:
            relative = raw.replace("\\", "/").lstrip("/")
            if (
                not relative
                or relative.startswith("../")
                or "/../" in relative
                or not (relative.casefold().startswith("data/") or relative.casefold() == "package.json")
                or not relative.casefold().endswith(".json")
                or relative not in copied_paths
            ):
                raise BlockedError(f"stage manifest allowlist contains an unsafe file: {relative}")
            combined.add(relative)
        combined.update(safe)
        data["allowedModifiedFiles"] = sorted(combined)
        atomic_write_json(manifest_path, {**data, "updatedAtUtc": now_utc()})
        stage.allowed_modified_files = sorted(combined)

    def build(
        self,
        template: str | Path,
        stage: StageManifest,
        config: BuildConfig,
        api_key: str | None = None,
        toolchain: ToolchainInfo | None = None,
    ) -> BuildResult:
        return BuildService(self.progress, self.cancel_event).build(template, stage, config, toolchain=toolchain, api_key=api_key)

    def sign(self, result: BuildResult, config: BuildConfig, password: str | None = None) -> dict[str, object]:
        if not result.apk_path:
            raise BlockedError("cannot sign a build without a fresh release APK")
        signer = SigningService(self.state_root, self.progress)
        signing = signer.sign_apk(
            result.apk_path,
            config.application_id,
            password=password,
            apksigner=result.toolchain.apksigner,
            jdk_dir=result.toolchain.jdk_dir,
            input_role="Gradle assembleRelease unsigned APK input",
        )
        # SigningService may rename Gradle's misleading ``*-unsigned.apk``
        # output.  Carry the signed path forward so verification, promotion,
        # GUI reports, and the web job all point at the same artifact.
        result.apk_path = str(signing["finalSignedApk"])
        audit_path = Path(result.work_dir).parent / "signing-report.json"
        atomic_write_json(audit_path, {**signing, "generatedAtUtc": now_utc()})
        signing["auditPath"] = str(audit_path)
        if result.log_path:
            log_path = Path(result.log_path)
            try:
                existing = log_path.read_text(encoding="utf-8")
            except OSError:
                existing = ""
            audit_line = (
                "[game2apk audit] inputRole=Gradle assembleRelease unsigned APK input; "
                f"signingMode={signing['signingMode']}; outputRole=final signed release APK; "
                f"inputApk={signing['inputApk']}; finalSignedApk={signing['finalSignedApk']}"
            )
            atomic_write_text(log_path, existing.rstrip("\r\n") + "\n" + audit_line + "\n")
        return signing

    def verify(self, result: BuildResult, config: BuildConfig, install: bool = False) -> VerificationReport:
        if not result.apk_path:
            raise BlockedError("cannot verify a build without a fresh release APK")
        report_path = Path(result.work_dir).parent / "verification-report.json"
        return VerificationService(self.progress).verify(
            result.apk_path,
            result.toolchain,
            result.started_at_utc,
            expected_application_id=config.application_id,
            expected_version_code=config.version_code,
            install=install,
            report_path=report_path,
            stage_manifest_path=Path(result.work_dir).parent / "stage-manifest.json",
        )

    def promote(self, report: VerificationReport, config: BuildConfig) -> Path:
        safe_name = re.sub(r"[^0-9A-Za-z\u3400-\u9fff_-]+", "-", config.app_name).strip("-") or config.application_id
        filename = f"{safe_name}-{config.version_name}-signed.apk"
        return VerificationService.promote(report, self.root / "dist", filename)

    def default_build_config(self) -> BuildConfig:
        data = build_config(control=default_control_config())
        return BuildConfig(
            app_name=data["appName"],
            application_id=data["applicationId"],
            version_code=data["versionCode"],
            version_name=data["versionName"],
            control_config=data["control"],
        )
