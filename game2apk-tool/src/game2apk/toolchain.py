"""Desktop-release toolchain discovery and explicit, user-approved installers.

The portable GUI deliberately ships only the versioned Gradle/Android template.
Android SDK/JDK files are discovered from the machine or installed into a user
selected directory.  Configuration is kept below the user's profile, never in
the checkout or a portable bundle.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .builder import discover_toolchain
from .models import ToolchainInfo


CONFIG_FILE_NAME = "toolchain.json"
MAX_DOWNLOAD_BYTES = 1_500_000_000

# These are official vendor endpoints.  The GUI still asks for confirmation
# immediately before starting a download; merely opening the app never fetches.
COMPONENTS: dict[str, dict[str, str]] = {
    "android_cmdline_tools": {
        "label": "Android Command-line Tools",
        "url": "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip",
        "host": "dl.google.com",
    },
    "temurin_jdk17": {
        "label": "Eclipse Temurin JDK 17",
        "url": "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse",
        "host": "api.adoptium.net",
    },
}
# Adoptium's official API commonly redirects the binary to its signed GitHub
# release asset.  These hosts are accepted only as redirect destinations;
# users cannot select arbitrary URLs in the GUI.
ALLOWED_DOWNLOAD_HOSTS = frozenset({"dl.google.com", "api.adoptium.net", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"})


def user_config_dir() -> Path:
    """Return a profile-local directory suitable for non-secret preferences."""

    appdata = os.environ.get("APPDATA")
    root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return root / "game2apk-tool"


def config_path() -> Path:
    return user_config_dir() / CONFIG_FILE_NAME


def load_config(path: str | Path | None = None) -> dict[str, str]:
    target = Path(path) if path else config_path()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    # Only path preferences are accepted; this file is not an API-key store.
    return {key: str(value[key]) for key in ("sdk_dir", "jdk_dir", "gradle_user_home") if value.get(key)}


def save_config(values: dict[str, str], path: str | Path | None = None) -> Path:
    target = Path(path) if path else config_path()
    safe = {key: str(values[key]) for key in ("sdk_dir", "jdk_dir", "gradle_user_home") if values.get(key)}
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(safe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def discover_configured(template_dir: str | Path, path: str | Path | None = None) -> ToolchainInfo:
    """Discover using saved profile paths, then the normal environment/PATH."""

    values = load_config(path)
    # Keep Gradle's regenerable download/cache state in the user's profile;
    # the portable release never carries this directory.
    if not values.get("gradle_user_home"):
        profile_gradle = user_config_dir() / "gradle-home"
        profile_gradle.mkdir(parents=True, exist_ok=True)
        values["gradle_user_home"] = str(profile_gradle)
    return discover_toolchain(
        template_dir,
        sdk_dir=values.get("sdk_dir"),
        jdk_dir=values.get("jdk_dir"),
        gradle_user_home=values.get("gradle_user_home"),
    )


def missing_components(info: ToolchainInfo) -> list[str]:
    missing: list[str] = []
    if not info.sdk_dir:
        missing.append("Android SDK")
    if not info.jdk_dir:
        missing.append("JDK")
    if not info.aapt2:
        missing.append("aapt2")
    if not info.zipalign:
        missing.append("zipalign")
    if not info.apksigner:
        missing.append("apksigner")
    if not info.wrapper:
        missing.append("Gradle wrapper")
    return missing


def _check_component(name: str) -> dict[str, str]:
    try:
        component = COMPONENTS[name]
    except KeyError as exc:
        raise ValueError(f"unsupported toolchain component: {name}") from exc
    parsed = urllib.parse.urlparse(component["url"])
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
        raise ValueError("toolchain download URL is not an approved HTTPS vendor endpoint")
    return component


@dataclass(frozen=True)
class DownloadResult:
    component: str
    archive: Path
    extracted_to: Path


def download_component(
    component_name: str,
    destination: str | Path,
    *,
    confirm: Callable[[str], bool],
    progress: Callable[[int, int], None] | None = None,
    opener: Callable[..., object] | None = None,
) -> DownloadResult:
    """Download and safely extract an official archive after explicit consent.

    ``confirm`` is intentionally mandatory, making accidental background
    downloads impossible.  ``opener`` is injectable for unit tests.
    """

    component = _check_component(component_name)
    target = Path(destination).expanduser().resolve()
    if not confirm(f"将从 {component['host']} 下载 {component['label']} 到:\n{target}\n是否继续？"):
        raise PermissionError("toolchain download cancelled by user")
    target.mkdir(parents=True, exist_ok=True)
    opener = opener or urllib.request.urlopen
    archive = target / ("android-commandline-tools.zip" if component_name == "android_cmdline_tools" else "temurin-jdk17.zip")
    temporary = archive.with_suffix(archive.suffix + ".part")
    try:
        with opener(component["url"], timeout=30) as response, temporary.open("wb") as output:
            final_url = getattr(response, "geturl", lambda: component["url"])()
            final_host = urllib.parse.urlparse(final_url).hostname
            if final_host not in ALLOWED_DOWNLOAD_HOSTS:
                raise ValueError("toolchain download redirected to a non-approved host")
            total = int(response.headers.get("Content-Length", "0") or 0)
            written = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_DOWNLOAD_BYTES:
                    raise ValueError("download exceeds the safety size limit")
                output.write(chunk)
                if progress:
                    progress(written, total)
        os.replace(temporary, archive)
        extracted = target / ("android-sdk" if component_name == "android_cmdline_tools" else "jdk-17")
        extracted.mkdir(parents=True, exist_ok=True)
        _safe_extract(archive, extracted)
        install_root = extracted
        if component_name == "temurin_jdk17" and not (install_root / "bin" / "java.exe").is_file():
            candidates = [child for child in install_root.iterdir() if child.is_dir() and (child / "bin" / "java.exe").is_file()]
            if len(candidates) == 1:
                install_root = candidates[0]
        return DownloadResult(component_name, archive, install_root)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _safe_extract(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as zipped:
        root = destination.resolve()
        for member in zipped.infolist():
            candidate = (destination / member.filename).resolve()
            if candidate != root and root not in candidate.parents:
                raise ValueError("archive contains a path outside the selected install directory")
        zipped.extractall(destination)
