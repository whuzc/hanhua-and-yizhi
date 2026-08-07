"""Source-tree launcher for Windows users without an installed package."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from game2apk.cli import main  # noqa: E402


raise SystemExit(main())

