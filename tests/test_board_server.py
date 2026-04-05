from __future__ import annotations

import json
import threading
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

from clawteam.board.collector import BoardCollector
from clawteam.board.server import BoardHandler
from clawteam.coding import CodingExecRequest, CodingExecResult, CodingService
from clawteam.runtime_console import RuntimeConsoleStore
from clawteam.runtime_console.models import RuntimeFaultRecord
from clawteam.team.manager import TeamManager
from clawteam.team.models import WorkerCodingCallbackReport, WorkerCodingDecision
from clawteam.team.tasks import TaskStore


def _seed_board_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    task_store = TaskStore("demo")
    task = task_store.create("Board API task", owner="worker1")

    service = CodingService()
    record = service.create_job(
        CodingExecRequest(
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            leaderName="leader",
            taskId=task.id,
            provider="claude",
            prompt="Build board API",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-board",
    )
    service.mark_running("demo", record.job_id)
    stdout_path = service.store.save_text_artifact("demo", record.job_id, "stdout.log", "board stdout\n")
    completed = service.complete_job(
        "demo",
        record.job_id,
        CodingExecResult(
            jobId=record.job_id,
            provider="claude",
            effectiveCwd="/tmp/worktree",
            status="completed",
            summary="Board API implemented",
        ),
        artifact_paths={"stdoutLog": stdout_path},
    )
    task_store.record_coding_callback(
        task.id,
        WorkerCodingCallbackReport.from_coding_result(
            task_id=task.id,
            job_id=completed.job_id,
            session_id=completed.provider_session_ref,
            worker_name=completed.worker_name,
            provider=completed.provider.value,
            status=completed.state.value,
            decision=WorkerCodingDecision.report_progress,
            summary="Board callback reported",
            artifact_paths=completed.artifact_paths,
        ),
    )
    RuntimeConsoleStore().save_fault(
        RuntimeFaultRecord(
            faultId="fault-board-1",
            faultType="session_ephemeral",
            severity="warning",
            scopeType="provider_session",
            scopeId=completed.provider_session_ref,
            teamName="demo",
            message="Session metadata unavailable",
        )
    )
    return task, completed


@contextmanager
def _running_board_server():
    BoardHandler.collector = BoardCollector()
    BoardHandler.default_team = ""
    BoardHandler.interval = 0.1
    server = ThreadingHTTPServer(("127.0.0.1", 0), BoardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _get_json(base_url: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base_url}{path}") as response:
        return json.loads(response.read().decode("utf-8"))


def test_board_server_exposes_runtime_console_api(monkeypatch, tmp_path):
    task, completed = _seed_board_runtime(monkeypatch, tmp_path)

    with _running_board_server() as base_url:
        payload = _get_json(base_url, "/api/board/demo")
        assert payload["runtimeConsole"]["jobs"][0]["jobId"] == completed.job_id

        payload = _get_json(base_url, "/api/teams/demo/workers")
        assert payload["workers"][0]["name"] == "leader" or payload["workers"][0]["name"] == "worker1"

        payload = _get_json(base_url, "/api/teams/demo/tasks")
        assert payload["tasks"][0]["id"] == task.id

        payload = _get_json(base_url, "/api/teams/demo/coding/jobs")
        assert payload["jobs"][0]["jobId"] == completed.job_id

        payload = _get_json(base_url, f"/api/teams/demo/coding/jobs/{completed.job_id}")
        assert payload["jobId"] == completed.job_id

        payload = _get_json(base_url, f"/api/teams/demo/coding/jobs/{completed.job_id}/events")
        assert [event["eventType"] for event in payload["events"]] == ["created", "started", "completed"]

        payload = _get_json(base_url, f"/api/teams/demo/coding/jobs/{completed.job_id}/result")
        assert payload["status"] == "completed"

        payload = _get_json(base_url, f"/api/teams/demo/coding/jobs/{completed.job_id}/artifacts")
        assert payload["artifacts"][0]["name"] in {"jobRecord", "resultJson", "stdoutLog"}

        payload = _get_json(base_url, f"/api/teams/demo/coding/jobs/{completed.job_id}/artifacts/stdoutLog")
        assert payload["name"] == "stdoutLog"
        assert payload["content"] == "board stdout\n"
        assert payload["truncated"] is False

        payload = _get_json(base_url, "/api/teams/demo/coding/sessions")
        assert payload["sessions"][0]["sessionId"] == completed.provider_session_ref
        assert payload["sessions"][0]["sessionMode"] == "ephemeral"

        payload = _get_json(base_url, f"/api/teams/demo/coding/sessions/{completed.provider_session_ref}")
        assert payload["sessionId"] == completed.provider_session_ref

        payload = _get_json(base_url, f"/api/teams/demo/coding/sessions/{completed.provider_session_ref}/jobs")
        assert payload["jobs"][0]["jobId"] == completed.job_id

        payload = _get_json(base_url, "/api/teams/demo/callbacks")
        assert payload["callbacks"][0]["jobId"] == completed.job_id

        payload = _get_json(base_url, "/api/teams/demo/faults")
        assert payload["faults"][0]["faultId"] == "fault-board-1"

        payload = _get_json(base_url, "/api/teams/demo/timeline")
        assert any(event["eventType"] == "callback_reported" for event in payload["events"])


def test_board_server_artifact_preview_rejects_paths_outside_job_artifact_root(monkeypatch, tmp_path):
    _, completed = _seed_board_runtime(monkeypatch, tmp_path)

    outside_path = tmp_path / "outside.txt"
    outside_path.write_text("secret\n", encoding="utf-8")

    service = CodingService()
    record = service.store.get_job("demo", completed.job_id)
    assert record is not None
    mutated = record.model_copy(
        update={
            "artifact_paths": {
                **record.artifact_paths,
                "stdoutLog": str(outside_path),
            }
        }
    )
    service.store.save_job(mutated)

    with _running_board_server() as base_url:
        payload = _get_json(base_url, f"/api/teams/demo/coding/jobs/{completed.job_id}/artifacts/stdoutLog")

    assert payload["name"] == "stdoutLog"
    assert payload["path"] == str(outside_path)
    assert payload["content"] is None
    assert payload["unavailableReason"] == "outside_artifact_root"


def test_board_server_tasks_api_surfaces_task_read_faults(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader-001")

    task_store = TaskStore("demo")
    task = task_store.create("healthy task", owner="worker1")
    broken_path = tmp_path / "tasks" / "demo" / "task-bad.json"
    broken_path.parent.mkdir(parents=True, exist_ok=True)
    broken_path.write_text("{bad-json", encoding="utf-8")

    with _running_board_server() as base_url:
        payload = _get_json(base_url, "/api/teams/demo/tasks")

    assert payload["summary"]["total"] == 1
    assert payload["tasks"][0]["id"] == task.id
    assert len(payload["faults"]) == 1
    assert payload["faults"][0]["faultType"] == "corrupt_record"
    assert payload["faults"][0]["recordKind"] == "task"


def test_board_server_board_api_preserves_mixed_fault_surfaces(monkeypatch, tmp_path):
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
            leaderName="leader",
            taskId=task.id,
            provider="claude",
            prompt="Build resilient board payloads",
            workerWorkspaceCwd="/tmp/worktree",
            workerRuntimeCwd="/tmp/runtime",
        ),
        job_id_factory=lambda: "job-board-mixed",
    )
    service.store.job_path("demo", "job-bad").write_text("{bad-json", encoding="utf-8")
    RuntimeConsoleStore().save_fault(
        RuntimeFaultRecord(
            faultId="fault-board-mixed",
            faultType="session_ephemeral",
            severity="warning",
            scopeType="provider_session",
            scopeId=record.provider_session_ref,
            teamName="demo",
            message="Session metadata unavailable",
        )
    )

    with _running_board_server() as base_url:
        payload = _get_json(base_url, "/api/board/demo")

    assert payload["taskSummary"]["total"] == 1
    assert payload["runtimeConsole"]["tasks"][0]["id"] == task.id
    assert len(payload["taskReadFaults"]) == 1
    assert payload["taskReadFaults"][0]["recordKind"] == "task"
    assert len(payload["coding"]["faults"]) == 1
    assert payload["coding"]["faults"][0]["recordKind"] == "job"
    assert len(payload["runtimeConsole"]["faults"]) == 1
    assert payload["runtimeConsole"]["faults"][0]["faultId"] == "fault-board-mixed"
