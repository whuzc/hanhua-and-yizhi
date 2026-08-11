"""External resource-pack planning and ZIP64 packaging for very large MV games.

Android's normal APK packager uses the ZIP32 layout and cannot place entries
past the 4 GiB offset boundary.  This module keeps the game WebView runtime in
the APK and writes the staged ``www`` tree to a separate ZIP64 archive when
the conservative APK-size estimate is too close to that boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


ZIP32_MAX_BYTES = 0xFFFFFFFF
# Leave room for the APK manifest, dex, resources and ZIP central directory.
APK_SAFE_PAYLOAD_BYTES = 3_900_000_000
RESOURCE_PACK_SCHEMA_VERSION = 1

_STORED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tga",
    ".ogg", ".m4a", ".mp3", ".wav", ".webm", ".rpgmvp", ".rpgmvo",
    ".rpgmvm", ".ttf", ".otf", ".woff", ".woff2", ".zip", ".7z",
}
_TEXT_EXTENSIONS = {".js", ".json", ".css", ".html", ".txt", ".xml", ".yaml", ".yml"}


@dataclass(frozen=True)
class ResourcePackPlan:
    enabled: bool
    estimated_apk_bytes: int
    staged_bytes: int
    file_count: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "estimatedApkBytes": self.estimated_apk_bytes,
            "stagedBytes": self.staged_bytes,
            "fileCount": self.file_count,
            "reason": self.reason,
            "apkSafePayloadBytes": APK_SAFE_PAYLOAD_BYTES,
        }


@dataclass(frozen=True)
class ResourcePackArtifact:
    path: Path
    file_name: str
    sha256: str
    pack_bytes: int
    source_bytes: int
    file_count: int
    project_id: str
    source_snapshot_sha256: str | None
    device_relative_path: str

    def config_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": RESOURCE_PACK_SCHEMA_VERSION,
            "fileName": self.file_name,
            "projectId": self.project_id,
            "packSha256": self.sha256,
            "packBytes": self.pack_bytes,
            "sourceBytes": self.source_bytes,
            "fileCount": self.file_count,
            "sourceSnapshotSha256": self.source_snapshot_sha256,
            "deviceRelativePath": self.device_relative_path,
            "entryRoot": "www",
            "startPath": "index.html",
        }


def _iter_files(www_root: Path):
    root = www_root.resolve(strict=True)
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        lowered = relative.casefold()
        # Saves are never valid input to an APK or an external resource pack.
        if lowered.startswith("save/") or lowered.endswith(".rpgsave"):
            continue
        if path.is_symlink():
            raise ValueError(f"staged asset is a symlink: {relative}")
        yield path, relative


def plan_resource_pack(www_root: str | Path) -> ResourcePackPlan:
    staged = Path(www_root).resolve(strict=True)
    total = 0
    estimate = 220 * 1024 * 1024  # runtime, manifest and ZIP directory margin
    count = 0
    for path, _relative in _iter_files(staged):
        size = path.stat().st_size
        total += size
        count += 1
        suffix = path.suffix.casefold()
        if suffix in _STORED_EXTENSIONS:
            estimate += size
        elif suffix in _TEXT_EXTENSIONS:
            # Text compresses well, but retain a deliberately conservative
            # bound so a project with unusual data does not hit Zip32 later.
            estimate += max(256, math.ceil(size * 0.75))
        else:
            estimate += size
    enabled = estimate >= APK_SAFE_PAYLOAD_BYTES
    reason = (
        "estimated APK payload reaches the ZIP32 safety limit"
        if enabled else "estimated APK payload is below the ZIP32 safety limit"
    )
    return ResourcePackPlan(enabled, estimate, total, count, reason)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def create_resource_pack(
    www_root: str | Path,
    output_path: str | Path,
    *,
    project_id: str,
    source_snapshot_sha256: str | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> ResourcePackArtifact:
    """Create a ZIP64 archive whose entries are rooted at ``www/``.

    Images/audio are stored because they are already compressed; text is
    deflated.  ``zipfile`` streams each file and does not load the game into
    memory, which is important for multi-gigabyte projects.
    """

    root = Path(www_root).resolve(strict=True)
    destination = Path(output_path).resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = list(_iter_files(root))
    source_bytes = sum(path.stat().st_size for path, _ in files)
    manifest = {
        "schemaVersion": RESOURCE_PACK_SCHEMA_VERSION,
        "projectId": project_id,
        "sourceBytes": source_bytes,
        "fileCount": len(files),
        "sourceSnapshotSha256": source_snapshot_sha256,
        "entryRoot": "www",
    }
    processed = 0
    with zipfile.ZipFile(destination, "w", allowZip64=True) as archive:
        for path, relative in files:
            suffix = path.suffix.casefold()
            compression = zipfile.ZIP_STORED if suffix in _STORED_EXTENSIONS else zipfile.ZIP_DEFLATED
            archive.write(path, f"www/{relative}", compress_type=compression)
            processed += 1
            if progress is not None and (processed == len(files) or processed % 256 == 0):
                progress(processed, len(files), f"packing external resources: {processed}/{len(files)}")
        archive.writestr(
            "game2apk-resource.json",
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"),
            compress_type=zipfile.ZIP_DEFLATED,
        )
    pack_sha256 = _sha256_file(destination)
    return ResourcePackArtifact(
        path=destination,
        file_name=destination.name,
        sha256=pack_sha256,
        pack_bytes=destination.stat().st_size,
        source_bytes=source_bytes,
        file_count=len(files),
        project_id=project_id,
        source_snapshot_sha256=source_snapshot_sha256,
        device_relative_path=f"game2apk/{destination.name}",
    )


def write_pack_config(path: str | Path, artifact: ResourcePackArtifact) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(artifact.config_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    destination.write_text(payload, encoding="utf-8")
    return destination
