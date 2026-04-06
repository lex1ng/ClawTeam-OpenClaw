from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.manager import TeamManager


class ErrorBackend:
    def spawn(self, **kwargs):
        return (
            "Error: command 'nanobot' not found in PATH. "
            "Install the agent CLI first or pass an executable path."
        )

    def list_running(self):
        return []


class RecordingBackend:
    def __init__(self):
        self.calls: list[dict] = []

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        return f"Agent '{kwargs['agent_name']}' spawned"

    def list_running(self):
        return []


def _init_git_repo(path: Path, *, commit: bool) -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True, text=True)
    if commit:
        (path / "README.md").write_text("demo\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, text=True)
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return branch
    branch_name = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return branch_name


def test_spawn_cli_exits_nonzero_and_rolls_back_failed_member(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: ErrorBackend())

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["spawn", "tmux", "nanobot", "--team", "demo", "--agent-name", "alice", "--no-workspace"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 1
    assert "Error: command 'nanobot' not found in PATH" in result.output
    assert [member.name for member in TeamManager.list_members("demo")] == ["leader"]


def test_spawn_cli_workspace_auto_skips_unhealthy_repo_with_diagnostics(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    backend = RecordingBackend()
    repo = tmp_path / "scratch-repo"
    unborn_branch = _init_git_repo(repo, commit=False)

    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["--json", "spawn", "tmux", "openclaw", "--team", "demo", "--agent-name", "alice", "--repo", str(repo), "--task", "do work"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path / "data")},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "spawned"
    assert payload["workspace"]["status"] == "skipped"
    assert payload["workspace"]["requestedPath"] == str(repo.resolve())
    assert payload["workspace"]["workspaceMode"] == "auto"
    assert payload["workspace"]["currentBranch"] == unborn_branch
    assert payload["workspace"]["headValid"] is False
    assert "--no-workspace" in payload["workspace"]["recommendations"]
    assert "--workspace-base-ref <ref>" in payload["workspace"]["recommendations"]
    assert backend.calls[0]["cwd"] == str(repo.resolve())


def test_spawn_cli_workspace_always_fails_on_unhealthy_repo_with_diagnostics(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    backend = RecordingBackend()
    repo = tmp_path / "scratch-repo"
    unborn_branch = _init_git_repo(repo, commit=False)

    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["--json", "spawn", "tmux", "openclaw", "--team", "demo", "--agent-name", "alice", "--workspace", "--repo", str(repo), "--task", "do work"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path / "data")},
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"] == "workspace_preflight_failed"
    assert payload["workspace"]["workspaceMode"] == "always"
    assert payload["workspace"]["currentBranch"] == unborn_branch
    assert payload["workspace"]["headValid"] is False
    assert backend.calls == []
    assert [member.name for member in TeamManager.list_members("demo")] == ["leader"]


def test_spawn_cli_workspace_base_ref_allows_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    backend = RecordingBackend()
    repo = tmp_path / "repo"
    branch = _init_git_repo(repo, commit=True)

    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--json",
            "spawn",
            "tmux",
            "openclaw",
            "--team",
            "demo",
            "--agent-name",
            "alice",
            "--workspace",
            "--workspace-base-ref",
            branch,
            "--repo",
            str(repo),
            "--task",
            "do work",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path / "data")},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["workspace"]["status"] == "created"
    assert payload["workspace"]["resolvedBaseRef"] == branch
    assert payload["workspace"]["headValid"] is True
