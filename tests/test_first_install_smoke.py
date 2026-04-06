from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.manager import TeamManager


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
    return subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_clawteam_standalone_smoke(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(data_dir))
    runner = CliRunner()
    backend = RecordingBackend()

    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)

    result = runner.invoke(app, ["team", "spawn-team", "demo", "-n", "leader"], env={"CLAWTEAM_DATA_DIR": str(data_dir)})
    assert result.exit_code == 0

    result = runner.invoke(app, ["--json", "team", "discover"], env={"CLAWTEAM_DATA_DIR": str(data_dir)})
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload[0]["name"] == "demo"

    result = runner.invoke(app, ["team", "status", "demo"], env={"CLAWTEAM_DATA_DIR": str(data_dir)})
    assert result.exit_code == 0
    assert "leader" in result.stdout

    result = runner.invoke(
        app,
        ["--json", "task", "create", "demo", "first task", "--owner", "worker1"],
        env={"CLAWTEAM_DATA_DIR": str(data_dir)},
    )
    assert result.exit_code == 0
    task_payload = json.loads(result.stdout)
    task_id = task_payload["id"]

    result = runner.invoke(app, ["--json", "task", "list", "demo"], env={"CLAWTEAM_DATA_DIR": str(data_dir)})
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["tasks"][0]["id"] == task_id

    result = runner.invoke(
        app,
        ["task", "update", "demo", task_id, "--status", "completed"],
        env={"CLAWTEAM_DATA_DIR": str(data_dir)},
    )
    assert result.exit_code == 0

    result = runner.invoke(
        app,
        ["--json", "task", "wait", "demo", "--timeout", "0.1", "--poll-interval", "0.01"],
        env={"CLAWTEAM_DATA_DIR": str(data_dir)},
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["status"] == "completed"

    result = runner.invoke(
        app,
        ["inbox", "send", "demo", "leader", "hello", "--from", "worker1"],
        env={"CLAWTEAM_DATA_DIR": str(data_dir)},
    )
    assert result.exit_code == 0

    result = runner.invoke(
        app,
        ["--json", "inbox", "receive", "demo", "--agent", "leader"],
        env={"CLAWTEAM_DATA_DIR": str(data_dir)},
    )
    assert result.exit_code == 0
    messages = json.loads(result.stdout)
    assert messages[0]["content"] == "hello"

    result = runner.invoke(
        app,
        ["--json", "inbox", "log", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(data_dir)},
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["count"] == 1

    repo = tmp_path / "project"
    repo.mkdir()
    result = runner.invoke(
        app,
        ["--json", "spawn", "tmux", "openclaw", "--team", "demo", "--agent-name", "worker1", "--no-workspace", "--repo", str(repo), "--task", "do work"],
        env={"CLAWTEAM_DATA_DIR": str(data_dir)},
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "spawned"
    assert backend.calls[0]["cwd"] == str(repo.resolve())

    result = runner.invoke(app, ["board", "show", "demo"], env={"CLAWTEAM_DATA_DIR": str(data_dir)})
    assert result.exit_code == 0
    assert "demo" in result.stdout
    assert "Task Board" in result.stdout


def test_openclaw_default_worker_spawn_smoke(monkeypatch, tmp_path):
    from clawteam.spawn.tmux_backend import TmuxBackend

    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr("sys.argv", [str(clawteam_bin)])

    run_calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(args, **kwargs):
        run_calls.append(args)
        if args[:3] == ["tmux", "has-session", "-t"]:
            return Result(returncode=1)
        if args[:3] == ["tmux", "list-panes", "-t"]:
            return Result(returncode=0, stdout="9876\n")
        return Result(returncode=0)

    def fake_which(name, path=None):
        if name == "tmux":
            return "/usr/bin/tmux"
        if name == "openclaw":
            return "/usr/bin/openclaw"
        return None

    monkeypatch.setattr("shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = TmuxBackend()
    result = backend.spawn(
        command=["openclaw"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo",
        prompt="Implement the assigned task",
        cwd="/tmp/project",
        skip_permissions=False,
    )

    assert result == "Agent 'worker1' spawned in tmux (clawteam-demo:worker1)"
    new_session = next(call for call in run_calls if call[:3] == ["tmux", "new-session", "-d"])
    full_cmd = new_session[-1]
    assert "openclaw tui --deliver" in full_cmd
    assert "--message 'Implement the assigned task'" in full_cmd


def test_spawn_workspace_auto_healthy_repo_smoke(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(data_dir))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")

    backend = RecordingBackend()
    repo = tmp_path / "project"
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
            "worker2",
            "--repo",
            str(repo),
            "--task",
            "implement feature",
        ],
        env={"CLAWTEAM_DATA_DIR": str(data_dir)},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "spawned"
    assert payload["workspace"]["status"] == "created"
    assert payload["workspace"]["resolvedBaseRef"] == branch
    assert Path(payload["workspace"]["worktreePath"]).exists()
    assert backend.calls[0]["cwd"] == str(Path(payload["workspace"]["worktreePath"]).resolve())


def test_board_serve_smoke_supports_remote_bind(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(data_dir))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")

    captured: dict[str, object] = {}

    def fake_serve(*, host: str, port: int, default_team: str, interval: float) -> None:
        captured.update(
            {
                "host": host,
                "port": port,
                "default_team": default_team,
                "interval": interval,
            }
        )

    monkeypatch.setattr("clawteam.board.server.serve", fake_serve)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["board", "serve", "demo", "--host", "0.0.0.0", "--port", "9090", "--interval", "1.5"],
        env={"CLAWTEAM_DATA_DIR": str(data_dir)},
    )

    assert result.exit_code == 0
    assert "http://0.0.0.0:9090" in result.stdout
    assert captured == {
        "host": "0.0.0.0",
        "port": 9090,
        "default_team": "demo",
        "interval": 1.5,
    }
