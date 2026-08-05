#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VENV_ROOT = ROOT / ".venv"
VENV_PYTHON = VENV_ROOT / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != VENV_ROOT.resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])
if str(SRC) in sys.path:
    sys.path.remove(str(SRC))
sys.path.insert(0, str(SRC))

try:
    from claimledger.cli import main
except ModuleNotFoundError as exc:
    raise SystemExit(
        f"ClaimLedger dependency '{exc.name}' is missing. Run: python scripts/bootstrap.py"
    ) from exc


if __name__ == "__main__":
    main()
