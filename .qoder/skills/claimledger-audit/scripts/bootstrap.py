#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create ClaimLedger's isolated local environment")
    parser.add_argument("--local-ai", action="store_true", help="also install OpenVINO and PaddleOCR dependencies")
    args = parser.parse_args()
    environment = ROOT / ".venv"
    if not environment.exists():
        preferred = shutil.which("python3.11") or shutil.which("python3.12")
        if preferred and sys.version_info >= (3, 13):
            subprocess.run([preferred, "-m", "venv", str(environment)], check=True)
        else:
            venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    version = subprocess.check_output(
        [str(python), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        text=True,
    ).strip()
    if args.local_ai and tuple(map(int, version.split("."))) >= (3, 13):
        raise SystemExit(
            "local-ai dependencies require Python 3.11 or 3.12; recreate .venv with a compatible interpreter"
        )
    extra = "[local-ai]" if args.local_ai else ""
    subprocess.run([str(python), "-m", "pip", "install", "-e", f"{ROOT}{extra}"], check=True)
    print(f"{python} (Python {version})")


if __name__ == "__main__":
    main()
