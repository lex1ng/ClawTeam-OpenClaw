from __future__ import annotations

import json

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus, get_data_dir
from clawteam.team.tasks import TaskStore
from clawteam.team.waiter import TaskWaiter


def _seed_tasks_with_corruption(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")
    store = TaskStore("demo")

    completed = store.create("healthy completed", owner="worker1")
    store.update(completed.id, status=TaskStatus.completed)

    in_progress = store.create("healthy in progress", owner="worker1")
    store.update(in_progress.id, status=TaskStatus.in_progress, caller="worker1")

    broken_path = get_data_dir() / "tasks" / "demo" / "task-bad.json"
    broken_path.write_text("{bad-json", encoding="utf-8")
    return store, completed, in_progress


def test_task_waiter_degrades_with_read_faults(monkeypatch, tmp_path):
    store, completed, _ = _seed_tasks_with_corruption(monkeypatch, tmp_path)
    store.update(completed.id, status=TaskStatus.completed)
    monkeypatch.setattr("clawteam.spawn.registry.list_dead_agents", lambda team_name: [])

    waiter = TaskWaiter(
        team_name="demo",
        agent_name="leader",
        mailbox=MailboxManager("demo"),
        task_store=store,
        poll_interval=0.01,
        timeout=0.1,
    )

    result = waiter.wait()

    assert result.status == "timeout"
    assert result.total == 2
    assert result.completed == 1
    assert len(result.read_faults) == 1
    assert result.read_faults[0]["recordKind"] == "task"


def test_task_list_json_degrades_with_read_faults(monkeypatch, tmp_path):
    store, completed, _ = _seed_tasks_with_corruption(monkeypatch, tmp_path)
    store.update(completed.id, status=TaskStatus.completed)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["--json", "task", "list", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload["tasks"]) == 2
    assert len(payload["readFaults"]) == 1
    assert payload["readFaults"][0]["recordKind"] == "task"


def test_task_stats_json_degrades_with_read_faults(monkeypatch, tmp_path):
    _seed_tasks_with_corruption(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["--json", "task", "stats", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["total"] == 2
    assert len(payload["readFaults"]) == 1
    assert payload["readFaults"][0]["recordKind"] == "task"


def test_lifecycle_on_exit_degrades_with_read_faults_and_recovers_healthy_tasks(monkeypatch, tmp_path):
    store, _, in_progress = _seed_tasks_with_corruption(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["--json", "lifecycle", "on-exit", "--team", "demo", "--agent", "worker1"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "agent_exited"
    assert len(payload["abandoned_tasks"]) == 1
    assert payload["abandoned_tasks"][0]["id"] == in_progress.id
    assert len(payload["readFaults"]) == 1
    assert payload["readFaults"][0]["recordKind"] == "task"

    reloaded = store.get(in_progress.id)
    assert reloaded is not None
    assert reloaded.status == TaskStatus.pending
