"""Application service facade shared by the CLI and Tkinter GUI."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable

from .builder import BuildService
from .config import build_config, default_control_config
from .errors import BlockedError
from .inspector import inspect_game
from .models import BuildConfig, BuildResult, InspectionReport, StageManifest, TranslationReport, VerificationReport
from .patcher import patch_staged_www
from .security import atomic_write_json, atomic_write_text, now_utc
from .signing import SigningService
from .staging import StageService
from .translation import TranslationService, extract_safe_entries, recommend_skip_translation
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

    def stage(self, report: InspectionReport, minimum_free_bytes: int | None = None) -> StageManifest:
        return StageService(self.progress, self.cancel_event).stage(report, self.work_root, minimum_free_bytes=minimum_free_bytes)

    def patch(self, stage: StageManifest, config: BuildConfig) -> dict[str, str | int]:
        self.progress("patch", 0.1, "injecting staged input bridge")
        result = patch_staged_www(stage.staged_www, config)
        self.progress("patch", 1.0, "input bridge and versioned config written")
        return result

    def translation_recommendation(self, stage: StageManifest) -> bool:
        return recommend_skip_translation(extract_safe_entries(stage.staged_www))

    def translate(self, stage: StageManifest, **kwargs: Any) -> TranslationReport:
        return TranslationService(self.progress, self.cancel_event).translate(stage.staged_www, memory_path=self.state_root / "translation-memory.json", **kwargs)

    def build(self, template: str | Path, stage: StageManifest, config: BuildConfig, api_key: str | None = None) -> BuildResult:
        return BuildService(self.progress, self.cancel_event).build(template, stage, config, api_key=api_key)

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
                "signingMode=signed-in-place; outputRole=final signed release APK; "
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
