from __future__ import annotations

import json

from typer.testing import CliRunner

from clawteam.board.collector import BoardCollector
from clawteam.cli.commands import app
from clawteam.coding import CodingExecRequest, CodingExecResult, CodingService
from clawteam.runtime_console import RuntimeConsoleStore
from clawteam.runtime_console.models import RuntimeFaultRecord
from clawteam.team.manager import TeamManager
from clawteam.team.models import WorkerCodingCallbackReport, WorkerCodingDecision
from clawteam.team.tasks import TaskStore


def _seed_mixed_fault_board_state(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    task_store = TaskStore("demo")
    task = task_store.create("healthy task", owner="worker1")
    broken_task_path = tmp_path / "tasks" / "demo" / "task-bad.json"
    broken_task_path.parent.mkdir(parents=True, exist_ok=True)
    broken_task_path.write_text("{bad-json", encoding="utf-8")

    service = CodingService()
    record = service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            taskId=task.id,
            provider="claude",
            prompt="Implement durable callbacks",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-mixed-fault",
    )
    service.store.job_path("demo", "job-bad").write_text("{bad-json", encoding="utf-8")
    RuntimeConsoleStore().save_fault(
        RuntimeFaultRecord(
            faultId="fault-runtime-mixed",
            faultType="session_ephemeral",
            severity="warning",
            scopeType="provider_session",
            scopeId=record.provider_session_ref,
            teamName="demo",
            message="Session metadata unavailable",
        )
    )
    return task


def test_board_collector_surfaces_coding_runtime_and_task_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    task_store = TaskStore("demo")
    task = task_store.create("Implement callback runtime", owner="worker1")

    service = CodingService()
    service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            taskId=task.id,
            provider="claude",
            prompt="Queued job",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-queued",
    )

    service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker2",
            workerId="worker-002",
            taskId="task-2",
            provider="codex",
            prompt="Completed job",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-completed",
    )
    service.mark_running("demo", "job-completed")
    completed = service.complete_job(
        "demo",
        "job-completed",
        CodingExecResult(
            jobId="job-completed",
            provider="codex",
            effectiveCwd="/tmp/worktree",
            status="completed",
            summary="Implemented runtime collector hooks",
        ),
    )
    task_store.record_coding_callback(
        task.id,
        WorkerCodingCallbackReport.from_coding_result(
            task_id=task.id,
            job_id=completed.job_id,
            provider=completed.provider.value,
            status=completed.state.value,
            decision=WorkerCodingDecision.report_progress,
            summary="Collector hooks implemented and recorded.",
            artifact_paths=completed.artifact_paths,
        ),
    )

    data = BoardCollector().collect_team("demo")

    assert data["coding"]["summary"]["queued"] == 1
    assert data["coding"]["summary"]["completed"] == 1
    assert data["coding"]["summary"]["active"] == 1
    assert data["coding"]["recentJobs"][0]["jobId"] in {"job-queued", "job-completed"}
    assert data["coding"]["latestByWorker"]["worker1"]["jobId"] == "job-queued"
    pending_task = data["tasks"]["pending"][0]
    assert pending_task["metadata"]["coding"]["latestJobId"] == "job-completed"
    assert pending_task["metadata"]["coding"]["summary"] == "Collector hooks implemented and recorded."
    assert data["coding"]["storage"]["jobsRoot"].endswith("/coding/jobs/demo")
    assert data["runtimeConsole"]["jobs"][0]["jobId"] in {"job-queued", "job-completed"}
    assert data["runtimeConsole"]["sessions"][0]["sessionMode"] == "ephemeral"
    assert "providerSessionId" not in data["runtimeConsole"]["sessions"][0]
    assert data["runtimeConsole"]["callbacks"][0]["jobId"] == "job-completed"
    assert any(event["eventType"] == "callback_reported" for event in data["runtimeConsole"]["timeline"])


def test_board_collector_runtime_console_faults_include_explicit_runtime_faults(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    service = CodingService()
    record = service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            taskId="task-1",
            provider="claude",
            prompt="Queued job",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-fault",
    )
    RuntimeConsoleStore().save_fault(
        RuntimeFaultRecord(
            faultId="fault-runtime-1",
            faultType="session_ephemeral",
            severity="warning",
            scopeType="provider_session",
            scopeId=record.provider_session_ref,
            teamName="demo",
            message="Session metadata unavailable",
        )
    )

    data = BoardCollector().collect_team("demo")

    assert data["runtimeConsole"]["faults"][0]["faultId"] == "fault-runtime-1"
    assert data["runtimeConsole"]["summary"]["faults"]["total"] == 1


def test_board_collector_session_events_include_callback_linked_events(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    task_store = TaskStore("demo")
    task = task_store.create("Implement callback runtime", owner="worker1")

    service = CodingService()
    service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            taskId=task.id,
            provider="claude",
            prompt="Queued job",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-session-events",
    )
    service.mark_running("demo", "job-session-events")
    completed = service.complete_job(
        "demo",
        "job-session-events",
        CodingExecResult(
            jobId="job-session-events",
            provider="claude",
            effectiveCwd="/tmp/worktree",
            status="completed",
            summary="Implemented runtime collector hooks",
        ),
    )
    task_store.record_coding_callback(
        task.id,
        WorkerCodingCallbackReport.from_coding_result(
            task_id=task.id,
            job_id=completed.job_id,
            provider=completed.provider.value,
            status=completed.state.value,
            decision=WorkerCodingDecision.report_progress,
            summary="Collector hooks implemented and recorded.",
            artifact_paths=completed.artifact_paths,
        ),
    )

    payload = BoardCollector().collect_provider_session_events("demo", completed.provider_session_ref)
    event_types = [event["eventType"] for event in payload["events"]]

    assert "provider_session_attached" in event_types
    assert "callback_reported" in event_types


def test_board_show_json_includes_coding_section(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["--json", "board", "show", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "coding" in payload
    assert payload["coding"]["summary"]["total"] == 0


def test_board_show_json_surfaces_coding_store_faults(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    service = CodingService()
    service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            taskId="task-1",
            provider="claude",
            prompt="Queued job",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-ok",
    )
    broken_path = service.store.job_path("demo", "job-bad")
    broken_path.write_text("{bad-json", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["--json", "board", "show", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["coding"]["summary"]["total"] == 1
    assert len(payload["coding"]["faults"]) == 1
    assert payload["coding"]["faults"][0]["faultType"] == "corrupt_record"


def test_board_collector_surfaces_task_read_faults(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    task_store = TaskStore("demo")
    task = task_store.create("healthy task", owner="worker1")
    broken_path = tmp_path / "tasks" / "demo" / "task-bad.json"
    broken_path.parent.mkdir(parents=True, exist_ok=True)
    broken_path.write_text("{bad-json", encoding="utf-8")

    data = BoardCollector().collect_team("demo")

    assert data["taskSummary"]["total"] == 1
    assert data["tasks"]["pending"][0]["id"] == task.id
    assert len(data["taskReadFaults"]) == 1
    assert data["taskReadFaults"][0]["faultType"] == "corrupt_record"
    assert data["taskReadFaults"][0]["recordKind"] == "task"


def test_board_show_json_preserves_mixed_fault_surfaces(monkeypatch, tmp_path):
    task = _seed_mixed_fault_board_state(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["--json", "board", "show", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["taskSummary"]["total"] == 1
    assert payload["runtimeConsole"]["tasks"][0]["id"] == task.id
    assert len(payload["taskReadFaults"]) == 1
    assert payload["taskReadFaults"][0]["recordKind"] == "task"
    assert len(payload["coding"]["faults"]) == 1
    assert payload["coding"]["faults"][0]["recordKind"] == "job"
    assert len(payload["runtimeConsole"]["faults"]) == 1
    assert payload["runtimeConsole"]["faults"][0]["faultId"] == "fault-runtime-mixed"


def test_board_show_human_surfaces_task_coding_and_runtime_fault_groups(monkeypatch, tmp_path):
    _seed_mixed_fault_board_state(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["board", "show", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0
    assert "Fault Surfaces" in result.stdout
    assert "Task Read Faults" in result.stdout
    assert "Coding Read Faults" in result.stdout
    assert "Runtime Faults" in result.stdout
    assert "Healthy records continue to render" in result.stdout
