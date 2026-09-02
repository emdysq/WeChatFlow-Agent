import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def test_cli_emits_utf8_under_ascii_parent_stdio(tmp_path):
    """Chinese diagnostics must not crash under a legacy Windows code page."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "ascii"
    env["WEWRITE_HOME"] = str(tmp_path / "wewrite-home")

    result = subprocess.run(
        [sys.executable, "-m", "wewrite", "diagnose", "--json"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    payload = json.loads(result.stdout.decode("utf-8"))
    assert "summary" in payload
