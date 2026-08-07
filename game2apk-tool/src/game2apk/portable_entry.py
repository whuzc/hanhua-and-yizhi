"""PyInstaller entry point that keeps package-relative imports intact."""

from game2apk.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

