from __future__ import annotations

import pytest

from tests.smoke.helpers import isolated_smoke_context


DECISION_CASES = [
    {
        "decision": "continue",
        "callback_status": "continue_with_provider",
        "timeline_event": "callback_continued",
        "escalation_reason": None,
    },
    {
        "decision": "report_progress",
        "callback_status": "reported",
        "timeline_event": "callback_reported",
        "escalation_reason": None,
    },
    {
        "decision": "escalate",
        "callback_status": "escalated_to_leader",
        "timeline_event": "callback_escalated",
        "escalation_reason": "needs human approval",
    },
    {
        "decision": "complete",
        "callback_status": "closed",
        "timeline_event": "callback_reported",
        "escalation_reason": None,
    },
    {
        "decision": "blocked",
        "callback_status": "blocked_waiting_decision",
        "timeline_event": "callback_reported",
        "escalation_reason": None,
    },
]


def _seed_completed_job(ctx, *, team_name: str, worker_name: str, subject: str) -> tuple[dict, dict]:
    workspace_dir = ctx.root / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    ctx.env.update(
        {
            "CLAWTEAM_TEAM_NAME": team_name,
            "CLAWTEAM_AGENT_NAME": worker_name,
            "CLAWTEAM_AGENT_ID": "worker-001",
            "CLAWTEAM_WORKSPACE_DIR": str(workspace_dir),
        }
    )
    ctx.run_cli("team", "spawn-team", team_name, "-d", "callback decision matrix", "-n", "leader")
    ctx.register_team(team_name, None)
    task = ctx.run_cli_json("task", "create", team_name, subject, "--owner", worker_name)
    exec_payload = ctx.run_cli_json(
        "coding",
        "exec",
        "claude",
        f"Implement callback decision coverage for {task['id']}",
        "--team",
        team_name,
        "--task-id",
        task["id"],
    )
    return task, exec_payload


@pytest.mark.parametrize(
    "case",
    DECISION_CASES,
    ids=[case["decision"] for case in DECISION_CASES],
)
def test_callback_decision_matrix_updates_all_operator_surfaces(tmp_path, case):
    team_name = f"decision-{case['decision']}"
    summary = f"{case['decision']} summary"
    next_step = f"{case['decision']} next step"

    with isolated_smoke_context(tmp_path, team_name) as ctx:
        task, exec_payload = _seed_completed_job(
            ctx,
            team_name=team_name,
            worker_name="worker1",
            subject=f"{case['decision']} callback matrix",
        )
        args = [
            "coding",
            "callback-report",
            exec_payload["jobId"],
            "--team",
            team_name,
            "--decision",
            case["decision"],
            "--summary",
            summary,
            "--next-step",
            next_step,
        ]
        if case["escalation_reason"]:
            args.extend(["--escalation-reason", case["escalation_reason"]])

        callback_payload = ctx.run_cli_json(*args)
        task_payload = ctx.run_cli_json("task", "get", team_name, task["id"])
        coding_status = ctx.run_cli_json("coding", "status", exec_payload["jobId"], "--team", team_name)
        board_json = ctx.run_cli_json("board", "show", team_name)
        board = ctx.start_board_server(team_name, host="127.0.0.1")
        team_api = ctx.http_get_json(board.base_url, f"/api/team/{team_name}")
        callbacks_api = ctx.http_get_json(board.base_url, f"/api/teams/{team_name}/callbacks")
        timeline_api = ctx.http_get_json(board.base_url, f"/api/teams/{team_name}/timeline")

        coding_meta = task_payload["metadata"]["coding"]
        assert coding_meta["latestJobId"] == exec_payload["jobId"]
        assert coding_meta["provider"] == "claude"
        assert coding_meta["status"] == "completed"
        assert coding_meta["decision"] == case["decision"]
        assert coding_meta["summary"] == summary
        assert coding_meta["artifactPaths"]
        assert coding_meta["reportedAt"]

        assert callback_payload["jobId"] == exec_payload["jobId"]
        assert callback_payload["taskId"] == task["id"]
        assert callback_payload["decision"] == case["decision"]
        if case["escalation_reason"]:
            assert callback_payload["escalationReason"] == case["escalation_reason"]

        assert coding_status["callbackDecision"] == case["decision"]
        assert coding_status["callbackStatus"] == case["callback_status"]
        assert coding_status["callbackReportedAt"]

        callback_record = next(
            callback
            for callback in callbacks_api["callbacks"]
            if callback["jobId"] == exec_payload["jobId"]
        )
        assert callback_record["taskId"] == task["id"]
        assert callback_record["decision"] == case["decision"]
        assert callback_record["summary"] == summary
        assert callback_record["nextStep"] == next_step
        assert callback_record["status"] == "completed"
        assert callback_record["artifactPaths"]
        if case["escalation_reason"]:
            assert callback_record["escalationReason"] == case["escalation_reason"]

        timeline_event = next(
            event
            for event in timeline_api["events"]
            if event["scopeType"] == "callback" and event["scopeId"] == exec_payload["jobId"]
        )
        assert timeline_event["eventType"] == case["timeline_event"]
        assert timeline_event["links"]["jobId"] == exec_payload["jobId"]
        assert timeline_event["links"]["taskId"] == task["id"]

        board_job = next(
            job
            for job in board_json["runtimeConsole"]["jobs"]
            if job["jobId"] == exec_payload["jobId"]
        )
        board_callback = next(
            callback
            for callback in board_json["runtimeConsole"]["callbacks"]
            if callback["jobId"] == exec_payload["jobId"]
        )
        board_task = next(
            item
            for item in board_json["runtimeConsole"]["tasks"]
            if item["id"] == task["id"]
        )
        assert board_job["callbackDecision"] == case["decision"]
        assert board_job["callbackStatus"] == case["callback_status"]
        assert board_callback["decision"] == case["decision"]
        assert board_callback["summary"] == summary
        assert board_task["metadata"]["coding"]["decision"] == case["decision"]
        assert team_api["runtimeConsole"]["callbacks"][0]["jobId"] == exec_payload["jobId"]


def test_callback_report_rejects_non_terminal_job(tmp_path, monkeypatch):
    from clawteam.coding import CodingExecRequest, CodingService

    with isolated_smoke_context(tmp_path, "callback-non-terminal") as ctx:
        monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(ctx.data_dir))
        ctx.run_cli("team", "spawn-team", "demo", "-d", "callback non-terminal", "-n", "leader")
        ctx.register_team("demo", None)
        task = ctx.run_cli_json("task", "create", "demo", "queued callback", "--owner", "worker1")
        job = CodingService().create_job(
            CodingExecRequest(
                teamName="demo",
                workerName="worker1",
                workerId="worker-001",
                leaderName="leader",
                taskId=task["id"],
                provider="claude",
                prompt="queued callback",
                workerRuntimeCwd=str(ctx.root),
                workerWorkspaceCwd=str(ctx.root),
            ),
            job_id_factory=lambda: "job-non-terminal",
        )

        result = ctx.run_cli(
            "coding",
            "callback-report",
            job.job_id,
            "--team",
            "demo",
            "--decision",
            "report_progress",
            check=False,
        )

        assert result.returncode != 0
        assert "is not terminal yet" in result.stdout


def test_callback_report_rejects_missing_task_linkage(tmp_path, monkeypatch):
    from clawteam.coding import CodingExecRequest, CodingExecResult, CodingService

    with isolated_smoke_context(tmp_path, "callback-missing-task-linkage") as ctx:
        monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(ctx.data_dir))
        ctx.run_cli("team", "spawn-team", "demo", "-d", "missing task linkage", "-n", "leader")
        ctx.register_team("demo", None)
        service = CodingService()
        record = service.create_job(
            CodingExecRequest(
                teamName="demo",
                workerName="worker1",
                workerId="worker-001",
                leaderName="leader",
                provider="claude",
                prompt="missing task linkage",
                workerRuntimeCwd=str(ctx.root),
                workerWorkspaceCwd=str(ctx.root),
            ),
            job_id_factory=lambda: "job-no-task",
        )
        service.mark_running("demo", record.job_id)
        service.complete_job(
            "demo",
            record.job_id,
            CodingExecResult(
                jobId=record.job_id,
                provider="claude",
                effectiveCwd=str(ctx.root),
                status="completed",
                exitCode=0,
                summary="done",
                responseText="done",
            ),
        )

        result = ctx.run_cli(
            "coding",
            "callback-report",
            record.job_id,
            "--team",
            "demo",
            "--decision",
            "report_progress",
            check=False,
        )

        assert result.returncode != 0
        assert "has no task linkage" in result.stdout


def test_callback_report_rejects_invalid_decision(tmp_path):
    with isolated_smoke_context(tmp_path, "callback-invalid-decision") as ctx:
        task, exec_payload = _seed_completed_job(
            ctx,
            team_name="demo",
            worker_name="worker1",
            subject="invalid decision callback",
        )

        result = ctx.run_cli(
            "coding",
            "callback-report",
            exec_payload["jobId"],
            "--team",
            "demo",
            "--decision",
            "nonsense",
            check=False,
        )

        assert task["id"]
        assert result.returncode != 0
        assert "Decision must be one of" in result.stdout


def test_callback_report_rejects_escalate_without_reason(tmp_path):
    with isolated_smoke_context(tmp_path, "callback-escalate-no-reason") as ctx:
        _, exec_payload = _seed_completed_job(
            ctx,
            team_name="demo",
            worker_name="worker1",
            subject="escalate callback",
        )

        result = ctx.run_cli(
            "coding",
            "callback-report",
            exec_payload["jobId"],
            "--team",
            "demo",
            "--decision",
            "escalate",
            check=False,
        )

        assert result.returncode != 0
        assert "Escalation callbacks require --escalation-reason." in result.stdout
