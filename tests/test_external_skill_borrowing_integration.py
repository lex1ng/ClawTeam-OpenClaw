from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from clawteam.board.collector import BoardCollector
from clawteam.cli.commands import app
from clawteam.coding import CodingExecRequest, CodingExecResult, CodingService
from clawteam.coding.store import CodingJobStore
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskHandoffContract, WorkerCodingCallbackReport, WorkerCodingDecision
from clawteam.team.session_bridge import SessionBridge
from clawteam.team.tasks import TaskStore


def _complete_job(*, team_name: str, worker_name: str, worker_id: str, task_id: str, job_id: str) -> None:
    service = CodingService()
    service.create_job(
        CodingExecRequest(
            teamName=team_name,
            workerName=worker_name,
            workerId=worker_id,
            leaderName="leader",
            taskId=task_id,
            provider="claude",
            prompt="Implement borrowing layer",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: job_id,
    )
    service.mark_running(team_name, job_id)
    service.complete_job(
        team_name,
        job_id,
        CodingExecResult(
            jobId=job_id,
            provider="claude",
            effectiveCwd="/tmp/worktree",
            status="completed",
            summary="done",
        ),
    )


def test_identity_profile_and_session_metadata_are_exposed(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001", product_key="prod-demo")
    TeamManager.add_member(
        "demo",
        "worker1",
        agent_id="worker-001",
        member_nickname="Navigator",
        member_role="backend",
        preferred_session_key="session://demo/worker1",
        session_routing={"preferredSessionKey": "session://demo/worker1", "durableAuthority": "id_session_key"},
    )

    runner = CliRunner()
    result = runner.invoke(app, ["--json", "team", "status", "demo"], env={"CLAWTEAM_DATA_DIR": str(tmp_path)})
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    worker = next(member for member in payload["members"] if member["name"] == "worker1")
    assert worker["memberNickname"] == "Navigator"
    assert worker["memberRole"] == "backend"
    assert worker["preferredSessionKey"] == "session://demo/worker1"
    assert worker["agentId"] == "worker-001"
    assert payload["teamProfileId"]
    assert payload["productKey"] == "prod-demo"

    board = BoardCollector().collect_team("demo")
    board_worker = next(member for member in board["members"] if member["name"] == "worker1")
    assert board_worker["memberNickname"] == "Navigator"
    assert board_worker["memberRole"] == "backend"
    assert board_worker["preferredSessionKey"] == "session://demo/worker1"
    runtime_worker = next(worker for worker in board["runtimeConsole"]["workers"] if worker["name"] == "worker1")
    assert runtime_worker["memberNickname"] == "Navigator"
    assert runtime_worker["memberRole"] == "backend"
    assert runtime_worker["preferredSessionKey"] == "session://demo/worker1"


def test_nickname_uniqueness_and_callback_linkage_remains_machine_facing(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")
    TeamManager.add_member("demo", "worker1", agent_id="worker-001", member_nickname="Scribe")
    with pytest.raises(ValueError, match="Nickname 'Scribe' already exists"):
        TeamManager.add_member("demo", "worker2", agent_id="worker-002", member_nickname="Scribe")

    updated = TeamManager.update_member_profile(
        "demo",
        "worker1",
        member_nickname="Scribe-Renamed",
        preferred_session_key="session://demo/worker1",
    )
    assert updated is not None
    assert updated.member_nickname == "Scribe-Renamed"

    store = TaskStore("demo")
    task = store.create("Machine-facing linkage test", owner="worker1")
    _complete_job(
        team_name="demo",
        worker_name="worker1",
        worker_id="worker-001",
        task_id=task.id,
        job_id="job-machine-link",
    )

    handoff = TaskHandoffContract(
        taskIdentity=task.id,
        objective="Finish linkage test",
        inputs=["task spec"],
        outputs=["resultJson"],
        validation="pytest -q",
        blockers=["none"],
        risks=["low"],
        recommendedNextStep="Leader review",
        callbackExpectation="team_leader_ack",
    )
    report = WorkerCodingCallbackReport.from_coding_result(
        task_id=task.id,
        job_id="job-machine-link",
        session_id="psess-job-machine-link",
        worker_name="worker1",
        provider="claude",
        status="completed",
        decision=WorkerCodingDecision.report_progress,
        summary="callback persisted",
        callback_expectation="team_leader_ack",
        handoff_contract=handoff,
    )
    updated_task = store.record_coding_callback(task.id, report)
    assert updated_task is not None
    assert updated_task.metadata["sessionBridgeNoticeId"]

    notice = SessionBridge().list_notices("demo")[0]
    assert notice.notice_type == "worker_to_team_leader"
    assert notice.from_member_id == updated.member_id
    assert notice.from_session_key == "session://demo/worker1"
    assert notice.task_id == task.id
    assert notice.job_id == "job-machine-link"

    board = BoardCollector().collect_team("demo")
    callback = next(item for item in board["runtimeConsole"]["callbacks"] if item["jobId"] == "job-machine-link")
    assert callback["workerName"] == "worker1"
    assert callback["jobId"] == "job-machine-link"


def test_incomplete_handoff_is_detectable_and_lifecycle_is_distinct_from_callback_state(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")
    TeamManager.add_member("demo", "worker1", agent_id="worker-001")

    store = TaskStore("demo")
    task = store.create("Lifecycle distinction", owner="worker1")
    _complete_job(
        team_name="demo",
        worker_name="worker1",
        worker_id="worker-001",
        task_id=task.id,
        job_id="job-lifecycle",
    )

    incomplete_handoff = TaskHandoffContract(
        taskIdentity=task.id,
        objective="Report progress",
        inputs=[],
        outputs=[],
        validation="",
        blockers=[],
        risks=[],
        recommendedNextStep="",
        callbackExpectation="",
    )
    report = WorkerCodingCallbackReport.from_coding_result(
        task_id=task.id,
        job_id="job-lifecycle",
        worker_name="worker1",
        provider="claude",
        status="completed",
        decision=WorkerCodingDecision.report_progress,
        summary="reported with incomplete handoff",
        handoff_contract=incomplete_handoff,
    )
    updated_task = store.record_coding_callback(task.id, report)
    assert updated_task is not None
    assert updated_task.callback_lifecycle_phase.value == "incomplete"
    assert updated_task.review_lifecycle_phase.value == "pending"
    assert updated_task.task_lifecycle_phase.value == "handoff"
    assert "validation" in updated_task.handoff_missing_fields
    assert "callbackExpectation" in updated_task.handoff_missing_fields

    board = BoardCollector().collect_team("demo")
    chain_row = next(row for row in board["runtimeConsole"]["callbackChain"]["workers"] if row["workerName"] == "worker1")
    assert chain_row["callbackState"] == "reported"
    assert chain_row["callbackLifecyclePhase"] == "incomplete"
    assert chain_row["reviewLifecyclePhase"] == "pending"
    assert chain_row["taskLifecyclePhase"] == "handoff"


def test_session_bridge_binds_member_by_machine_identity_not_ambiguous_name(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")
    alice_member = TeamManager.add_member(
        "demo",
        "worker",
        agent_id="worker-A",
        user="alice",
        member_nickname="alice-worker",
        preferred_session_key="session://alice/worker",
    )
    TeamManager.add_member(
        "demo",
        "worker",
        agent_id="worker-B",
        user="bob",
        member_nickname="bob-worker",
        preferred_session_key="session://bob/worker",
    )

    store = TaskStore("demo")
    task = store.create("Ambiguous worker name callback", owner="worker")
    _complete_job(
        team_name="demo",
        worker_name="worker",
        worker_id="worker-A",
        task_id=task.id,
        job_id="job-ambiguous-worker",
    )
    handoff = TaskHandoffContract(
        taskIdentity=task.id,
        objective="Ensure session bridge binds by machine identity",
        inputs=["task"],
        outputs=["resultJson"],
        validation="pytest -q",
        blockers=["none"],
        risks=["low"],
        recommendedNextStep="leader ack",
        callbackExpectation="team_leader_ack",
    )
    report = WorkerCodingCallbackReport.from_coding_result(
        task_id=task.id,
        job_id="job-ambiguous-worker",
        worker_name="worker",
        provider="claude",
        status="completed",
        decision=WorkerCodingDecision.report_progress,
        summary="callback with ambiguous worker name",
        handoff_contract=handoff,
    )
    updated_task = store.record_coding_callback(task.id, report)
    assert updated_task is not None

    notice = SessionBridge().list_notices("demo")[0]
    assert notice.job_id == "job-ambiguous-worker"
    assert notice.from_member_id == alice_member.member_id
    assert notice.from_agent_id == "worker-A"
    assert notice.from_session_key == "session://alice/worker"


def test_session_bridge_skips_notice_when_machine_identity_missing_and_name_ambiguous(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")
    TeamManager.add_member(
        "demo",
        "worker",
        agent_id="worker-A",
        user="alice",
        member_nickname="alice-worker",
        preferred_session_key="session://alice/worker",
    )
    TeamManager.add_member(
        "demo",
        "worker",
        agent_id="worker-B",
        user="bob",
        member_nickname="bob-worker",
        preferred_session_key="session://bob/worker",
    )

    store = TaskStore("demo")
    task = store.create("Fail-safe ambiguous callback linkage", owner="worker")
    _complete_job(
        team_name="demo",
        worker_name="worker",
        worker_id="worker-A",
        task_id=task.id,
        job_id="job-ambiguous-missing-id",
    )
    job_store = CodingJobStore()
    persisted = job_store.get_job("demo", "job-ambiguous-missing-id")
    assert persisted is not None
    job_store.save_job(persisted.model_copy(update={"worker_id": ""}))

    handoff = TaskHandoffContract(
        taskIdentity=task.id,
        objective="Fail-safe should skip bridge notice",
        inputs=["task"],
        outputs=["resultJson"],
        validation="pytest -q",
        blockers=["none"],
        risks=["low"],
        recommendedNextStep="leader ack",
        callbackExpectation="team_leader_ack",
    )
    report = WorkerCodingCallbackReport.from_coding_result(
        task_id=task.id,
        job_id="job-ambiguous-missing-id",
        worker_name="worker",
        provider="claude",
        status="completed",
        decision=WorkerCodingDecision.report_progress,
        summary="callback with ambiguous name and missing worker_id",
        handoff_contract=handoff,
    )
    updated_task = store.record_coding_callback(task.id, report)
    assert updated_task is not None
    assert "sessionBridgeNoticeId" not in updated_task.metadata
    assert SessionBridge().list_notices("demo") == []
