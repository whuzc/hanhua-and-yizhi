"""Static APK acceptance checks and optional adb install -r verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any

from .builder import AsciiPathMapper
from .errors import ExternalToolError
from .models import ToolchainInfo, VerificationReport
from .security import atomic_write_json, now_utc, redact_text, require_within


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str]) -> tuple[int, str]:
    if command and command[0].casefold().endswith(".bat"):
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", *command]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False)
    except OSError as exc:
        return -1, redact_text(exc)
    return completed.returncode, redact_text(completed.stdout + completed.stderr)


def _parse_badging(text: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"raw": text[-4000:]}
    match = re.search(r"package:\s+name='([^']+)'\s+versionCode='([^']+)'\s+versionName='([^']*)'", text)
    if match:
        metadata.update({"applicationId": match.group(1), "versionCode": match.group(2), "versionName": match.group(3)})
    label = re.search(r"application-label(?:-[^:]+)?:'([^']*)'", text)
    if label:
        metadata["label"] = label.group(1)
    icon = re.search(r"(?:^|\s)icon='([^']*)'", text)
    if icon:
        metadata["icon"] = icon.group(1)
    icon_by_density = re.search(r"application-icon-[^:]+:'([^']*)'", text)
    if icon_by_density and not metadata.get("icon"):
        metadata["icon"] = icon_by_density.group(1)
    metadata["debuggable"] = "application-debuggable" in text or bool(re.search(r"debuggable\s*[:=]\s*true", text, re.I))
    metadata["debuggableChecked"] = "application-debuggable" in text or bool(re.search(r"debuggable\s*[:=]\s*(?:true|false)", text, re.I))
    return metadata


def _critical_assets(apk: Path) -> dict[str, Any]:
    required = ["assets/www/index.html", "assets/www/js/rpg_core.js", "assets/www/js/game2apk-input.js"]
    try:
        with zipfile.ZipFile(apk) as archive:
            names = set(archive.namelist())
            config_candidates = ["assets/game2apk/config.json", "assets/game2apk-config.json", "assets/www/game2apk-config.json"]
            missing = [name for name in required if name not in names]
            config_present = next((name for name in config_candidates if name in names), None)
            if not config_present:
                missing.append("assets/game2apk/config.json")
            save_entries = [name for name in names if name.startswith("assets/www/save/") or name.casefold().endswith(".rpgsave")]
            resource_entries = [name for name in names if name.startswith("assets/www/")]
            return {
                "passed": not missing and not save_entries,
                "assetCount": len(resource_entries),
                "missing": missing,
                "saveEntries": sorted(save_entries)[:20],
                "config": config_present,
                "required": required,
            }
    except (OSError, zipfile.BadZipFile) as exc:
        return {"passed": False, "assetCount": 0, "missing": required, "error": redact_text(exc), "saveEntries": []}


def _normalize_zip_name(name: str) -> str:
    """Repair Java/Windows ZIP names written as UTF-8 bytes without the flag."""
    try:
        repaired = name.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name
    return repaired if repaired.startswith("assets/") else name


def _stage_asset_check(apk: Path, manifest_path: str | Path | None) -> dict[str, Any]:
    if not manifest_path:
        return {"checked": False, "passed": True, "reason": "stage manifest not supplied"}
    manifest = Path(manifest_path).resolve(strict=False)
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        copied = data.get("copiedFiles")
        if not isinstance(copied, list):
            raise ValueError("copiedFiles is not an array")
        expected: dict[str, dict[str, Any]] = {}
        expected_collisions: dict[str, list[str]] = {}
        for item in copied:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError("copiedFiles contains an invalid entry")
            relative = item["path"].replace("\\", "/").lstrip("/")
            if not relative or relative.startswith("../") or "/../" in relative:
                raise ValueError("copiedFiles contains an unsafe path")
            normalized = _normalize_zip_name(f"assets/www/{relative}")
            if normalized in expected:
                expected_collisions.setdefault(normalized, [str(expected[normalized].get("path", ""))])
                expected_collisions[normalized].append(relative)
            else:
                expected[normalized] = item
        generated = {"assets/www/js/game2apk-input.js", "assets/www/game2apk-config.json"}
        # Patcher injects the input bridge in index.html and rewrites MV's
        # encrypted-audio extension selector in rpg_managers.js.  Both are
        # intentional, auditable staged mutations; all other copied assets
        # must still match the source manifest byte-for-byte.
        modified = {"assets/www/index.html", "assets/www/js/rpg_managers.js"}
        with zipfile.ZipFile(apk) as archive:
            actual_to_raw: dict[str, str] = {}
            repaired_names: list[str] = []
            actual_collisions: dict[str, list[str]] = {}
            for raw_name in archive.namelist():
                if raw_name.startswith("assets/www/") and not raw_name.endswith("/"):
                    normalized = _normalize_zip_name(raw_name)
                    if normalized in actual_to_raw:
                        actual_collisions.setdefault(normalized, [actual_to_raw[normalized]]).append(raw_name)
                    actual_to_raw[normalized] = raw_name
                    if normalized != raw_name:
                        repaired_names.append(raw_name)
            actual = set(actual_to_raw)
            missing = sorted(set(expected) - actual)
            unexpected = sorted(actual - set(expected) - generated)
            hash_mismatches: list[str] = []
            for name, item in expected.items():
                if name in missing or name in modified:
                    continue
                expected_hash = item.get("sha256")
                if not isinstance(expected_hash, str):
                    continue
                with archive.open(actual_to_raw[name]) as handle:
                    digest = hashlib.sha256()
                    while chunk := handle.read(1024 * 1024):
                        digest.update(chunk)
                    digest = digest.hexdigest()
                if digest.casefold() != expected_hash.casefold():
                    hash_mismatches.append(name)
        collision_names = sorted(set(expected_collisions) | set(actual_collisions))
        return {
            "checked": True,
            "passed": not missing and not unexpected and not hash_mismatches
            and not expected_collisions and not actual_collisions,
            "manifestPath": str(manifest),
            "expectedCount": len(expected),
            "actualCount": len(actual),
            "generated": sorted(generated & actual),
            "missing": missing,
            "unexpected": unexpected,
            "hashMismatches": hash_mismatches,
            "modifiedAllowed": sorted(modified & actual),
            "zipNameRepairCount": len(repaired_names),
            "normalizedNameCollisions": [
                {
                    "normalized": name,
                    "rawNames": sorted(set(expected_collisions.get(name, []) + actual_collisions.get(name, []))),
                }
                for name in collision_names
            ],
            "expectedNameCollisions": [
                {"normalized": name, "rawNames": names}
                for name, names in sorted(expected_collisions.items())
            ],
            "actualNameCollisions": [
                {"normalized": name, "rawNames": names}
                for name, names in sorted(actual_collisions.items())
            ],
        }
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        return {"checked": True, "passed": False, "manifestPath": str(manifest), "error": redact_text(exc)}


class VerificationService:
    def __init__(self, progress=None):
        self.progress = progress or (lambda *_args, **_kwargs: None)

    def verify(
        self,
        apk_path: str | Path,
        toolchain: ToolchainInfo | None = None,
        build_started_at: str | None = None,
        expected_application_id: str | None = None,
        expected_version_code: int | None = None,
        install: bool = False,
        report_path: str | Path | None = None,
        stage_manifest_path: str | Path | None = None,
    ) -> VerificationReport:
        apk = Path(apk_path).resolve(strict=True)
        build_start_epoch = None
        if build_started_at:
            try:
                build_start_epoch = datetime.fromisoformat(build_started_at.replace("Z", "+00:00")).timestamp()
            except ValueError:
                build_start_epoch = None
        fresh = build_start_epoch is None or apk.stat().st_mtime >= build_start_epoch
        digest = _sha256_file(apk)
        self.progress("verify", 0.15, "checking APK ZIP assets")
        assets = _critical_assets(apk)
        stage_assets = _stage_asset_check(apk, stage_manifest_path)
        toolchain = toolchain or ToolchainInfo(None, None, None, None, None, None, None, None)
        mapper = None
        if stage_manifest_path:
            manifest_path = Path(stage_manifest_path).resolve(strict=False)
            project_dir = manifest_path.parents[2] if len(manifest_path.parents) > 2 else None
            if project_dir and project_dir.name and apk.is_relative_to(project_dir):
                mapper = AsciiPathMapper(project_dir, project_dir.name)
        with (mapper or nullcontext()) as path_mapper:
            mapped_apk = path_mapper.mapped_path(apk) if path_mapper and path_mapper.active else apk
            aapt_tool = toolchain.aapt or toolchain.aapt2
            aapt: dict[str, Any] = {"available": bool(aapt_tool), "passed": False, "tool": aapt_tool}
            if aapt_tool:
                code, output = _run([aapt_tool, "dump", "badging", str(mapped_apk)])
                aapt.update({"returnCode": code, "output": output[-4000:], "passed": code == 0})
                metadata = _parse_badging(output)
                metadata["debuggableChecked"] = code == 0
                metadata["minSdk"] = re.search(r"sdkVersion:'([^']+)'", output).group(1) if re.search(r"sdkVersion:'([^']+)'", output) else None
                metadata["targetSdk"] = re.search(r"targetSdkVersion:'([^']+)'", output).group(1) if re.search(r"targetSdkVersion:'([^']+)'", output) else None
            else:
                metadata = {"debuggable": None, "debuggableChecked": False}
            if expected_application_id and metadata.get("applicationId"):
                metadata["applicationIdMatches"] = metadata["applicationId"] == expected_application_id
            elif expected_application_id:
                metadata["applicationIdMatches"] = False
            if expected_version_code is not None and metadata.get("versionCode") is not None:
                metadata["versionCodeMatches"] = str(metadata["versionCode"]) == str(expected_version_code)
            elif expected_version_code is not None:
                metadata["versionCodeMatches"] = False

            self.progress("verify", 0.28, "checking APK permissions")
            permissions_tool = toolchain.aapt or toolchain.aapt2
            permissions: dict[str, Any] = {"available": bool(permissions_tool), "passed": False, "tool": permissions_tool}
            if permissions_tool:
                code, output = _run([permissions_tool, "dump", "permissions", str(mapped_apk)])
                has_internet = bool(re.search(r"android\.permission\.INTERNET", output, re.I))
                permissions.update({
                    "returnCode": code,
                    "output": output[-4000:],
                    "internet": has_internet,
                    "passed": code == 0 and not has_internet,
                })

            self.progress("verify", 0.4, "checking ZIP alignment")
            zipalign: dict[str, Any] = {"available": bool(toolchain.zipalign), "passed": False}
            if toolchain.zipalign:
                code, output = _run([toolchain.zipalign, "-c", "-v", "4", str(mapped_apk)])
                zipalign.update({"returnCode": code, "output": output[-4000:], "passed": code == 0})
            self.progress("verify", 0.65, "checking release certificate")
            apksigner: dict[str, Any] = {"available": bool(toolchain.apksigner), "passed": False}
            if toolchain.apksigner:
                code, output = _run([toolchain.apksigner, "verify", "--verbose", "--print-certs", str(mapped_apk)])
                fingerprint = re.search(r"certificate SHA-256 digest:\s*([0-9A-Fa-f:]+)", output)
                apksigner.update(
                    {
                        "returnCode": code,
                        "output": output[-4000:],
                        "passed": code == 0,
                        "certificateSha256": fingerprint.group(1) if fingerprint else None,
                    }
                )

            device: dict[str, Any] = {"requested": install, "verified": False, "checked": False, "reason": "adb not checked"}
            adb = toolchain.adb
            if not adb:
                device["reason"] = "adb unavailable; no device verification"
            else:
                code, devices = _run([adb, "devices"])
                connected = [line for line in devices.splitlines()[1:] if line.strip().endswith("\tdevice")]
                device.update({"checked": True, "adbReturnCode": code, "connectedCount": len(connected)})
                if code != 0 or not connected:
                    device["reason"] = "no Android device or emulator available"
                elif install:
                    install_code, install_output = _run([adb, "install", "-r", str(mapped_apk)])
                    device.update({"returnCode": install_code, "output": install_output[-4000:], "verified": install_code == 0, "reason": "adb install -r completed" if install_code == 0 else "adb install -r failed"})
                else:
                    device["reason"] = "device detected; install not requested"
        metadata_requirements = bool(metadata.get("debuggableChecked")) and metadata.get("debuggable") is False
        metadata_requirements = metadata_requirements and bool(metadata.get("icon"))
        if expected_application_id is not None:
            metadata_requirements = metadata_requirements and metadata.get("applicationIdMatches", False)
        if expected_version_code is not None:
            metadata_requirements = metadata_requirements and metadata.get("versionCodeMatches", False)
        passed = bool(
            fresh
            and assets.get("passed")
            and stage_assets.get("passed", True)
            and permissions.get("passed")
            and aapt.get("passed")
            and zipalign.get("passed")
            and apksigner.get("passed")
            and metadata_requirements
        )
        report = VerificationReport(
            apk_path=str(apk),
            sha256=digest,
            file_size=apk.stat().st_size,
            fresh=fresh,
            metadata=metadata,
            critical_assets=assets,
            stage_assets=stage_assets,
            permissions=permissions,
            zipalign=zipalign,
            apksigner=apksigner,
            aapt=aapt,
            device=device,
            passed=passed,
            signature_candidate=passed,
        )
        if report_path:
            report.report_path = str(atomic_write_json(report_path, {**report.to_dict(), "generatedAtUtc": now_utc()}))
        self.progress("verify", 1.0, "verification complete")
        return report

    @staticmethod
    def promote(report: VerificationReport, dist_dir: str | Path, filename: str | None = None) -> Path:
        if not report.signature_candidate:
            raise ExternalToolError("APK is not a signature candidate; refusing to copy it to dist")
        destination_dir = Path(dist_dir).resolve(strict=False)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / (filename or Path(report.apk_path).name)
        shutil.copy2(report.apk_path, destination)
        return destination
