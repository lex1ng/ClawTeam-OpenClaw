"""Phase 2 tests for Runtime Console CLI inspection commands."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.coding import CodingExecRequest, CodingExecResult, CodingService
from clawteam.runtime_console import RuntimeConsoleStore
from clawteam.runtime_console.models import RuntimeFaultRecord
from clawteam.team.manager import TeamManager
from clawteam.team.models import WorkerCodingCallbackReport, WorkerCodingDecision
from clawteam.team.tasks import TaskStore


def _seed_runtime_console(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    task_store = TaskStore("demo")
    task = task_store.create("Inspect runtime console", owner="worker1")

    service = CodingService()
    record = service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            leaderName="leader",
            taskId=task.id,
            provider="claude",
            prompt="Implement runtime console",
            cwd="/tmp/worktree/runtime-console",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
            providerArgs=["--model", "sonnet"],
        ),
        job_id_factory=lambda: "job-console",
    )
    service.mark_running("demo", record.job_id)
    stdout_path = service.store.save_text_artifact(
        "demo",
        record.job_id,
        "stdout.log",
        "provider stdout\n",
    )
    stderr_path = service.store.save_text_artifact(
        "demo",
        record.job_id,
        "stderr.log",
        "",
    )
    completed = service.complete_job(
        "demo",
        record.job_id,
        CodingExecResult(
            jobId=record.job_id,
            provider="claude",
            effectiveCwd="/tmp/worktree/runtime-console",
            status="completed",
            exitCode=0,
            summary="Runtime console CLI implemented",
            responseText="structured result",
        ),
        artifact_paths={
            "stdoutLog": stdout_path,
            "stderrLog": stderr_path,
        },
    )
    task_store.record_coding_callback(
        task.id,
        WorkerCodingCallbackReport.from_coding_result(
            task_id=task.id,
            job_id=completed.job_id,
            session_id=completed.provider_session_ref,
            provider_session_id=completed.provider_session_id,
            worker_name=completed.worker_name,
            provider=completed.provider.value,
            status=completed.state.value,
            decision=WorkerCodingDecision.report_progress,
            summary="Reported progress back to leader.",
            artifact_paths=completed.artifact_paths,
            next_step="Run verification",
        ),
    )

    runtime_store = RuntimeConsoleStore()
    runtime_store.save_fault(
        RuntimeFaultRecord(
            faultId="fault-runtime-1",
            faultType="session_ephemeral",
            severity="warning",
            scopeType="provider_session",
            scopeId=completed.provider_session_ref,
            teamName="demo",
            message="Provider session metadata is unavailable; using ephemeral mode.",
            suggestedAction="Treat provider session id as unavailable in operator surfaces.",
        )
    )
    return task, completed


def test_runtime_console_cli_json_commands(monkeypatch, tmp_path):
    task, completed = _seed_runtime_console(tmp_path, monkeypatch)
    runner = CliRunner()
    env = {"CLAWTEAM_DATA_DIR": str(tmp_path)}

    result = runner.invoke(app, ["--json", "coding", "list", "--team", "demo"], env=env)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["teamName"] == "demo"
    assert payload["jobs"][0]["jobId"] == completed.job_id

    result = runner.invoke(app, ["--json", "coding", "result", completed.job_id, "--team", "demo"], env=env)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["jobId"] == completed.job_id
    assert payload["status"] == "completed"

    result = runner.invoke(app, ["--json", "coding", "events", completed.job_id, "--team", "demo"], env=env)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["jobId"] == completed.job_id
    assert [event["eventType"] for event in payload["events"]] == ["created", "started", "completed"]

    result = runner.invoke(app, ["--json", "coding", "artifacts", completed.job_id, "--team", "demo"], env=env)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    artifact_names = {artifact["name"] for artifact in payload["artifacts"]}
    assert {"jobRecord", "resultJson", "stdoutLog", "stderrLog"} <= artifact_names

    result = runner.invoke(
        app,
        ["--json", "coding", "artifact", completed.job_id, "--name", "stdoutLog", "--team", "demo"],
        env=env,
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["name"] == "stdoutLog"
    assert payload["exists"] is True
    assert payload["content"] == "provider stdout\n"

    result = runner.invoke(app, ["--json", "coding", "session", "list", "--team", "demo"], env=env)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["sessions"][0]["sessionId"] == completed.provider_session_ref
    assert payload["sessions"][0]["sessionMode"] == "ephemeral"
    assert "providerSessionId" not in payload["sessions"][0]

    result = runner.invoke(
        app,
        ["--json", "coding", "session", "show", completed.provider_session_ref, "--team", "demo"],
        env=env,
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["sessionId"] == completed.provider_session_ref
    assert payload["callbackStatus"] == "reported"

    result = runner.invoke(
        app,
        ["--json", "coding", "session", "jobs", completed.provider_session_ref, "--team", "demo"],
        env=env,
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["sessionId"] == completed.provider_session_ref
    assert payload["jobs"][0]["jobId"] == completed.job_id

    result = runner.invoke(
        app,
        ["--json", "coding", "session", "events", completed.provider_session_ref, "--team", "demo"],
        env=env,
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["sessionId"] == completed.provider_session_ref
    assert any(event["eventType"] == "provider_session_attached" for event in payload["events"])

    result = runner.invoke(app, ["--json", "faults", "list", "--team", "demo"], env=env)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["faults"][0]["faultId"] == "fault-runtime-1"

    result = runner.invoke(app, ["--json", "faults", "show", "fault-runtime-1", "--team", "demo"], env=env)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["scopeId"] == completed.provider_session_ref

    result = runner.invoke(app, ["--json", "audit", "timeline", "--team", "demo"], env=env)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["teamName"] == "demo"
    assert any(event["eventType"] == "callback_reported" for event in payload["events"])
    assert any(event["links"].get("taskId") == task.id for event in payload["events"])


def test_runtime_console_session_show_human_output_marks_ephemeral_unavailable(monkeypatch, tmp_path):
    _, completed = _seed_runtime_console(tmp_path, monkeypatch)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["coding", "session", "show", completed.provider_session_ref, "--team", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0
    assert f"Session: {completed.provider_session_ref}" in result.stdout
    assert "Provider Session ID: unavailable" in result.stdout
    assert "Session Mode: ephemeral" in result.stdout
    assert "Resume Supported: no" in result.stdout
