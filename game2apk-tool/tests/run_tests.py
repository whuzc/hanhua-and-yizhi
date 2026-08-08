from __future__ import annotations

import sys
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


if __name__ == "__main__":
    passed = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")).wasSuccessful()
    node = shutil.which("node")
    if not node:
        print("node is required for the MV frame sampling regression", file=sys.stderr)
        raise SystemExit(1)
    node_results = []
    for script in ("mv_input_frame_regression.js", "mv_touch_regression.js", "mv_audio_exit_regression.js"):
        node_results.append(subprocess.run([node, str(ROOT / "tests" / script)], text=True).returncode)
    raise SystemExit(0 if passed and all(code == 0 for code in node_results) else 1)
