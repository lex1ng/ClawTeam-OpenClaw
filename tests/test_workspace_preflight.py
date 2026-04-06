from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from clawteam.cli.commands import app


def _init_git_repo(path: Path, *, commit: bool) -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True, text=True)
    if commit:
        (path / "README.md").write_text("demo\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, text=True)
    return subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_workspace_doctor_reports_healthy_repo(tmp_path):
    repo = tmp_path / "repo"
    branch = _init_git_repo(repo, commit=True)
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "workspace", "doctor", "--repo", str(repo)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["isGitRepo"] is True
    assert payload["headValid"] is True
    assert payload["currentBranch"] == branch
    assert payload["resolvedBaseRef"] == branch
    assert payload["worktreeCapable"] is True
    assert payload["recommendedSpawnMode"] == "workspace"
    assert payload["status"] == "ready"


def test_workspace_doctor_reports_unhealthy_repo(tmp_path):
    repo = tmp_path / "repo"
    branch = _init_git_repo(repo, commit=False)
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "workspace", "doctor", "--repo", str(repo)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["isGitRepo"] is True
    assert payload["headValid"] is False
    assert payload["currentBranch"] == branch
    assert payload["worktreeCapable"] is False
    assert payload["recommendedSpawnMode"] == "no-workspace"
    assert "--workspace-base-ref <ref>" in payload["recommendations"]
