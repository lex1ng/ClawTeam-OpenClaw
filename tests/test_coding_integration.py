"""Integration tests for coding CLI commands backed by durable job state."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.coding import CodingExecRequest, CodingService
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import WorkerCodingCallbackReport, WorkerCodingDecision
from clawteam.team.tasks import TaskStore


def _structured_output(summary: str, response_text: str) -> str:
    payload = json.dumps(
        {
            "summary": summary,
            "responseText": response_text,
            "nextSuggestion": "verify",
            "signals": {"needsReview": False},
        }
    )
    return (
        "CLAWTEAM_RESULT_JSON_START\n"
        f"{payload}\n"
        "CLAWTEAM_RESULT_JSON_END\n"
    )


def test_coding_exec_and_status_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "worker1")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "worker-001")
    monkeypatch.setenv("CLAWTEAM_WORKSPACE_DIR", "/tmp/worktree")
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    class Result:
        returncode = 0
        stdout = _structured_output("Implemented callback runtime", "Patch complete")
        stderr = ""

    monkeypatch.setattr("clawteam.coding.harness.base.shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr("clawteam.coding.harness.base.subprocess.run", lambda *a, **k: Result())

    runner = CliRunner()
    exec_result = runner.invoke(
        app,
        ["--json", "coding", "exec", "claude", "Implement callback runtime"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert exec_result.exit_code == 0
    result_payload = json.loads(exec_result.stdout)
    assert result_payload["status"] == "completed"
    job_id = result_payload["jobId"]

    status_result = runner.invoke(
        app,
        ["--json", "coding", "status", job_id, "--team", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert status_result.exit_code == 0
    status_payload = json.loads(status_result.stdout)
    assert status_payload["jobId"] == job_id
    assert status_payload["state"] == "completed"
    assert status_payload["summary"] == "Implemented callback runtime"


def test_coding_wait_cancel_retry_and_replay_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "worker1")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "worker-001")
    monkeypatch.setenv("CLAWTEAM_WORKSPACE_DIR", "/tmp/worktree")
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    service = CodingService()
    queued_job = service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            provider="claude",
            prompt="Queued job",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-queued",
    )

    runner = CliRunner()
    cancel_result = runner.invoke(
        app,
        ["--json", "coding", "cancel", queued_job.job_id, "--team", "demo", "--reason", "operator stop"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )
    assert cancel_result.exit_code == 0
    cancel_payload = json.loads(cancel_result.stdout)
    assert cancel_payload["state"] == "cancelled"

    wait_result = runner.invoke(
        app,
        ["--json", "coding", "wait", queued_job.job_id, "--team", "demo", "--timeout", "0.1"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )
    assert wait_result.exit_code == 0
    wait_payload = json.loads(wait_result.stdout)
    assert wait_payload["state"] == "cancelled"

    class RetryFailure:
        returncode = 2
        stdout = "partial"
        stderr = "transient launch failure"

    class ReplaySuccess:
        returncode = 0
        stdout = _structured_output("Replayed successfully", "usable summary")
        stderr = ""

    responses = [RetryFailure(), ReplaySuccess(), ReplaySuccess()]
    monkeypatch.setattr("clawteam.coding.harness.base.shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(
        "clawteam.coding.harness.base.subprocess.run",
        lambda *a, **k: responses.pop(0),
    )

    failed_result = runner.invoke(
        app,
        ["--json", "coding", "exec", "claude", "Fail once", "--team", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )
    assert failed_result.exit_code == 0
    failed_payload = json.loads(failed_result.stdout)
    assert failed_payload["status"] == "failed"

    retry_result = runner.invoke(
        app,
        ["--json", "coding", "retry", failed_payload["jobId"], "--team", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )
    assert retry_result.exit_code == 0
    retry_payload = json.loads(retry_result.stdout)
    assert retry_payload["status"] == "completed"

    replay_result = runner.invoke(
        app,
        ["--json", "coding", "replay", retry_payload["jobId"], "--team", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )
    assert replay_result.exit_code == 0
    replay_payload = json.loads(replay_result.stdout)
    assert replay_payload["status"] == "completed"

    replay_record = service.require_job("demo", replay_payload["jobId"])
    assert replay_record.parent_job_id == retry_payload["jobId"]
    assert replay_record.replay_count == 1


def test_worker_callback_report_is_summarized_and_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    task_store = TaskStore("demo")
    task = task_store.create("Implement callback runtime", owner="worker1")

    class Result:
        returncode = 0
        stdout = (
            "RAW PROVIDER TRANSCRIPT\nlots of detailed text\n"
            + _structured_output(
                "Implemented callback runtime",
                "Stored artifacts and patch summary",
            )
        )
        stderr = ""

    monkeypatch.setattr("clawteam.coding.harness.base.shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr("clawteam.coding.harness.base.subprocess.run", lambda *a, **k: Result())

    service = CodingService()
    result = service.execute(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            leaderName="leader",
            taskId=task.id,
            provider="claude",
            prompt="Implement callback runtime",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-summary",
    )

    report = WorkerCodingCallbackReport.from_coding_result(
        task_id=task.id,
        job_id=result.job_id,
        provider=result.provider.value,
        status=result.status.value,
        decision=WorkerCodingDecision.report_progress,
        summary="Implemented callback runtime and stored artifacts for review.",
        artifact_paths=result.artifacts,
        next_step="Run task-level verification and notify leader.",
    )
    updated_task = task_store.record_coding_callback(task.id, report)
    mailbox = MailboxManager("demo")
    mailbox.send(
        from_agent="worker1",
        to="leader",
        content=report.to_leader_summary(),
    )

    assert updated_task is not None
    assert updated_task.metadata["coding"]["latestJobId"] == "job-summary"
    assert updated_task.metadata["coding"]["decision"] == "report_progress"
    leader_msg = mailbox.peek("leader")[0].content
    assert "job=job-summary" in leader_msg
    assert "decision=report_progress" in leader_msg
    assert "RAW PROVIDER TRANSCRIPT" not in leader_msg


def test_coding_status_cli_surfaces_corrupt_job_record(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    service = CodingService()
    broken_path = service.store.job_path("demo", "job-bad")
    broken_path.write_text("{bad-json", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["--json", "coding", "status", "job-bad", "--team", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert "corrupt" in payload["error"]


def test_coding_status_human_output_includes_runtime_audit_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    service = CodingService()
    service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            leaderName="leader",
            taskId="task-77",
            provider="claude",
            prompt="Queued job",
            cwd="/tmp/worktree/subdir",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
            providerArgs=["--model", "sonnet"],
        ),
        job_id_factory=lambda: "job-audit",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["coding", "status", "job-audit", "--team", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0
    assert "Task: task-77" in result.stdout
    assert "Leader: leader" in result.stdout
    assert "Attempt: initial  retry=0  replay=0" in result.stdout
    assert "Requested CWD: /tmp/worktree/subdir" in result.stdout
    assert "Effective CWD: /tmp/worktree/subdir" in result.stdout
    assert "Startup Policy: source=provider_default  skipProviderPermissions=True" in result.stdout
    assert "--dangerously-skip-permissions: enabled" in result.stdout
    assert 'Applied Flags: ["--dangerously-skip-permissions"]' in result.stdout
    assert 'Extra Args: ["--model", "sonnet"]' in result.stdout


def test_coding_callback_report_cli_persists_runtime_console_callback(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "worker1")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "worker-001")
    monkeypatch.setenv("CLAWTEAM_WORKSPACE_DIR", "/tmp/worktree")
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    task_store = TaskStore("demo")
    task = task_store.create("Implement callback runtime", owner="worker1")

    class Result:
        returncode = 0
        stdout = _structured_output("Implemented callback runtime", "Patch complete")
        stderr = ""

    monkeypatch.setattr("clawteam.coding.harness.base.shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr("clawteam.coding.harness.base.subprocess.run", lambda *a, **k: Result())

    runner = CliRunner()
    exec_result = runner.invoke(
        app,
        ["--json", "coding", "exec", "claude", "Implement callback runtime", "--team", "demo", "--task-id", task.id],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )
    assert exec_result.exit_code == 0
    exec_payload = json.loads(exec_result.stdout)

    callback_result = runner.invoke(
        app,
        [
            "--json",
            "coding",
            "callback-report",
            exec_payload["jobId"],
            "--team",
            "demo",
            "--decision",
            "report_progress",
            "--summary",
            "Implemented callback runtime",
            "--next-step",
            "notify leader",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )
    assert callback_result.exit_code == 0
    callback_payload = json.loads(callback_result.stdout)
    assert callback_payload["jobId"] == exec_payload["jobId"]
    assert callback_payload["taskId"] == task.id
    assert callback_payload["decision"] == "report_progress"

    board_payload = runner.invoke(
        app,
        ["--json", "board", "show", "demo"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )
    assert board_payload.exit_code == 0
    board_data = json.loads(board_payload.stdout)
    assert board_data["runtimeConsole"]["callbacks"][0]["jobId"] == exec_payload["jobId"]
    assert board_data["runtimeConsole"]["callbacks"][0]["decision"] == "report_progress"
    assert board_data["runtimeConsole"]["callbacks"][0]["summary"] == "Implemented callback runtime"
