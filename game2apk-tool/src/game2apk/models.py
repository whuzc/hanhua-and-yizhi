"""Small, JSON-friendly domain models shared by CLI, GUI and services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Risk:
    code: str
    level: str
    message: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "level": self.level,
            "message": self.message,
            "evidence": list(self.evidence),
        }


@dataclass
class InspectionReport:
    source_root: str
    www_root: str
    engine: str
    engine_version: str | None
    title: str | None
    effective_width: int | None
    effective_height: int | None
    mv_default_width: int | None
    mv_default_height: int | None
    outer_window_width: int | None
    outer_window_height: int | None
    has_encrypted_images: bool
    has_encrypted_audio: bool
    encryption_key_present: bool
    file_count: int
    total_bytes: int
    extensions: dict[str, dict[str, int]]
    enabled_plugins: list[str]
    disabled_plugins: list[str]
    custom_keys: list[dict[str, Any]]
    risks: list[Risk] = field(default_factory=list)
    source_writable: bool = False
    missing_required: list[str] = field(default_factory=list)
    missing_references: list[str] = field(default_factory=list)
    case_collisions: list[list[str]] = field(default_factory=list)
    long_paths: list[str] = field(default_factory=list)
    resource_headers: dict[str, int] = field(default_factory=dict)
    plugin_risks: dict[str, list[str]] = field(default_factory=dict)
    status: str = "compatible"

    @property
    def blocked(self) -> bool:
        return self.status == "blocked" or any(r.level == "block" for r in self.risks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_root": self.source_root,
            "www_root": self.www_root,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "title": self.title,
            "effective_resolution": {
                "width": self.effective_width,
                "height": self.effective_height,
                "source": "YEP_CoreEngine runtime override" if self._has_yep_override() else "MV/runtime metadata",
            },
            "mv_default_resolution": {
                "width": self.mv_default_width,
                "height": self.mv_default_height,
            },
            "outer_window_resolution": {
                "width": self.outer_window_width,
                "height": self.outer_window_height,
            },
            "encrypted_resources": {
                "images": self.has_encrypted_images,
                "audio": self.has_encrypted_audio,
                "key_present": self.encryption_key_present,
            },
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "extensions": self.extensions,
            "enabled_plugins": self.enabled_plugins,
            "disabled_plugins": self.disabled_plugins,
            "custom_keys": self.custom_keys,
            "source_writable": self.source_writable,
            "missing_required": self.missing_required,
            "missing_references": self.missing_references,
            "case_collisions": self.case_collisions,
            "long_paths": self.long_paths,
            "resource_headers": self.resource_headers,
            "plugin_risks": self.plugin_risks,
            "risks": [risk.to_dict() for risk in self.risks],
            "status": self.status,
        }

    def _has_yep_override(self) -> bool:
        return any(plugin.lower() == "yep_coreengine" for plugin in self.enabled_plugins) and (
            self.effective_width != self.mv_default_width
            or self.effective_height != self.mv_default_height
        )


@dataclass
class StageManifest:
    schema_version: int
    project_id: str
    source_root: str
    staged_www: str
    source_file_count: int
    source_bytes: int
    copied_file_count: int
    copied_bytes: int
    excluded_file_count: int
    excluded_bytes: int
    source_snapshot_sha256: str
    staged_snapshot_sha256: str
    excluded_examples: list[str] = field(default_factory=list)
    copied_files: list[dict[str, Any]] = field(default_factory=list)
    excluded_files: list[dict[str, Any]] = field(default_factory=list)
    source_unchanged: bool = False
    manifest_path: str | None = None
    run_id: str | None = None
    source_snapshot_after_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "projectId": self.project_id,
            "sourceRoot": self.source_root,
            "stagedWww": self.staged_www,
            "sourceFileCount": self.source_file_count,
            "sourceBytes": self.source_bytes,
            "copiedFileCount": self.copied_file_count,
            "copiedBytes": self.copied_bytes,
            "excludedFileCount": self.excluded_file_count,
            "excludedBytes": self.excluded_bytes,
            "sourceSnapshotSha256": self.source_snapshot_sha256,
            "stagedSnapshotSha256": self.staged_snapshot_sha256,
            "excludedExamples": list(self.excluded_examples),
            "copiedFiles": list(self.copied_files),
            "excludedFiles": list(self.excluded_files),
            "sourceUnchanged": self.source_unchanged,
            "manifestPath": self.manifest_path,
            "runId": self.run_id,
            "sourceSnapshotAfterSha256": self.source_snapshot_after_sha256,
        }


@dataclass
class TranslationEntry:
    entry_id: str
    relative_file: str
    kind: str
    field: str
    segments: list[str]
    locations: list[str]
    source_sha256: str
    placeholder_tokens: list[list[str]]

    @property
    def source_text(self) -> str:
        return "\n".join(self.segments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.entry_id,
            "file": self.relative_file,
            "kind": self.kind,
            "field": self.field,
            "segments": list(self.segments),
            "locations": list(self.locations),
            "sourceSha256": self.source_sha256,
            "placeholderTokens": [list(tokens) for tokens in self.placeholder_tokens],
        }


@dataclass
class TranslationFailure:
    entry_id: str
    reason: str
    original: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.entry_id, "reason": self.reason, "original": self.original}


@dataclass
class TranslationReport:
    schema_version: int
    source_language: str
    target_language: str
    model: str
    entries_total: int
    entries_applied: int
    entries_cached: int
    failures: list[TranslationFailure] = field(default_factory=list)
    diffs: list[dict[str, Any]] = field(default_factory=list)
    skipped_recommended: bool = False
    live_api_used: bool = False
    report_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "sourceLanguage": self.source_language,
            "targetLanguage": self.target_language,
            "model": self.model,
            "entriesTotal": self.entries_total,
            "entriesApplied": self.entries_applied,
            "entriesCached": self.entries_cached,
            "failures": [failure.to_dict() for failure in self.failures],
            "diffs": list(self.diffs),
            "skippedRecommended": self.skipped_recommended,
            "liveApiUsed": self.live_api_used,
            "reportPath": self.report_path,
        }


@dataclass
class BuildConfig:
    app_name: str
    application_id: str
    version_code: int
    version_name: str
    icon_path: str | None = None
    control_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "appName": self.app_name,
            "applicationId": self.application_id,
            "versionCode": self.version_code,
            "versionName": self.version_name,
            "iconPath": self.icon_path,
            "control": self.control_config,
        }


@dataclass
class ToolchainInfo:
    sdk_dir: str | None
    jdk_dir: str | None
    gradle_user_home: str | None
    wrapper: str | None
    aapt2: str | None
    zipalign: str | None
    apksigner: str | None
    adb: str | None
    issues: list[str] = field(default_factory=list)
    aapt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sdkDir": self.sdk_dir,
            "jdkDir": self.jdk_dir,
            "gradleUserHome": self.gradle_user_home,
            "wrapper": self.wrapper,
            "aapt2": self.aapt2,
            "zipalign": self.zipalign,
            "apksigner": self.apksigner,
            "adb": self.adb,
            "aapt": self.aapt,
            "issues": list(self.issues),
        }


@dataclass
class BuildResult:
    started_at_utc: str
    finished_at_utc: str
    return_code: int
    command: list[str]
    work_dir: str
    apk_path: str | None
    log_path: str | None
    toolchain: ToolchainInfo
    cancelled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "startedAtUtc": self.started_at_utc,
            "finishedAtUtc": self.finished_at_utc,
            "returnCode": self.return_code,
            "command": list(self.command),
            "workDir": self.work_dir,
            "apkPath": self.apk_path,
            "logPath": self.log_path,
            "toolchain": self.toolchain.to_dict(),
            "cancelled": self.cancelled,
        }


@dataclass
class VerificationReport:
    apk_path: str
    sha256: str
    file_size: int
    fresh: bool
    metadata: dict[str, Any]
    critical_assets: dict[str, Any]
    stage_assets: dict[str, Any]
    permissions: dict[str, Any]
    zipalign: dict[str, Any]
    apksigner: dict[str, Any]
    aapt: dict[str, Any]
    device: dict[str, Any]
    passed: bool
    signature_candidate: bool
    report_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "apkPath": self.apk_path,
            "sha256": self.sha256,
            "fileSize": self.file_size,
            "fresh": self.fresh,
            "metadata": self.metadata,
            "criticalAssets": self.critical_assets,
            "stageAssets": self.stage_assets,
            "permissions": self.permissions,
            "zipalign": self.zipalign,
            "apksigner": self.apksigner,
            "aapt": self.aapt,
            "device": self.device,
            "passed": self.passed,
            "signatureCandidate": self.signature_candidate,
            "reportPath": self.report_path,
        }
