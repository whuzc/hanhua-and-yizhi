"""Read-only source staging and marker-scoped cleanup."""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path
from typing import Iterable

from .errors import BlockedError, CancelledError
from .models import InspectionReport, StageManifest
from .security import atomic_write_json, create_work_marker, now_utc, require_within, safe_remove_workdir, stable_project_id


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
    ) -> StageManifest:
        if report.blocked:
            raise BlockedError("cannot stage a blocked inspection report")
        source_www = Path(report.www_root).resolve(strict=True)
        base = Path(work_base).resolve(strict=False)
        base.mkdir(parents=True, exist_ok=True)
        project_id = project_id or stable_project_id(report.source_root)
        work_dir = base / project_id
        create_work_marker(work_dir, project_id, report.source_root)
        run_dir = work_dir / "runs" / uuid.uuid4().hex
        staged_www = run_dir / "staged" / "www"
        staged_www.mkdir(parents=True, exist_ok=True)
        self.progress("stage", 0.0, "snapshotting source")
        source_entries, source_bytes = _snapshot(source_www, self.cancel_event)
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
        )
        manifest_path = run_dir / "stage-manifest.json"
        manifest.manifest_path = str(manifest_path)
        atomic_write_json(manifest_path, {**manifest.to_dict(), "createdAtUtc": now_utc()})
        self.progress("stage", 1.0, "staging complete")
        return manifest

    @staticmethod
    def cleanup(work_dir: str | os.PathLike[str], work_base: str | os.PathLike[str], project_id: str) -> None:
        # safe_remove_workdir performs all marker, parent and project checks.
        safe_remove_workdir(work_dir, work_base, project_id)
