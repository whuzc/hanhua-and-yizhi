"""Android SDK/JDK/Gradle discovery and isolated template rendering."""

from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from .config import default_control_config, write_android_config
from .errors import BlockedError, CancelledError, ExternalToolError
from .models import BuildConfig, BuildResult, StageManifest, ToolchainInfo
from .resource_pack import (
    ResourcePackArtifact,
    ResourcePackPlan,
    create_resource_pack,
    plan_resource_pack,
    write_pack_config,
)
from .security import atomic_write_text, now_utc, redact_text, require_within, sanitized_child_environment


NO_COMPRESS_EXTENSIONS = ("rpgmvp", "rpgmvo", "rpgmvm", "ogg", "m4a", "mp3", "wav", "webm")
ALIYUN_GRADLE_DISTRIBUTION = "https://mirrors.aliyun.com/gradle/distributions/v8.11.1/gradle-8.11.1-bin.zip"
OFFICIAL_GRADLE_DISTRIBUTION = "https://services.gradle.org/distributions/gradle-8.11.1-bin.zip"


def _has_non_ascii(path: str | Path) -> bool:
    return any(ord(character) > 127 for character in str(path))


def _subst_executable() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return str(Path(system_root) / "System32" / "subst.exe")


def _run_subst(command: list[str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False)
        return completed.returncode, completed.stdout + completed.stderr
    except OSError as exc:
        return -1, str(exc)


class AsciiPathMapper:
    """Map a marked project work directory to an ASCII drive for Gradle."""

    CANDIDATE_DRIVES = tuple("STUVWXYZQPR")

    def __init__(self, project_dir: str | Path, project_id: str, runner=None):
        self.project_dir = Path(project_dir).resolve(strict=True)
        self.project_id = project_id
        self.runner = runner or _run_subst
        self.drive: str | None = None
        self.active = False
        self._validate_target()

    def _validate_target(self) -> None:
        marker = self.project_dir / ".game2apk-work-marker.json"
        if not marker.is_file():
            raise BlockedError("ASCII mapping target is not marker-protected")
        try:
            import json

            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BlockedError("ASCII mapping target marker is unreadable") from exc
        if data.get("tool") != "game2apk-tool" or data.get("project_id") != self.project_id:
            raise BlockedError("ASCII mapping target marker does not match project id")
        if self.project_dir.name != self.project_id:
            raise BlockedError("ASCII mapping target is not the expected .work project directory")

    @staticmethod
    def choose_drive(used: set[str], candidates: tuple[str, ...] = CANDIDATE_DRIVES) -> str:
        normalized = {item.rstrip(":").upper() for item in used}
        for letter in candidates:
            if letter.upper() not in normalized:
                return letter.upper()
        raise ExternalToolError("no free ASCII drive letter is available for Gradle path mapping")

    def _used_drives(self) -> set[str]:
        used: set[str] = set()
        code, output = self.runner([_subst_executable()])
        if code == 0:
            used.update(re.findall(r"\b([A-Z]):", output.upper()))
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            try:
                if Path(f"{letter}:\\").exists():
                    used.add(letter)
            except OSError:
                # A drive can exist but be inaccessible to the current user;
                # treat it as occupied rather than risk mapping over it.
                used.add(letter)
        return used

    @property
    def mapped_root(self) -> Path:
        if not self.drive:
            raise ExternalToolError("ASCII drive mapping has not been created")
        return Path(f"{self.drive}:\\")

    def mapped_path(self, physical_path: str | Path) -> Path:
        path = Path(physical_path).resolve(strict=False)
        relative = path.relative_to(self.project_dir)
        return self.mapped_root / relative

    def __enter__(self) -> "AsciiPathMapper":
        if not _has_non_ascii(self.project_dir):
            return self
        self.drive = self.choose_drive(self._used_drives())
        command = [_subst_executable(), f"{self.drive}:", str(self.project_dir)]
        code, output = self.runner(command)
        if code != 0:
            self.drive = None
            raise ExternalToolError(f"subst mapping failed with exit code {code}: {redact_text(output)}")
        self.active = True
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if not self.active or not self.drive:
            return
        command = [_subst_executable(), f"{self.drive}:", "/D"]
        code, output = self.runner(command)
        self.active = False
        self.drive = None
        if code != 0 and exc_value is None:
            raise ExternalToolError(f"subst cleanup failed with exit code {code}: {redact_text(output)}")


def _first_existing(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.is_dir()), None)


def _tool_in(path: Path | None, name: str) -> str | None:
    if path:
        for candidate in (path / name, path / f"{name}.exe", path / f"{name}.bat"):
            if candidate.is_file():
                return str(candidate)
    return shutil.which(name)


def discover_toolchain(
    template_dir: str | Path | None = None,
    sdk_dir: str | Path | None = None,
    jdk_dir: str | Path | None = None,
    gradle_user_home: str | Path | None = None,
) -> ToolchainInfo:
    sdk_candidates = [
        Path(sdk_dir) if sdk_dir else Path(""),
        Path(os.environ["ANDROID_SDK_ROOT"]) if os.environ.get("ANDROID_SDK_ROOT") else Path(""),
        Path(os.environ["ANDROID_HOME"]) if os.environ.get("ANDROID_HOME") else Path(""),
        Path(r"F:\AndroidDev\android-sdk"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk",
    ]
    sdk_candidates = [path for path in sdk_candidates if str(path) not in {"", "."}]
    sdk = _first_existing(sdk_candidates)
    jdk_candidates = [
        Path(jdk_dir) if jdk_dir else Path(""),
        Path(os.environ["JAVA_HOME"]) if os.environ.get("JAVA_HOME") else Path(""),
    ]
    jdk_candidates = [path for path in jdk_candidates if str(path) not in {"", "."}]
    jdk = _first_existing(jdk_candidates)
    if jdk is None:
        java = shutil.which("java")
        if java:
            jdk = Path(java).resolve().parent.parent
    gradle_home_candidates = [
        Path(gradle_user_home) if gradle_user_home else Path(""),
        Path(os.environ["GRADLE_USER_HOME"]) if os.environ.get("GRADLE_USER_HOME") else Path(""),
        Path(r"F:\AndroidDev\gradle-home"),
        Path.home() / ".gradle",
    ]
    gradle_home_candidates = [path for path in gradle_home_candidates if str(path) not in {"", "."}]
    gradle_home = _first_existing(gradle_home_candidates)
    wrapper = None
    if template_dir:
        template = Path(template_dir)
        for candidate in (template / "gradlew.bat", template / "gradlew"):
            if candidate.is_file():
                wrapper = str(candidate.resolve())
                break
    if wrapper is None:
        wrapper = shutil.which("gradle")

    build_tools = sdk / "build-tools" if sdk else None
    versions = sorted([path for path in build_tools.iterdir() if path.is_dir()], key=lambda p: p.name, reverse=True) if build_tools and build_tools.is_dir() else []
    build_tools_dir = versions[0] if versions else None
    info = ToolchainInfo(
        sdk_dir=str(sdk) if sdk else None,
        jdk_dir=str(jdk) if jdk else None,
        gradle_user_home=str(gradle_home) if gradle_home else None,
        wrapper=wrapper,
        aapt2=_tool_in(build_tools_dir, "aapt2"),
        zipalign=_tool_in(build_tools_dir, "zipalign"),
        apksigner=_tool_in(build_tools_dir, "apksigner"),
        adb=_tool_in(sdk / "platform-tools" if sdk else None, "adb"),
        aapt=_tool_in(build_tools_dir, "aapt"),
    )
    if not info.sdk_dir:
        info.issues.append("Android SDK not found; checked F:\\AndroidDev\\android-sdk and configured environment")
    if not info.jdk_dir:
        info.issues.append("JDK not found; configure JAVA_HOME or pass jdk_dir")
    if not info.gradle_user_home:
        info.issues.append("Gradle cache not found; checked F:\\AndroidDev\\gradle-home and configured environment")
    if not info.wrapper:
        info.issues.append("gradlew.bat/gradle not found in the versioned template or PATH")
    for name in ("aapt2", "zipalign", "apksigner"):
        if not getattr(info, name):
            info.issues.append(f"Android build tool missing: {name}")
    return info


def _replace_text(path: Path, replacements: list[tuple[str, str]]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    original = text
    for old, new in replacements:
        text = text.replace(old, new)
    if text != original:
        atomic_write_text(path, text)


def _render_template(android_dir: Path, config: BuildConfig) -> None:
    config_file = android_dir / "app" / "src" / "main" / "assets" / "game2apk" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    control = config.control_config or default_control_config()
    write_android_config(
        config_file,
        {
            "schemaVersion": 1,
            "appName": config.app_name,
            "applicationId": config.application_id,
            "versionCode": config.version_code,
            "versionName": config.version_name,
            "control": control,
        },
    )
    gradle_files = list(android_dir.rglob("*.gradle")) + list(android_dir.rglob("*.gradle.kts"))
    for path in gradle_files:
        _replace_text(
            path,
            [
                ("@@APPLICATION_ID@@", config.application_id),
                ("@@VERSION_CODE@@", str(config.version_code)),
                ("@@VERSION_NAME@@", config.version_name),
                ("@@APP_NAME@@", config.app_name),
                ("@@NO_COMPRESS_EXTENSIONS@@", ", ".join(f"'{extension}'" for extension in NO_COMPRESS_EXTENSIONS)),
            ],
        )
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "applicationId" in text:
            text = re.sub(r'(applicationId\s*[= ]\s*[\"\'])[a-zA-Z0-9_.-]+([\"\'])', rf"\g<1>{config.application_id}\g<2>", text)
        text = re.sub(r"(versionCode\s+)[0-9]+", rf"\g<1>{config.version_code}", text)
        text = re.sub(r"(versionName\s+[\"']).*?([\"'])", rf"\g<1>{config.version_name}\g<2>", text)
        text = re.sub(r"debuggable\s+true", "debuggable false", text, flags=re.I)
        if path.parent.name == "app" and not all(extension in text for extension in NO_COMPRESS_EXTENSIONS):
            text += "\n// game2apk-tool large RPGMV assets\nandroid { androidResources { noCompress += [" + ", ".join(repr(extension) for extension in NO_COMPRESS_EXTENSIONS) + "] } }\n"
        atomic_write_text(path, text)

    for path in android_dir.rglob("strings.xml"):
        _replace_text(path, [("@@APP_NAME@@", xml_escape(config.app_name))])
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        text = re.sub(r'(<string\s+name=["\']app_name["\'][^>]*>).*?(</string>)', rf"\g<1>{xml_escape(config.app_name)}\g<2>", text, flags=re.S)
        atomic_write_text(path, text)
    for path in android_dir.rglob("AndroidManifest.xml"):
        _replace_text(path, [("@@APPLICATION_ID@@", config.application_id), ("@@APP_NAME@@", xml_escape(config.app_name))])
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        text = re.sub(r'android:debuggable\s*=\s*["\']true["\']', 'android:debuggable="false"', text, flags=re.I)
        atomic_write_text(path, text)

    if config.icon_path:
        icon = Path(config.icon_path).expanduser().resolve(strict=True)
        if not icon.is_file():
            raise BlockedError(f"configured icon is not a file: {icon}")
        if icon.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise BlockedError("icon must be a PNG, JPEG or WebP image")
        drawable = android_dir / "app" / "src" / "main" / "res" / "drawable"
        drawable.mkdir(parents=True, exist_ok=True)
        destination = drawable / f"game2apk_icon{icon.suffix.casefold()}"
        shutil.copy2(icon, destination)
        manifest_path = android_dir / "app" / "src" / "main" / "AndroidManifest.xml"
        manifest = manifest_path.read_text(encoding="utf-8")
        icon_attributes = ("icon", "roundIcon")
        for attribute in icon_attributes:
            pattern = rf"android:{attribute}\s*=\s*[\"'][^\"']*[\"']"
            if re.search(pattern, manifest, flags=re.I):
                manifest = re.sub(
                    pattern,
                    f'android:{attribute}="@drawable/game2apk_icon"',
                    manifest,
                    count=1,
                    flags=re.I,
                )
        if not re.search(r"android:icon\s*=", manifest, flags=re.I):
            application = re.search(r"<application\b[^>]*>", manifest, flags=re.I)
            if not application:
                raise BlockedError("AndroidManifest.xml has no application element for icon injection")
            opening = application.group(0)
            replacement = opening[:-1] + ' android:icon="@drawable/game2apk_icon">'
            manifest = manifest[: application.start()] + replacement + manifest[application.end() :]
        atomic_write_text(manifest_path, manifest)


class BuildService:
    def __init__(self, progress=None, cancel_event=None, runner=None, mapping_runner=None, mapper_factory=None):
        self.progress = progress or (lambda *_args, **_kwargs: None)
        self.cancel_event = cancel_event
        self.runner = runner
        self.mapping_runner = mapping_runner
        self.mapper_factory = mapper_factory or (lambda project_dir, project_id: AsciiPathMapper(project_dir, project_id, runner=self.mapping_runner))
        self.resource_pack_plan: ResourcePackPlan | None = None
        self.resource_pack_artifact: ResourcePackArtifact | None = None

    @staticmethod
    def _validate_stage_for_build(stage: StageManifest) -> tuple[Path, Path, Path]:
        """Validate the complete generated path before any delete or overwrite."""

        if stage.schema_version != 1 or not stage.source_unchanged:
            raise BlockedError("stage manifest is not an accepted schema-1, source-unchanged result")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", stage.project_id):
            raise BlockedError("stage manifest has an invalid project id")
        staged_raw = Path(stage.staged_www).expanduser()
        if staged_raw.is_symlink():
            raise BlockedError("staged www must not be a symlink")
        staged_www = staged_raw.resolve(strict=True)
        if not staged_www.is_dir() or staged_www.name.casefold() != "www":
            raise BlockedError("staged www does not have the required directory shape")
        staged_dir = staged_www.parent
        run_dir = staged_dir.parent
        runs_dir = run_dir.parent
        project_dir = runs_dir.parent
        work_base = project_dir.parent
        if staged_dir.name.casefold() != "staged" or runs_dir.name.casefold() != "runs":
            raise BlockedError("staged www must be .work/<project-id>/runs/<run-id>/staged/www")
        if work_base.name.casefold() != ".work" or project_dir.name != stage.project_id:
            raise BlockedError("staged www is outside the expected .work project boundary")
        if not re.fullmatch(r"[0-9a-f]{32}", run_dir.name):
            raise BlockedError("staged www has an invalid run id")
        if stage.run_id is not None and stage.run_id != run_dir.name:
            raise BlockedError("stage manifest run id does not match its path")

        marker_path = project_dir / ".game2apk-work-marker.json"
        if not marker_path.is_file():
            raise BlockedError("staged project marker is missing")
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BlockedError("staged project marker is unreadable") from exc
        if marker.get("tool") != "game2apk-tool" or marker.get("project_id") != stage.project_id:
            raise BlockedError("staged project marker does not match project id")

        if not stage.manifest_path:
            raise BlockedError("stage manifest path is required for a build")
        manifest_raw = Path(stage.manifest_path).expanduser()
        if manifest_raw.is_symlink():
            raise BlockedError("stage manifest must not be a symlink")
        manifest_path = manifest_raw.resolve(strict=True)
        expected_manifest = run_dir / "stage-manifest.json"
        if manifest_path != expected_manifest or not manifest_path.is_file():
            raise BlockedError("stage manifest is not owned by the staged run")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BlockedError("stage manifest is unreadable") from exc
        if not isinstance(manifest, dict):
            raise BlockedError("stage manifest must be a JSON object")
        if manifest.get("projectId") != stage.project_id or manifest.get("runId") != run_dir.name:
            raise BlockedError("stage manifest project/run ownership does not match its path")
        try:
            manifest_staged = Path(str(manifest["stagedWww"])).resolve(strict=True)
            manifest_root = Path(str(manifest["sourceRoot"])).resolve(strict=False)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise BlockedError("stage manifest has invalid path fields") from exc
        if manifest_staged != staged_www or manifest_root != Path(stage.source_root).resolve(strict=False):
            raise BlockedError("stage manifest path fields do not match the supplied manifest")
        if manifest.get("manifestPath") != str(manifest_path):
            raise BlockedError("stage manifest does not self-identify its owning run")
        marker_source = marker.get("source_root")
        if marker_source and Path(str(marker_source)).resolve(strict=False) != Path(stage.source_root).resolve(strict=False):
            raise BlockedError("staged project marker source root does not match the manifest")

        android_dir = run_dir / "android"
        require_within(android_dir, run_dir, "generated Android work directory")
        if android_dir.is_symlink():
            raise BlockedError("generated Android work directory must not be a symlink")
        return staged_www, run_dir, android_dir

    def prepare_template(self, template_dir: str | Path, stage: StageManifest, config: BuildConfig) -> Path:
        template = Path(template_dir).resolve(strict=True)
        lowered = str(template).casefold().replace("/", "\\")
        if "仙肴圣餐超魔改 ver22\\android" in lowered or template.name.casefold() == "android" and "templates" not in lowered:
            raise BlockedError("the old game's android failure sample is not an allowed template")
        staged_www, run_dir, android_dir = self._validate_stage_for_build(stage)
        if android_dir.exists():
            shutil.rmtree(android_dir)
        shutil.copytree(template, android_dir, ignore=self._ignore_template_artifacts)
        assets_www = android_dir / "app" / "src" / "main" / "assets" / "www"
        if assets_www.is_symlink():
            raise BlockedError("template assets/www must not be a symlink")
        if assets_www.exists():
            shutil.rmtree(assets_www)
        assets_www.parent.mkdir(parents=True, exist_ok=True)
        self.resource_pack_plan = plan_resource_pack(staged_www)
        self.resource_pack_artifact = None
        if self.resource_pack_plan.enabled:
            # Keep only the tiny runtime fixture in the APK.  The actual MV
            # www tree is written to a ZIP64 archive and served by the
            # Android WebView from the app-specific external files directory.
            template_www = Path(template_dir).resolve(strict=True) / "app" / "src" / "main" / "assets" / "www"
            if template_www.is_dir():
                shutil.copytree(template_www, assets_www)
            else:
                assets_www.mkdir(parents=True, exist_ok=True)
            pack_stem = re.sub(
                r"[^0-9A-Za-z\u3400-\u9fff_-]+",
                "-",
                config.app_name,
            ).strip("-") or config.application_id
            pack_version = re.sub(r"[^0-9A-Za-z._-]+", "-", config.version_name).strip("-") or "version"
            pack_path = run_dir / "resource-pack" / f"{pack_stem}-{pack_version}-resources.g2ares"
            self.progress(
                "build",
                0.12,
                "project exceeds the single-APK ZIP32 limit; creating external ZIP64 resource pack",
            )

            def pack_progress(done: int, total: int, message: str) -> None:
                if self.cancel_event is not None and self.cancel_event.is_set():
                    raise CancelledError("resource pack creation cancelled")
                fraction = 0.12 + (0.06 * (float(done) / float(total) if total else 0.0))
                self.progress("build", fraction, message)

            self.resource_pack_artifact = create_resource_pack(
                staged_www,
                pack_path,
                project_id=stage.project_id,
                source_snapshot_sha256=stage.source_snapshot_sha256,
                progress=pack_progress,
            )
            write_pack_config(
                android_dir / "app" / "src" / "main" / "assets" / "game2apk" / "resource-pack.json",
                self.resource_pack_artifact,
            )
            self.progress(
                "build",
                0.19,
                f"external resource pack ready: {self.resource_pack_artifact.pack_bytes} bytes",
            )
        else:
            shutil.copytree(staged_www, assets_www)
            if (assets_www / "save").exists() or list(assets_www.rglob("*.rpgsave")):
                raise BlockedError("staged save files would enter APK assets")
            stale_pack_config = android_dir / "app" / "src" / "main" / "assets" / "game2apk" / "resource-pack.json"
            if stale_pack_config.exists():
                stale_pack_config.unlink()
        _render_template(android_dir, config)
        self.progress("build", 0.2, "versioned Android template rendered")
        return android_dir

    @staticmethod
    def _ignore_template_artifacts(directory: str, names: list[str]) -> set[str]:
        # A template checkout may contain local Gradle caches or old outputs;
        # neither is a source asset or a valid result for this build.
        ignored = {".gradle", ".gradle-home", ".gradle-user-home", "build", ".work", ".state", "dist"}
        return {
            name
            for name in names
            if name in ignored or name.casefold().endswith((".apk", ".aab", ".jks", ".keystore"))
        }

    def _command(self, wrapper: str, config: BuildConfig | None = None) -> list[str]:
        command = [wrapper, "assembleRelease", "--no-daemon", "--stacktrace"]
        if config is not None:
            command.extend(
                [
                    f"-Pgame2apkApplicationId={config.application_id}",
                    f"-Pgame2apkVersionCode={config.version_code}",
                    f"-Pgame2apkVersionName={config.version_name}",
                ]
            )
        if wrapper.casefold().endswith(".bat"):
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", *command]
        return command

    @staticmethod
    def _wrapper_distribution_properties(wrapper: Path) -> Path | None:
        candidate = wrapper.parent / "gradle" / "wrapper" / "gradle-wrapper.properties"
        return candidate if candidate.is_file() else None

    @staticmethod
    def _mirror_download_failed(log_path: Path) -> bool:
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace").casefold()
        except OSError:
            return False
        if "mirrors.aliyun.com/gradle/distributions" not in text:
            return False
        # Do not retry the official URL for ordinary Maven resolution errors;
        # only wrapper/distribution transport failures qualify.
        markers = (
            "could not install gradle distribution",
            "could not download",
            "failed to download",
            "connection reset",
            "connection refused",
            "unknownhost",
            "timed out",
            "unable to tunnel",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _switch_to_official_distribution(properties: Path) -> bool:
        try:
            text = properties.read_text(encoding="utf-8")
        except OSError:
            return False
        escaped_mirror = ALIYUN_GRADLE_DISTRIBUTION.replace(":", r"\:")
        escaped_official = OFFICIAL_GRADLE_DISTRIBUTION.replace(":", r"\:")
        if escaped_mirror not in text and ALIYUN_GRADLE_DISTRIBUTION not in text:
            return False
        updated = text.replace(escaped_mirror, escaped_official).replace(ALIYUN_GRADLE_DISTRIBUTION, escaped_official)
        if updated == text:
            return False
        atomic_write_text(properties, updated)
        return True

    def _run_process(self, command: list[str], cwd: Path, env: dict[str, str], log_path: Path, secrets: list[str]) -> tuple[int, bool]:
        if self.runner is not None:
            result = self.runner(command, cwd, env, log_path, self.progress, self.cancel_event)
            if isinstance(result, tuple):
                return int(result[0]), bool(result[1]) if len(result) > 1 else False
            return int(result), False
        try:
            process = subprocess.Popen(command, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", shell=False)
        except OSError as exc:
            raise ExternalToolError(f"unable to start Gradle wrapper: {redact_text(exc)}") from exc
        lines: list[str] = []
        cancelled = False
        assert process.stdout is not None
        for line in process.stdout:
            if self.cancel_event is not None and self.cancel_event.is_set():
                cancelled = True
                process.terminate()
                break
            safe_line = redact_text(line.rstrip("\r\n"), secrets)
            lines.append(safe_line)
            self.progress("build", 0.5, safe_line[-240:])
        if cancelled:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        return_code = process.wait()
        atomic_write_text(log_path, "\n".join(lines) + "\n")
        return (-2 if cancelled else return_code), cancelled

    def build(
        self,
        template_dir: str | Path,
        stage: StageManifest,
        config: BuildConfig,
        toolchain: ToolchainInfo | None = None,
        api_key: str | None = None,
    ) -> BuildResult:
        self.resource_pack_plan = None
        self.resource_pack_artifact = None
        android_dir = self.prepare_template(template_dir, stage, config)
        run_dir = android_dir.parent
        if toolchain is None:
            tool_root = Path(template_dir).resolve().parents[1]
            isolated_gradle_home = tool_root / ".work" / "gradle-home"
            isolated_gradle_home.mkdir(parents=True, exist_ok=True)
            # Keep Gradle state in the tool-owned, regenerable .work cache. It
            # is writable and isolated from the user's AndroidDev cache; copying
            # transformed caches between runs is unsafe on Windows because they
            # can contain absolute and overlong paths.
            toolchain = discover_toolchain(template_dir, gradle_user_home=isolated_gradle_home)
        if toolchain.issues:
            raise ExternalToolError("toolchain validation failed: " + "; ".join(toolchain.issues))
        if not toolchain.wrapper:
            raise ExternalToolError("Gradle wrapper is missing")
        start_epoch = time.time()
        started_at = now_utc()
        project_dir = run_dir.parents[1]
        log_path = run_dir / "build.log"
        # Never pass ambient API/signing credentials to Gradle.  The API key
        # is only an in-memory redaction value for this process; Gradle has no
        # reason to receive it at all.
        env = sanitized_child_environment()
        if toolchain.gradle_user_home:
            env["GRADLE_USER_HOME"] = toolchain.gradle_user_home
        if toolchain.sdk_dir:
            env["ANDROID_SDK_ROOT"] = toolchain.sdk_dir
            env["ANDROID_HOME"] = toolchain.sdk_dir
        if toolchain.jdk_dir:
            env["JAVA_HOME"] = toolchain.jdk_dir
            env["PATH"] = str(Path(toolchain.jdk_dir) / "bin") + os.pathsep + env.get("PATH", "")
        template_root = Path(template_dir).resolve(strict=True)
        configured_wrapper = Path(toolchain.wrapper)
        if configured_wrapper.is_file():
            try:
                wrapper_relative = configured_wrapper.resolve().relative_to(template_root)
                generated_wrapper = android_dir / wrapper_relative
            except ValueError:
                generated_wrapper = configured_wrapper
        else:
            generated_wrapper = configured_wrapper
        self.progress("build", 0.3, "starting Gradle assembleRelease")
        # Gradle's worker classloader cannot reliably start from non-ASCII
        # absolute paths on Windows.  Mapping the marked project directory
        # changes only the process-visible path; source and work files stay put.
        mapper = self.mapper_factory(project_dir, stage.project_id)
        with mapper:
            mapped_android = mapper.mapped_path(android_dir) if mapper.active else android_dir
            mapped_wrapper = mapper.mapped_path(generated_wrapper) if mapper.active and generated_wrapper.is_relative_to(project_dir) else generated_wrapper
            mapped_log_path = mapper.mapped_path(log_path) if mapper.active else log_path
            command = self._command(str(mapped_wrapper), config)
            try:
                return_code, cancelled = self._run_process(command, mapped_android, env, mapped_log_path, [api_key] if api_key else [])
                wrapper_properties = self._wrapper_distribution_properties(generated_wrapper)
                if (
                    return_code != 0
                    and not cancelled
                    and wrapper_properties is not None
                    and self._mirror_download_failed(log_path)
                    and self._switch_to_official_distribution(wrapper_properties)
                ):
                    first_log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
                    self.progress("build", 0.55, "Aliyun Gradle distribution unavailable; retrying official distribution")
                    return_code, cancelled = self._run_process(command, mapped_android, env, mapped_log_path, [api_key] if api_key else [])
                    second_log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
                    atomic_write_text(
                        log_path,
                        "[game2apk] Aliyun Gradle distribution failed; retried the official distribution URL.\n"
                        + first_log
                        + "\n[game2apk] official distribution retry output\n"
                        + second_log,
                    )
            finally:
                # __exit__ is the actual cleanup, but this finally documents
                # and tests the guarantee around failures/cancellation.
                pass
        finished_at = now_utc()
        candidates = [path for path in (android_dir / "app" / "build" / "outputs" / "apk" / "release").glob("*.apk") if path.is_file() and path.stat().st_mtime >= start_epoch]
        apk = max(candidates, key=lambda path: path.stat().st_mtime) if candidates and return_code == 0 else None
        self.progress("build", 1.0, f"Gradle exited with code {return_code}")
        resource_metadata = self.resource_pack_plan.to_dict() if self.resource_pack_plan else None
        if self.resource_pack_artifact is not None:
            resource_metadata = {
                **(resource_metadata or {}),
                "mode": "external",
                **self.resource_pack_artifact.config_dict(),
            }
        elif resource_metadata is not None:
            resource_metadata = {**resource_metadata, "mode": "apk"}
        return BuildResult(
            started_at_utc=started_at,
            finished_at_utc=finished_at,
            return_code=return_code,
            command=command,
            work_dir=str(android_dir),
            apk_path=str(apk) if apk else None,
            log_path=str(log_path),
            toolchain=toolchain,
            cancelled=cancelled,
            resource_pack_path=(str(self.resource_pack_artifact.path) if self.resource_pack_artifact else None),
            resource_pack=resource_metadata,
        )
