"""Read-only source staging and marker-scoped cleanup."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Iterable

from .errors import BlockedError, CancelledError
from .models import InspectionReport, StageManifest
from .security import TOOL_MARKER, TOOL_NAME, atomic_write_json, create_work_marker, now_utc, require_within, safe_remove_workdir, stable_project_id


_EXCLUDED_SUFFIXES = {".rpgsave", ".sfk", ".sfl"}
_TEMP_NAMES = {"thumbs.db", "desktop.ini"}


def _is_excluded(relative: str, is_dir: bool) -> bool:
    parts = relative.replace("\\", "/").split("/")
    name = parts[-1]
    folded = name.casefold()
    if parts and parts[0].casefold() == "save":
        return True
    if not is_dir and (
        Path(name).suffix.casefold() in _EXCLUDED_SUFFIXES
        or folded in _TEMP_NAMES
        or folded.startswith(".~")
        or folded.startswith("~$")
        or folded.endswith(".tmp")
        or folded.endswith(".temp")
        or folded.endswith(".bak")
    ):
        return True
    return False


def _walk_files(root: Path, *, include_excluded: bool = False) -> Iterable[tuple[Path, str]]:
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise BlockedError(f"unable to read source directory: {current}") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            if entry.is_symlink():
                raise BlockedError(f"symlinked source content is not allowed: {relative}")
            if entry.is_dir(follow_symlinks=False):
                if include_excluded or not _is_excluded(relative, True):
                    stack.append(path)
            elif entry.is_file(follow_symlinks=False):
                yield path, relative


def _sha256_file(path: Path, cancel_event=None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError("staging cancelled")
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot(root: Path, cancel_event=None) -> tuple[list[tuple[str, int, str]], int]:
    entries: list[tuple[str, int, str]] = []
    total = 0
    for path, relative in sorted(_walk_files(root, include_excluded=True), key=lambda item: item[1].casefold()):
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("staging cancelled")
        size = path.stat().st_size
        digest = _sha256_file(path, cancel_event)
        entries.append((relative, size, digest))
        total += size
    return entries, total


def _digest_entries(entries: list[tuple[str, int, str]]) -> str:
    digest = hashlib.sha256()
    for relative, size, file_digest in entries:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


class StageService:
    """Copy only ``www`` into a marker-protected work area."""

    def __init__(self, progress=None, cancel_event=None):
        self.progress = progress or (lambda *_args, **_kwargs: None)
        self.cancel_event = cancel_event

    def stage(
        self,
        report: InspectionReport,
        work_base: str | os.PathLike[str],
        project_id: str | None = None,
        minimum_free_bytes: int | None = None,
        space_multiplier: float = 2.5,
        extra_space_bytes: int = 2 * 1024**3,
        *,
        resume: bool = False,
        resume_key: str | None = None,
    ) -> StageManifest:
        if report.blocked:
            raise BlockedError("cannot stage a blocked inspection report")
        source_www = Path(report.www_root).resolve(strict=True)
        base = Path(work_base).resolve(strict=False)
        base.mkdir(parents=True, exist_ok=True)
        project_id = project_id or stable_project_id(report.source_root)
        work_dir = base / project_id
        create_work_marker(work_dir, project_id, report.source_root)
        self.progress("stage", 0.0, "snapshotting source")
        source_entries, source_bytes = _snapshot(source_www, self.cancel_event)
        if resume and resume_key:
            resumed = self._find_prepared_checkpoint(
                report,
                work_dir,
                source_www,
                source_entries,
                resume_key,
            )
            if resumed is not None:
                self.progress("stage", 1.0, "resuming prepared checkpoint")
                return resumed

        run_dir = work_dir / "runs" / uuid.uuid4().hex
        staged_www = run_dir / "staged" / "www"
        staged_www.mkdir(parents=True, exist_ok=True)
        all_source_files = list(_walk_files(source_www, include_excluded=True))
        excluded_files: list[tuple[Path, str]] = []
        for path, relative in all_source_files:
            if _is_excluded(relative, False):
                excluded_files.append((path, relative))
        source_entry_by_path = {relative: (size, digest) for relative, size, digest in source_entries}
        excluded_bytes = sum(path.stat().st_size for path, _ in excluded_files)
        required_free = minimum_free_bytes
        if required_free is None:
            required_free = int(source_bytes * space_multiplier) + int(extra_space_bytes)
        try:
            free_bytes = shutil.disk_usage(base).free
        except OSError as exc:
            raise BlockedError(f"unable to check free disk space for {base}") from exc
        if free_bytes < required_free:
            raise BlockedError(
                f"insufficient free space: {free_bytes} bytes available, {required_free} required"
            )

        copied = 0
        copied_bytes = 0
        included_files = [(path, relative) for path, relative in all_source_files if not _is_excluded(relative, False)]
        total_included = len(included_files)
        for index, (source_path, relative) in enumerate(included_files, start=1):
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise CancelledError("staging cancelled")
            destination = staged_www / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
            copied += 1
            copied_bytes += destination.stat().st_size
            if index == total_included or index % max(1, total_included // 100) == 0:
                self.progress("stage", index / max(1, total_included), f"copied {index}/{total_included} files")

        self.progress("stage", 0.98, "checking source invariance")
        after_entries, _ = _snapshot(source_www, self.cancel_event)
        source_unchanged = source_entries == after_entries
        if not source_unchanged:
            raise BlockedError("source www changed while staging; no result is accepted")
        source_snapshot_after_sha256 = _digest_entries(after_entries)
        staged_entries, _ = _snapshot(staged_www, self.cancel_event)
        manifest = StageManifest(
            schema_version=1,
            project_id=project_id,
            source_root=str(Path(report.source_root).resolve()),
            staged_www=str(staged_www),
            source_file_count=len(source_entries),
            source_bytes=source_bytes,
            copied_file_count=copied,
            copied_bytes=copied_bytes,
            excluded_file_count=len(excluded_files),
            excluded_bytes=excluded_bytes,
            source_snapshot_sha256=_digest_entries(source_entries),
            staged_snapshot_sha256=_digest_entries(staged_entries),
            excluded_examples=[relative for _, relative in sorted(excluded_files, key=lambda item: item[1])[:50]],
            copied_files=[
                {"path": relative, "size": size, "sha256": digest}
                for relative, size, digest in staged_entries
            ],
            excluded_files=[
                {
                    "path": relative,
                    "size": source_entry_by_path[relative][0],
                    "sha256": source_entry_by_path[relative][1],
                }
                for path, relative in sorted(excluded_files, key=lambda item: item[1])
            ],
            source_unchanged=True,
            run_id=run_dir.name,
            source_snapshot_after_sha256=source_snapshot_after_sha256,
            resume_key=resume_key,
        )
        manifest_path = run_dir / "stage-manifest.json"
        manifest.manifest_path = str(manifest_path)
        atomic_write_json(manifest_path, {**manifest.to_dict(), "createdAtUtc": now_utc()})
        self.progress("stage", 1.0, "staging complete")
        return manifest

    @staticmethod
    def mark_prepared(stage: StageManifest, cancel_event=None) -> StageManifest:
        """Mark a patched/translated stage as safe to reuse after a failed build.

        This is deliberately a separate checkpoint from the initial copy
        manifest.  It fingerprints the exact staged ``www`` after all allowed
        patch/translation edits, so a retry cannot accidentally reuse a
        partially modified or unrelated run directory.
        """

        if not stage.manifest_path or not stage.run_id or not stage.project_id:
            raise BlockedError("cannot checkpoint a stage without an owned manifest")
        manifest_path = Path(stage.manifest_path).resolve(strict=True)
        run_dir = manifest_path.parent
        expected_staged = (run_dir / "staged" / "www").resolve(strict=False)
        staged_www = Path(stage.staged_www).resolve(strict=True)
        if staged_www != expected_staged:
            raise BlockedError("stage checkpoint path does not match its run manifest")
        if run_dir.name != stage.run_id or run_dir.parent.name != "runs":
            raise BlockedError("stage checkpoint run identity is invalid")
        require_within(manifest_path, run_dir, "stage manifest")
        require_within(staged_www, run_dir, "staged www")
        work_dir = run_dir.parent.parent
        marker_path = work_dir / TOOL_MARKER
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BlockedError("stage checkpoint work marker is unreadable") from exc
        if marker.get("tool") != TOOL_NAME or marker.get("project_id") != stage.project_id:
            raise BlockedError("stage checkpoint work marker does not match the project")
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BlockedError(f"cannot read stage manifest for checkpoint: {exc}") from exc
        if data.get("schemaVersion") != 1 or data.get("projectId") != stage.project_id:
            raise BlockedError("stage manifest identity is invalid")
        if data.get("runId") != run_dir.name or Path(str(data.get("stagedWww", ""))).resolve(strict=False) != expected_staged:
            raise BlockedError("stage manifest path identity is invalid")
        entries, _ = _snapshot(staged_www, cancel_event)
        prepared_digest = _digest_entries(entries)
        data["preparedSnapshotSha256"] = prepared_digest
        data["manifestPath"] = str(manifest_path)
        atomic_write_json(manifest_path, {**data, "updatedAtUtc": now_utc()})
        stage.prepared_snapshot_sha256 = prepared_digest
        return stage

    def _find_prepared_checkpoint(
        self,
        report: InspectionReport,
        work_dir: Path,
        source_www: Path,
        source_entries: list[tuple[str, int, str]],
        resume_key: str,
    ) -> StageManifest | None:
        """Return the newest matching, unverified pre-build checkpoint."""

        runs_dir = work_dir / "runs"
        if not runs_dir.is_dir():
            return None
        source_digest = _digest_entries(source_entries)
        expected_source_root = str(Path(report.source_root).resolve())
        candidates = sorted(
            (path for path in runs_dir.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for run_dir in candidates:
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise CancelledError("staging cancelled")
            manifest_path = run_dir / "stage-manifest.json"
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
            if data.get("schemaVersion") != 1 or data.get("projectId") != work_dir.name:
                continue
            if data.get("resumeKey") != resume_key or not data.get("preparedSnapshotSha256"):
                continue
            if data.get("sourceRoot") != expected_source_root or data.get("runId") != run_dir.name:
                continue
            if (run_dir / "verification-report.json").exists():
                continue
            expected_staged = (run_dir / "staged" / "www").resolve(strict=False)
            try:
                staged_value = Path(str(data.get("stagedWww", ""))).resolve(strict=False)
            except (OSError, ValueError):
                continue
            if staged_value != expected_staged or not expected_staged.is_dir():
                continue
            try:
                source_digest_in_manifest = str(data["sourceSnapshotAfterSha256"] or data["sourceSnapshotSha256"])
                prepared_digest = str(data["preparedSnapshotSha256"])
                if source_digest_in_manifest != source_digest:
                    continue
                staged_entries, _ = _snapshot(expected_staged, self.cancel_event)
                if _digest_entries(staged_entries) != prepared_digest:
                    continue
                # A candidate is only accepted after all paths are proven to
                # remain inside this marker-owned project's run directory.
                require_within(manifest_path, run_dir, "stage manifest")
                require_within(expected_staged, run_dir, "staged www")
                manifest = self._manifest_from_dict(data, manifest_path)
            except (KeyError, TypeError, ValueError, OSError, BlockedError, CancelledError):
                if self.cancel_event is not None and self.cancel_event.is_set():
                    raise
                continue
            manifest.resumed_from_existing = True
            return manifest
        return None

    @staticmethod
    def _manifest_from_dict(data: dict, manifest_path: Path) -> StageManifest:
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
            manifest_path=str(manifest_path),
            run_id=str(data.get("runId")) if data.get("runId") is not None else None,
            source_snapshot_after_sha256=data.get("sourceSnapshotAfterSha256"),
            allowed_modified_files=list(data.get("allowedModifiedFiles", [])),
            resume_key=data.get("resumeKey"),
            prepared_snapshot_sha256=data.get("preparedSnapshotSha256"),
        )

    @staticmethod
    def cleanup(work_dir: str | os.PathLike[str], work_base: str | os.PathLike[str], project_id: str) -> None:
        # safe_remove_workdir performs all marker, parent and project checks.
        safe_remove_workdir(work_dir, work_base, project_id)
