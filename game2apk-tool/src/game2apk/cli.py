"""Command line entry point for the same services used by the GUI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .builder import discover_toolchain
from .config import build_config, default_control_config
from .errors import Game2ApkError
from .models import BuildConfig
from .pipeline import PipelineService, stage_manifest_from_dict
from .security import read_secret_source, redact_text
from .translation import (
    DEFAULT_TRANSLATION_MODEL,
    DEFAULT_TRANSLATION_REASONING_EFFORT,
    DEFAULT_TRANSLATION_THINKING_ENABLED,
    TRANSLATION_REASONING_EFFORTS,
)
from .verifier import VerificationService


class SafeArgumentParser(argparse.ArgumentParser):
    """Do not echo arbitrary rejected argv tokens in usage errors."""

    def error(self, _message: str) -> None:
        raise Game2ApkError("invalid command line; use --help for supported options")


# These names are intentionally rejected, including ``--flag=value``. The
# supported interface accepts only an env-variable name, stdin, or a hidden
# prompt, never a secret value in argv.
_RAW_SECRET_FLAGS = {
    "--api-key",
    "--api-key-value",
    "--password",
    "--password-value",
    "--sign-password",
    "--sign-password-value",
    "--secret",
    "--token",
    "--passphrase",
    "--storepass",
    "--keypass",
}


def _reject_raw_secret_argv(argv: list[str]) -> None:
    for token in argv:
        flag = token.split("=", 1)[0].casefold()
        if flag in _RAW_SECRET_FLAGS:
            raise Game2ApkError(
                "raw secret command-line arguments are not supported; use an explicitly named environment variable, stdin, or a hidden prompt"
            )


def _add_secret_source_options(
    parser: argparse.ArgumentParser,
    prefix: str,
    *,
    default_env: str | None = None,
) -> None:
    group = parser.add_mutually_exclusive_group()
    option_prefix = prefix.replace("_", "-")
    group.add_argument(
        f"--{option_prefix}-env",
        dest=f"{prefix}_env",
        metavar="NAME",
        default=default_env,
        help="read the secret from environment variable NAME",
    )
    group.add_argument(
        f"--{option_prefix}-stdin",
        dest=f"{prefix}_stdin",
        action="store_true",
        help="read the secret from one line of stdin",
    )
    group.add_argument(
        f"--{option_prefix}-prompt",
        dest=f"{prefix}_prompt",
        action="store_true",
        help="read the secret using a hidden interactive prompt",
    )


def _read_cli_secret(args, prefix: str, kind: str, *, default_env: str | None = None) -> str | None:
    from_stdin = bool(getattr(args, f"{prefix}_stdin", False))
    prompt = bool(getattr(args, f"{prefix}_prompt", False))
    # An explicit source selector overrides the documented default variable.
    env_name = None if from_stdin or prompt else getattr(args, f"{prefix}_env", None)
    return read_secret_source(
        kind=kind,
        env_name=env_name,
        from_stdin=from_stdin,
        prompt=prompt,
        default_env_name=default_env,
    )


def _emit(value) -> None:
    payload = json.dumps(value.to_dict() if hasattr(value, "to_dict") else value, ensure_ascii=False, indent=2) + "\n"
    try:
        print(payload, end="")
    except UnicodeEncodeError:
        sys.stdout.buffer.write(payload.encode("utf-8"))


def _config(args) -> BuildConfig:
    data = build_config(
        app_name=args.app_name,
        application_id=args.application_id,
        version_code=args.version_code,
        version_name=args.version_name,
        icon_path=args.icon,
        control=default_control_config(),
    )
    return BuildConfig(
        app_name=data["appName"],
        application_id=data["applicationId"],
        version_code=data["versionCode"],
        version_name=data["versionName"],
        icon_path=args.icon,
        control_config=data["control"],
    )


def _common_build_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app-name", default="仙肴圣餐超魔改 Ver22")
    parser.add_argument("--application-id", default="com.game2apk.xianyaoshengcanver22")
    parser.add_argument("--version-code", type=int, default=8)
    parser.add_argument("--version-name", default="1.3.0")
    parser.add_argument("--icon")


def _translation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--thinking-mode",
        choices=("enabled", "disabled"),
        default="enabled" if DEFAULT_TRANSLATION_THINKING_ENABLED else "disabled",
        help="translation thinking mode (default: enabled; disabled is faster)",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=TRANSLATION_REASONING_EFFORTS,
        default=DEFAULT_TRANSLATION_REASONING_EFFORT,
        help="V4 Flash effort when thinking is enabled (low, high, max; default: high)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(
        prog="game2apk-tool",
        description="RPG Maker MV Windows staging/build/verify tool",
    )
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]), help="game2apk-tool root")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=SafeArgumentParser)

    inspect_parser = sub.add_parser("inspect", help="inspect an unpacked RPG Maker MV project")
    inspect_parser.add_argument("source")

    stage_parser = sub.add_parser("stage", help="inspect and stage only www")
    stage_parser.add_argument("source")
    stage_parser.add_argument("--minimum-free-bytes", type=int)

    patch_parser = sub.add_parser("patch", help="inject input bridge into an existing staged www")
    patch_parser.add_argument("--staged-www", required=True)
    _common_build_arguments(patch_parser)

    translate_parser = sub.add_parser("translate", help="translate safe MV fields; default skips Chinese projects")
    translate_parser.add_argument("--www", required=True)
    translate_parser.add_argument(
        "--model",
        default=DEFAULT_TRANSLATION_MODEL,
        help=f"DeepSeek model identifier (default: {DEFAULT_TRANSLATION_MODEL}; v4flash is accepted as an alias)",
    )
    translate_parser.add_argument("--target-language", default="zh-CN")
    translate_parser.add_argument("--force", action="store_true")
    translate_parser.add_argument("--confirm-third-party", action="store_true")
    _translation_arguments(translate_parser)
    _add_secret_source_options(translate_parser, "api_key", default_env="DEEPSEEK_API_KEY")

    build_parser_ = sub.add_parser("build", help="render template and run assembleRelease")
    build_parser_.add_argument("--stage-manifest", required=True)
    build_parser_.add_argument("--template", required=True)
    _common_build_arguments(build_parser_)

    sign_parser = sub.add_parser("sign", help="sign a fresh release APK using stable per-package key")
    sign_parser.add_argument("--apk", required=True)
    sign_parser.add_argument("--application-id", required=True)
    _add_secret_source_options(sign_parser, "password")

    verify_parser = sub.add_parser("verify", help="run static APK acceptance checks")
    verify_parser.add_argument("--apk", required=True)
    verify_parser.add_argument("--started-at")
    verify_parser.add_argument("--application-id")
    verify_parser.add_argument("--version-code", type=int)
    verify_parser.add_argument("--stage-manifest")
    verify_parser.add_argument("--adb-install", action="store_true")

    sub.add_parser("gui", help="open the non-blocking Tkinter wizard")

    run_parser = sub.add_parser("run", help="run inspect -> stage -> patch -> build -> sign -> verify")
    run_parser.add_argument("source")
    run_parser.add_argument("--translate", action="store_true", help="optionally translate selected MV text with DeepSeek; default is off")
    run_parser.add_argument("--template", required=True)
    run_parser.add_argument("--force-translation", action="store_true")
    run_parser.add_argument("--confirm-third-party", action="store_true")
    _translation_arguments(run_parser)
    _add_secret_source_options(run_parser, "api_key", default_env="DEEPSEEK_API_KEY")
    _add_secret_source_options(run_parser, "sign_password")
    run_parser.add_argument("--adb-install", action="store_true")
    _common_build_arguments(run_parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        _reject_raw_secret_argv(raw_argv)
        args = build_parser().parse_args(raw_argv)
    except Game2ApkError as exc:
        print(redact_text(exc), file=sys.stderr)
        return 2

    service = PipelineService(
        args.root,
        progress=lambda stage, fraction, message: print(
            f"[{stage} {fraction:.0%}] {redact_text(message)}", file=sys.stderr
        ),
    )
    try:
        if args.command == "inspect":
            _emit(service.inspect(args.source))
        elif args.command == "stage":
            _emit(service.stage(service.inspect(args.source), minimum_free_bytes=args.minimum_free_bytes))
        elif args.command == "patch":
            from .patcher import patch_staged_www

            _emit(patch_staged_www(args.staged_www, _config(args)))
        elif args.command == "translate":
            from .translation import TranslationService, extract_safe_entries, recommend_skip_translation

            recommended = recommend_skip_translation(extract_safe_entries(args.www))
            api_key = None if recommended and not args.force else _read_cli_secret(
                args, "api_key", "DeepSeek API key", default_env="DEEPSEEK_API_KEY"
            )
            _emit(
                TranslationService(service.progress, service.cancel_event).translate(
                    args.www,
                    target_language=args.target_language,
                    model=args.model,
                    api_key=api_key,
                    confirmed_third_party=args.confirm_third_party,
                    force=args.force,
                    thinking_enabled=args.thinking_mode == "enabled",
                    reasoning_effort=args.reasoning_effort,
                    memory_path=Path(args.root) / ".state" / "translation-memory.json",
                )
            )
        elif args.command == "build":
            stage_data = json.loads(Path(args.stage_manifest).read_text(encoding="utf-8"))
            result = service.build(args.template, stage_manifest_from_dict(stage_data), _config(args))
            _emit(result)
            return 0 if result.return_code == 0 and result.apk_path else 2
        elif args.command == "sign":
            from .signing import SigningService

            tools = discover_toolchain(Path(args.root) / "templates" / "android-rpgmv")
            password = _read_cli_secret(args, "password", "Signing password")
            _emit(
                SigningService(Path(args.root) / ".state").sign_apk(
                    args.apk,
                    args.application_id,
                    password=password,
                    apksigner=tools.apksigner,
                    jdk_dir=tools.jdk_dir,
                    input_role="standalone APK input",
                )
            )
        elif args.command == "verify":
            tools = discover_toolchain(Path(args.root) / "templates" / "android-rpgmv")
            report = VerificationService().verify(
                args.apk,
                tools,
                build_started_at=args.started_at,
                expected_application_id=args.application_id,
                expected_version_code=args.version_code,
                install=args.adb_install,
                stage_manifest_path=args.stage_manifest,
            )
            _emit(report)
            return 0 if report.passed else 2
        elif args.command == "gui":
            from .gui import main as gui_main

            gui_main(args.root)
            return 0
        elif args.command == "run":
            config = _config(args)
            inspection = service.inspect(args.source)
            translate_requested = bool(args.translate or args.force_translation)
            resume_key = service.build_resume_key(
                inspection,
                args.template,
                config,
                translate=translate_requested,
                thinking_enabled=args.thinking_mode == "enabled",
                reasoning_effort=args.reasoning_effort,
            )
            stage = service.stage(inspection, resume=True, resume_key=resume_key)
            resumed = bool(stage.resumed_from_existing)
            if not resumed:
                service.patch(stage, config)
            translation = None
            api_key = None
            if translate_requested and not resumed:
                api_key = _read_cli_secret(args, "api_key", "DeepSeek API key", default_env="DEEPSEEK_API_KEY")
                translation = service.translate(
                    stage,
                    model=None,
                    api_key=api_key,
                    confirmed_third_party=args.confirm_third_party,
                    force=args.force_translation,
                    thinking_enabled=args.thinking_mode == "enabled",
                    reasoning_effort=args.reasoning_effort,
                )
            if not resumed:
                service.mark_prepared(stage)
            result = service.build(args.template, stage, config, api_key=api_key)
            if result.return_code != 0 or not result.apk_path:
                _emit(result)
                return 2
            password = _read_cli_secret(args, "sign_password", "Signing password")
            signing = service.sign(result, config, password=password)
            verification = service.verify(result, config, install=args.adb_install)
            promoted = service.promote(verification, config) if verification.signature_candidate and verification.passed else None
            _emit(
                {
                    "inspection": inspection.to_dict(),
                    "stage": stage.to_dict(),
                    "translation": translation.to_dict() if translation else None,
                    "build": result.to_dict(),
                    "signing": signing,
                    "verification": verification.to_dict(),
                    "distApkPath": str(promoted) if promoted else None,
                }
            )
            return 0 if verification.passed else 2
        return 0
    except Game2ApkError as exc:
        print(redact_text(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError) as exc:
        print(redact_text(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
