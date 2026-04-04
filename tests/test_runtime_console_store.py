"""Phase 1 tests for runtime console durable persistence."""

from __future__ import annotations

from clawteam.runtime_console.models import (
    CallbackReportRecord,
    ProviderSessionRecord,
    RuntimeFaultRecord,
    RuntimeTimelineEvent,
)
from clawteam.runtime_console.store import RuntimeConsoleStore


def test_runtime_console_store_roundtrips_primary_objects():
    store = RuntimeConsoleStore()

    session = store.save_provider_session(
        ProviderSessionRecord(
            sessionId="psess-job-1",
            provider="claude",
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            state="initializing",
            sessionMode="ephemeral",
            resumeSupported=False,
            currentJobId="job-1",
            currentTaskId="task-1",
            effectiveCwd="/tmp/worktree",
        )
    )
    callback = store.save_callback_report(
        CallbackReportRecord(
            teamName="demo",
            taskId="task-1",
            jobId="job-1",
            sessionId="psess-job-1",
            provider="claude",
            status="completed",
            decision="report_progress",
            summary="done",
        )
    )
    fault = store.save_fault(
        RuntimeFaultRecord(
            faultId="fault-1",
            faultType="store_corruption",
            severity="error",
            scopeType="coding_job",
            scopeId="job-1",
            teamName="demo",
            message="corrupt job record",
        )
    )
    event = store.append_timeline_event(
        "demo",
        RuntimeTimelineEvent(
            eventId="evt-1",
            eventType="coding_job_created",
            teamName="demo",
            scopeType="coding_job",
            scopeId="job-1",
            actorType="worker",
            actorId="worker-001",
            summary="job created",
        ),
    )

    assert store.get_provider_session("demo", session.session_id) is not None
    assert store.load_callback_report("demo", callback.job_id) is not None
    assert store.get_fault("demo", fault.fault_id) is not None
    assert store.list_timeline("demo")[0].event_id == event.event_id


def test_runtime_console_store_inspect_methods_surface_corruption_explicitly(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    store = RuntimeConsoleStore()
    store.save_provider_session(
        ProviderSessionRecord(
            sessionId="psess-job-1",
            provider="claude",
            teamName="demo",
            workerName="worker1",
            workerId="worker-001",
            state="initializing",
            sessionMode="ephemeral",
            resumeSupported=False,
            currentJobId="job-1",
            effectiveCwd="/tmp/worktree",
        )
    )
    broken_path = store.provider_session_path("demo", "psess-bad")
    broken_path.write_text("{bad-json", encoding="utf-8")

    sessions, faults = store.inspect_provider_sessions("demo")

    assert len(sessions) == 1
    assert sessions[0].session_id == "psess-job-1"
    assert len(faults) == 1
    assert faults[0]["faultType"] == "corrupt_record"
    assert faults[0]["recordKind"] == "provider_session"
