"""Machine-readable CLI output must remain JSON with current dependencies."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("command", ["doctor", "demo"])
def test_cli_json_has_no_dependency_banner(command, tmp_path):
    args = [sys.executable, str(ROOT / "scripts" / "claimledger.py"), command]
    if command == "demo":
        args += ["--scenario", "operations", "--output", str(tmp_path / "demo")]
    args += ["--json"]
    result = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", cwd=tmp_path,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
             "CLAIMLEDGER_DATA_DIR": str(tmp_path / "data")},
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    if command == "doctor":
        assert payload["status"] == "ok"
    else:
        assert Path(payload["report"]).is_file()
        assert Path(payload["sources"]).is_dir()
