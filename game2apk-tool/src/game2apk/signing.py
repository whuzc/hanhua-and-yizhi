"""Stable per-application signing with Windows DPAPI password protection."""

from __future__ import annotations

import ctypes
import os
import secrets
import shutil
import string
import subprocess
from ctypes import wintypes
from pathlib import Path

from .errors import ConfigurationError, ExternalToolError
from .security import now_utc, redact_text, sanitized_child_environment


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class DPAPI:
    """User-scope DPAPI.  On non-Windows hosts no password is persisted."""

    @staticmethod
    def available() -> bool:
        return os.name == "nt" and hasattr(ctypes, "windll")

    @staticmethod
    def protect(value: bytes) -> bytes:
        if not DPAPI.available():
            raise ConfigurationError("Windows DPAPI is unavailable; password persistence is disabled")
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        source_buffer = ctypes.create_string_buffer(value)
        source = _DATA_BLOB(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
        destination = _DATA_BLOB()
        if not crypt32.CryptProtectData(ctypes.byref(source), "game2apk-tool", None, None, None, 0, ctypes.byref(destination)):
            raise ConfigurationError("Windows DPAPI could not protect the signing password")
        try:
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            kernel32.LocalFree(destination.pbData)

    @staticmethod
    def unprotect(value: bytes) -> bytes:
        if not DPAPI.available():
            raise ConfigurationError("Windows DPAPI is unavailable; password persistence is disabled")
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        source_buffer = ctypes.create_string_buffer(value)
        source = _DATA_BLOB(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
        destination = _DATA_BLOB()
        if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(destination)):
            raise ConfigurationError("Windows DPAPI could not unprotect the signing password for this user")
        try:
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            kernel32.LocalFree(destination.pbData)


BACKUP_PROMPT = (
    "签名密钥已按 applicationId 长期复用。请把 keystore 和密码通过安全的离线方式备份；"
    "工具不会把密码写入 dist、APK 或日志。"
)


def _random_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits + "-_+="
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _find_keytool(jdk_dir: str | Path | None = None) -> str | None:
    candidates: list[Path] = []
    if jdk_dir:
        root = Path(jdk_dir)
        candidates.extend([root / "bin" / "keytool.exe", root / "bin" / "keytool"])
    found = shutil.which("keytool")
    if found:
        candidates.append(Path(found))
    return next((str(path) for path in candidates if path.is_file()), None)


def _exec_command(command: list[str]) -> list[str]:
    if command and command[0].casefold().endswith(".bat"):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", *command]
    return command


class SigningService:
    def __init__(self, state_root: str | Path, progress=None):
        self.state_root = Path(state_root).resolve(strict=False)
        self.progress = progress or (lambda *_args, **_kwargs: None)

    def _paths(self, application_id: str) -> tuple[Path, Path, Path]:
        if not application_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_." for char in application_id):
            raise ConfigurationError("invalid applicationId for signing state")
        directory = self.state_root / "signing" / application_id
        return directory, directory / "release.keystore", directory / "password.dpapi"

    def status(self, application_id: str) -> dict[str, object]:
        directory, keystore, password_file = self._paths(application_id)
        return {
            "applicationId": application_id,
            "directory": str(directory),
            "keystore": str(keystore),
            "keystoreExists": keystore.is_file(),
            "passwordProtection": "Windows DPAPI" if password_file.is_file() else "not persisted",
            "passwordFileExists": password_file.is_file(),
            "backupPrompt": BACKUP_PROMPT,
        }

    def _load_or_create_password(self, password_file: Path, provided_password: str | None, create: bool) -> str:
        if password_file.is_file():
            try:
                return DPAPI.unprotect(password_file.read_bytes()).decode("utf-8")
            except (OSError, UnicodeDecodeError, ConfigurationError) as exc:
                if provided_password:
                    return provided_password
                raise ConfigurationError("signing password protection file is unreadable") from exc
        if provided_password:
            password = provided_password
        elif create and DPAPI.available():
            password = _random_password()
        elif create:
            raise ConfigurationError("provide a signing password for first key creation on a host without DPAPI")
        else:
            raise ConfigurationError("existing signing key has no usable protected password")
        if DPAPI.available():
            password_file.parent.mkdir(parents=True, exist_ok=True)
            password_file.write_bytes(DPAPI.protect(password.encode("utf-8")))
        return password

    def _ensure_keystore(
        self,
        application_id: str,
        password: str | None = None,
        jdk_dir: str | Path | None = None,
        runner=None,
    ) -> tuple[dict[str, object], str]:
        directory, keystore, password_file = self._paths(application_id)
        directory.mkdir(parents=True, exist_ok=True)
        keytool = _find_keytool(jdk_dir)
        if not keytool:
            raise ExternalToolError("keytool was not found; configure a JDK before signing")
        created = False
        effective_password = self._load_or_create_password(password_file, password, create=not keystore.exists())
        if not keystore.exists():
            alias = "game2apk"
            command = [
                keytool,
                "-genkeypair",
                "-v",
                "-keystore",
                str(keystore),
                "-storetype",
                "JKS",
                "-storepass:env",
                "GAME2APK_KEYTOOL_PASSWORD",
                "-keypass:env",
                "GAME2APK_KEYTOOL_PASSWORD",
                "-alias",
                alias,
                "-keyalg",
                "RSA",
                "-keysize",
                "2048",
                "-validity",
                "10000",
                "-dname",
                f"CN={application_id}, OU=game2apk-tool",
            ]
            self.progress("signing", 0.2, "generating stable application key")
            if runner is None:
                child_env = sanitized_child_environment()
                child_env["GAME2APK_KEYTOOL_PASSWORD"] = effective_password
                completed = subprocess.run(_exec_command(command), capture_output=True, text=True, shell=False, env=child_env)
                output = completed.stdout + completed.stderr
                return_code = completed.returncode
                del child_env["GAME2APK_KEYTOOL_PASSWORD"]
            else:
                return_code, output = runner(command)
            if return_code != 0 or not keystore.is_file():
                raise ExternalToolError(
                    f"keytool failed with exit code {return_code}: {redact_text(output, [effective_password])}"
                )
            created = True
        self.progress("signing", 1.0, "stable signing key ready")
        return ({
            "applicationId": application_id,
            "keystore": str(keystore),
            "alias": "game2apk",
            "created": created,
            "backupPrompt": BACKUP_PROMPT,
            "createdAtUtc": now_utc(),
        }, effective_password)

    def ensure_keystore(
        self,
        application_id: str,
        password: str | None = None,
        jdk_dir: str | Path | None = None,
        runner=None,
    ) -> dict[str, object]:
        """Ensure the stable key exists without returning its password."""

        state, _password = self._ensure_keystore(
            application_id,
            password=password,
            jdk_dir=jdk_dir,
            runner=runner,
        )
        return state

    def sign_apk(
        self,
        apk_path: str | Path,
        application_id: str,
        password: str | None = None,
        apksigner: str | Path | None = None,
        jdk_dir: str | Path | None = None,
        runner=None,
        input_role: str = "APK input for signing",
    ) -> dict[str, object]:
        apk = Path(apk_path).resolve(strict=True)
        state, effective_password = self._ensure_keystore(
            application_id,
            password=password,
            jdk_dir=jdk_dir,
            runner=runner,
        )
        signer = str(apksigner) if apksigner else shutil.which("apksigner")
        if not signer:
            raise ExternalToolError("apksigner was not found; configure Android build-tools before signing")
        command = [signer, "sign", "--ks", str(state["keystore"]), "--ks-key-alias", "game2apk", "--ks-pass", "env:GAME2APK_SIGNING_PASSWORD", str(apk)]
        if runner is None:
            child_env = sanitized_child_environment()
            child_env["GAME2APK_SIGNING_PASSWORD"] = effective_password
            completed = subprocess.run(_exec_command(command), capture_output=True, text=True, shell=False, env=child_env)
            output = completed.stdout + completed.stderr
            return_code = completed.returncode
            del child_env["GAME2APK_SIGNING_PASSWORD"]
        else:
            return_code, output = runner(command)
        if return_code != 0:
            raise ExternalToolError(f"apksigner failed with exit code {return_code}: {redact_text(output, [effective_password])}")
        # Gradle deliberately emits ``app-release-unsigned.apk`` even when
        # apksigner signs the file in place.  Leaving that name in the release
        # folder is misleading to users and to downstream file pickers.  Keep
        # the Gradle input in the audit report, but expose the signed output
        # with an explicit name and move the optional v4 sidecar alongside it.
        final_apk = apk
        renamed = False
        suffix = "-unsigned.apk"
        if apk.name.casefold().endswith(suffix):
            target = apk.with_name(apk.name[: -len(suffix)] + "-signed.apk")
            if target.exists():
                raise ExternalToolError(f"signed APK target already exists: {target}")
            apk.replace(target)
            source_idsig = Path(str(apk) + ".idsig")
            target_idsig = Path(str(target) + ".idsig")
            if source_idsig.exists():
                if target_idsig.exists():
                    raise ExternalToolError(f"signed APK sidecar target already exists: {target_idsig}")
                source_idsig.replace(target_idsig)
            final_apk = target
            renamed = True
        return {
            "apk": str(final_apk),
            "inputApk": str(apk),
            "inputRole": input_role,
            "signingMode": "signed-in-place-renamed" if renamed else "signed-in-place",
            "signedInPlace": True,
            "finalSignedApk": str(final_apk),
            "renamedFromUnsigned": renamed,
            "outputRole": "final signed release APK",
            "applicationId": application_id,
            "keystore": str(state["keystore"]),
            "signed": True,
            "backupPrompt": BACKUP_PROMPT,
        }
