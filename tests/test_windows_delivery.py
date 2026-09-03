import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None,
    reason="Windows PowerShell delivery test",
)


def _run(*args, env=None):
    return subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", *map(str, args)],
        cwd=REPO,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("script", ["install.ps1", "uninstall.ps1", "scripts/demo.ps1"])
def test_windows_scripts_parse(script):
    path = REPO / script
    quoted = str(path).replace("'", "''")
    result = _run(
        "-Command",
        f"[scriptblock]::Create([IO.File]::ReadAllText('{quoted}')) | Out-Null",
    )
    assert result.returncode == 0, result.stderr


def test_skill_install_is_idempotent_and_uninstall_preserves_state(tmp_path):
    install_root = tmp_path / "install"
    skill_root = tmp_path / "skills"
    fake_home = tmp_path / "home"
    state_marker = fake_home / ".wewrite" / "keep.txt"
    state_marker.parent.mkdir(parents=True)
    state_marker.write_text("keep", encoding="utf-8")
    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)

    args = (
        "-File", REPO / "install.ps1",
        "-RepoRoot", REPO,
        "-InstallRoot", install_root,
        "-SkillTarget", skill_root,
        "-SkipCli", "-SkipMigration", "-NoPathUpdate",
    )
    first = _run(*args, env=env)
    assert first.returncode == 0, first.stderr
    second = _run(*args, env=env)
    assert second.returncode == 0, second.stderr

    manifest = json.loads((install_root / "install.json").read_text(encoding="utf-8-sig"))
    assert manifest["cli_installed"] is False
    assert manifest["skill_links"]
    assert all(Path(path).exists() for path in manifest["skill_links"])

    removed = _run(
        "-File", REPO / "uninstall.ps1",
        "-InstallRoot", install_root,
        "-Confirm:$false",
        env=env,
    )
    assert removed.returncode == 0, removed.stderr
    assert not install_root.exists()
    assert not any(skill_root.iterdir())
    assert state_marker.read_text(encoding="utf-8") == "keep"


def test_offline_demo_generates_auditable_outputs(tmp_path):
    output = tmp_path / "demo"
    result = _run(
        "-File", REPO / "scripts" / "demo.ps1",
        "-RepoRoot", REPO,
        "-OutputDir", output,
        "-NoOpen",
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads((output / "demo-report.json").read_text(encoding="utf-8"))
    assert report["network_requests"] == 0
    assert report["credentials_read"] is False
    assert (output / "preview.html").is_file()
    validation = json.loads((output / "validation.json").read_text(encoding="utf-8"))
    assert validation["errors"] == 0
    assert "quality_score" in json.loads((output / "score.json").read_text(encoding="utf-8"))
