#!/usr/bin/env python3
"""Build the deterministic ClaimLedger release bundle."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".qoder" / "skills" / "claimledger-audit"
DIST = ROOT / "dist"
ZIP = DIST / "claimledger-audit.zip"
WHEELS = DIST / "wheels"
UPLOAD = DIST / "modelscope-upload"
SOURCE_DATE_EPOCH = "1767225600"
PROJECT_VERSION = tomllib.loads(
    (SKILL / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["version"]


def build_python() -> str:
    project_python = SKILL / ".venv" / "bin" / "python"
    return str(project_python) if project_python.is_file() else sys.executable


def run(*args: str, cwd: Path = ROOT) -> None:
    subprocess.run(args, cwd=cwd, check=True, env={
        **os.environ,
        "PYTHONHASHSEED": "0",
        "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH,
    })


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_wheel() -> Path:
    WHEELS.mkdir(parents=True, exist_ok=True)
    wheel_pattern = f"claimledger-{PROJECT_VERSION}-*.whl"
    for path in WHEELS.glob(wheel_pattern):
        path.unlink()
    with tempfile.TemporaryDirectory(prefix="claimledger-wheel-") as temporary:
        output = Path(temporary)
        run(
            build_python(),
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(output),
            ".",
            cwd=SKILL,
        )
        wheels = list(output.glob(wheel_pattern))
        if len(wheels) != 1:
            raise SystemExit(
                f"expected exactly one ClaimLedger {PROJECT_VERSION} wheel"
            )
        destination = WHEELS / wheels[0].name
        shutil.copy2(wheels[0], destination)
        return destination


def write_checksums(files: list[Path]) -> Path:
    target = DIST / "SHA256SUMS"
    lines = [
        f"{digest(path)}  {path.relative_to(DIST).as_posix()}"
        for path in sorted(files)
    ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def main() -> None:
    run(
        build_python(),
        str(ROOT / "tools" / "build-skill-package.py"),
        "--output",
        str(ZIP),
        "--upload-dir",
        str(UPLOAD),
    )
    wheel = build_wheel()
    checksums = write_checksums([ZIP, wheel])
    print(f"ZIP: {ZIP}")
    print(f"Wheel: {wheel}")
    print(f"Upload directory: {UPLOAD}")
    print(f"Checksums: {checksums}")


if __name__ == "__main__":
    main()
