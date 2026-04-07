from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from clawteam.board.collector import BoardCollector
from clawteam.cli.commands import app
from clawteam.coding import CodingExecRequest, CodingExecResult, CodingService
from clawteam.runtime_console import RuntimeConsoleStore
from clawteam.runtime_console.models import CallbackReportRecord, RuntimeFaultRecord
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
    assert "callbackChain" in data["runtimeConsole"]
    assert data["runtimeConsole"]["callbackChain"]["workers"][0]["to"] == "team_leader"
    assert data["runtimeConsole"]["callbackChain"]["team"]["to"] == "main_leader"
    assert "evidence" in data["runtimeConsole"]
    assert data["runtimeConsole"]["evidence"]["nonAuthoritative"] is True
    assert "source of truth" in data["runtimeConsole"]["evidence"]["authorityNotice"]


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
    assert data["runtimeConsole"]["faults"][0]["provenance"] == "runtime"


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


def test_board_collector_worker_alive_can_still_be_stalled_or_faulted(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("clawteam.board.collector.is_agent_alive", lambda _team, _agent: True)
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    task_store = TaskStore("demo")
    task = task_store.create("stalled callback worker", owner="worker1")
    service = CodingService()
    record = service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            taskId=task.id,
            provider="claude",
            prompt="stalled worker",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-stalled",
    )
    RuntimeConsoleStore().save_fault(
        RuntimeFaultRecord(
            faultId="fault-watchdog-1",
            faultType="watchdog_no_progress",
            severity="warning",
            scopeType="coding_job",
            scopeId=record.job_id,
            teamName="demo",
            message="Worker alive but no callback progress",
        )
    )

    data = BoardCollector().collect_team("demo")
    worker = next(item for item in data["runtimeConsole"]["workers"] if item["name"] == "worker1")
    chain_row = data["runtimeConsole"]["callbackChain"]["workers"][0]

    assert worker["processState"] == "alive"
    assert worker["health"] == "stalled"
    assert worker["callbackState"] == "pending"
    assert worker["faultProvenance"] == "watchdog"
    assert chain_row["callbackState"] == "pending"
    assert data["runtimeConsole"]["callbackChain"]["team"]["callbackState"] == "in_progress"


def test_board_collector_evidence_payload_is_bounded_and_read_faults_are_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")
    task = TaskStore("demo").create("evidence task", owner="worker1")
    service = CodingService()
    record = service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            taskId=task.id,
            provider="claude",
            prompt="evidence capture",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-evidence",
    )
    service.mark_running("demo", record.job_id)
    stdout_path = service.store.save_text_artifact("demo", record.job_id, "stdout.log", "x" * 200)
    service.complete_job(
        "demo",
        record.job_id,
        CodingExecResult(
            jobId=record.job_id,
            provider="claude",
            effectiveCwd="/tmp/worktree",
            status="completed",
            summary="completed with long stdout",
        ),
        artifact_paths={"stdoutLog": stdout_path},
    )

    broken_evidence_path = Path(tmp_path) / "runtime-console" / "evidence" / "demo" / "bad.json"
    broken_evidence_path.parent.mkdir(parents=True, exist_ok=True)
    broken_evidence_path.write_text("{bad-json", encoding="utf-8")

    payload = BoardCollector().collect_evidence("demo", max_chars=32, limit=20)

    assert payload["nonAuthoritative"] is True
    assert payload["viewKind"] == "bounded_evidence_view"
    assert payload["summary"]["total"] >= 1
    assert payload["summary"]["truncated"] >= 1
    assert payload["summary"]["collectorDerived"] >= 1
    assert any(len((record.get("excerpt") or "")) <= 32 for record in payload["records"])
    assert len(payload["readFaults"]) == 1
    assert payload["readFaults"][0]["recordKind"] == "evidence"
    assert payload["readFaults"][0]["faultType"] == "corrupt_record"


def test_board_collector_completed_worker_can_be_ended_without_faulted(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    task = TaskStore("demo").create("completed worker", owner="worker1")
    service = CodingService()
    service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            taskId=task.id,
            provider="claude",
            prompt="complete",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-ended-worker",
    )
    service.mark_running("demo", "job-ended-worker")
    completed = service.complete_job(
        "demo",
        "job-ended-worker",
        CodingExecResult(
            jobId="job-ended-worker",
            provider="claude",
            effectiveCwd="/tmp/worktree",
            status="completed",
            summary="done",
        ),
    )
    TaskStore("demo").record_coding_callback(
        task.id,
        WorkerCodingCallbackReport.from_coding_result(
            task_id=task.id,
            job_id=completed.job_id,
            provider=completed.provider.value,
            status=completed.state.value,
            decision=WorkerCodingDecision.report_progress,
            summary="done",
            artifact_paths=completed.artifact_paths,
        ),
    )
    monkeypatch.setattr("clawteam.board.collector.is_agent_alive", lambda _team, _agent: False)

    data = BoardCollector().collect_team("demo")
    worker = next(item for item in data["runtimeConsole"]["workers"] if item["name"] == "worker1")
    chain_row = next(item for item in data["runtimeConsole"]["callbackChain"]["workers"] if item["workerName"] == "worker1")

    assert worker["processState"] == "ended"
    assert worker["health"] != "faulted"
    assert worker["callbackState"] == "reported"
    assert chain_row["callbackState"] == "reported"


def test_board_collector_unknown_liveness_is_not_collapsed_to_ended_or_faulted(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")
    TaskStore("demo").create("unknown liveness worker", owner="worker1")
    monkeypatch.setattr("clawteam.board.collector.is_agent_alive", lambda _team, _agent: None)

    data = BoardCollector().collect_team("demo")
    worker = next(item for item in data["runtimeConsole"]["workers"] if item["name"] == "worker1")

    assert worker["processState"] == "unknown"
    assert worker["health"] != "faulted"
    assert worker["processState"] != "ended"


def test_board_collector_callback_state_survives_non_fatal_warning_fault(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    task = TaskStore("demo").create("callback with warning", owner="worker1")
    service = CodingService()
    record = service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            taskId=task.id,
            provider="claude",
            prompt="callback survives warning",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-warning",
    )
    service.mark_running("demo", record.job_id)
    completed = service.complete_job(
        "demo",
        record.job_id,
        CodingExecResult(
            jobId=record.job_id,
            provider="claude",
            effectiveCwd="/tmp/worktree",
            status="completed",
            summary="ok",
        ),
    )
    TaskStore("demo").record_coding_callback(
        task.id,
        WorkerCodingCallbackReport.from_coding_result(
            task_id=task.id,
            job_id=completed.job_id,
            provider=completed.provider.value,
            status=completed.state.value,
            decision=WorkerCodingDecision.report_progress,
            summary="reported",
            artifact_paths=completed.artifact_paths,
        ),
    )
    RuntimeConsoleStore().save_fault(
        RuntimeFaultRecord(
            faultId="fault-session-warning",
            faultType="session_ephemeral",
            severity="warning",
            scopeType="provider_session",
            scopeId=record.provider_session_ref,
            teamName="demo",
            message="Session metadata unavailable",
        )
    )

    data = BoardCollector().collect_team("demo")
    worker = next(item for item in data["runtimeConsole"]["workers"] if item["name"] == "worker1")
    chain_row = next(item for item in data["runtimeConsole"]["callbackChain"]["workers"] if item["workerName"] == "worker1")

    assert worker["callbackState"] == "reported"
    assert chain_row["callbackState"] == "reported"
    assert worker["faultState"] == "faulted"


def test_board_collector_team_callback_state_machine(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    task = TaskStore("demo").create("team callback state machine", owner="worker1")
    service = CodingService()
    service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            taskId=task.id,
            provider="claude",
            prompt="team in_progress",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-team-progress",
    )
    data = BoardCollector().collect_team("demo")
    assert data["runtimeConsole"]["callbackChain"]["team"]["callbackState"] == "in_progress"

    service.mark_running("demo", "job-team-progress")
    completed = service.complete_job(
        "demo",
        "job-team-progress",
        CodingExecResult(
            jobId="job-team-progress",
            provider="claude",
            effectiveCwd="/tmp/worktree",
            status="completed",
            summary="worker done",
        ),
    )
    TaskStore("demo").record_coding_callback(
        task.id,
        WorkerCodingCallbackReport.from_coding_result(
            task_id=task.id,
            job_id=completed.job_id,
            provider=completed.provider.value,
            status=completed.state.value,
            decision=WorkerCodingDecision.report_progress,
            summary="worker reported",
            artifact_paths=completed.artifact_paths,
        ),
    )
    data = BoardCollector().collect_team("demo")
    assert data["runtimeConsole"]["callbackChain"]["team"]["callbackState"] == "waiting_aggregate"

    RuntimeConsoleStore().save_callback_report(
        CallbackReportRecord(
            teamName="demo",
            taskId=task.id,
            jobId="team-callback-job",
            provider="clawteam",
            status="completed",
            decision="report_progress",
            callbackLevel="team",
            upwardTarget="main_leader",
            chainStatus="reported",
            reportedUpward=False,
            summary="team aggregated",
        )
    )
    data = BoardCollector().collect_team("demo")
    assert data["runtimeConsole"]["callbackChain"]["team"]["callbackState"] == "reported"

    RuntimeConsoleStore().save_callback_report(
        CallbackReportRecord(
            teamName="demo",
            taskId=task.id,
            jobId="team-callback-upward-job",
            provider="clawteam",
            status="completed",
            decision="report_progress",
            callbackLevel="team",
            upwardTarget="main_leader",
            chainStatus="reported_upward",
            reportedUpward=True,
            summary="team reported upward",
        )
    )
    data = BoardCollector().collect_team("demo")
    assert data["runtimeConsole"]["callbackChain"]["team"]["callbackState"] == "reported_upward"
