#!/usr/bin/env python3
"""Zero-shim unittest runner mapping `local_app` to repository root modules."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def register_local_app() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    pkg = types.ModuleType("local_app")
    pkg.__path__ = [str(ROOT)]
    sys.modules["local_app"] = pkg
    for module_path in sorted(ROOT.glob("*.py")):
        if module_path.stem.startswith("test_") or module_path.stem in ("__init__", "run_tests"):
            continue
        sys.modules[f"local_app.{module_path.stem}"] = importlib.import_module(module_path.stem)


def main() -> int:
    register_local_app()
    patterns = sys.argv[1:] or ["test_*.py"]
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for pat in patterns:
        suite.addTests(loader.discover(str(ROOT), pattern=pat))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
