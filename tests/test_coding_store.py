"""Phase 1 tests for durable coding store behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawteam.coding.models import (
    CodingEventType,
    CodingExecResult,
    CodingJobEvent,
    CodingJobRecord,
    CodingJobState,
    CodingProvider,
    ResolvedStartupPolicy,
)
from clawteam.coding.store import (
    CodingJobStore,
    CodingStoreAggregateReadError,
    CodingStoreCorruptionError,
    CodingStoreSchemaError,
)


def _job_record() -> CodingJobRecord:
    return CodingJobRecord(
        jobId="job-1",
        teamName="alpha",
        workerName="worker-1",
        workerId="worker-id-1",
        provider="claude",
        state="queued",
        requestedCwd="/tmp/project",
        workerWorkspaceCwd="/tmp/project",
        workerRuntimeCwd="/tmp/runtime",
        effectiveCwd="/tmp/project",
        startupPolicy=ResolvedStartupPolicy(
            skipProviderPermissions=True,
            appliedFlags=["--dangerously-skip-permissions"],
        ),
        artifactPaths={},
        request={"prompt": "Implement feature"},
    )


class TestCodingJobStore:
    def test_create_and_load_job(self):
        store = CodingJobStore()
        record = _job_record()

        store.create_job(record)
        loaded = store.get_job("alpha", "job-1")
        persisted = json.loads(store.job_path("alpha", "job-1").read_text(encoding="utf-8"))

        assert loaded is not None
        assert persisted["schemaVersion"] == 1
        assert loaded.job_id == "job-1"
        assert loaded.effective_cwd == "/tmp/project"
        assert loaded.startup_policy.applied_flags == ["--dangerously-skip-permissions"]

    def test_append_and_list_events(self):
        store = CodingJobStore()
        event = CodingJobEvent(
            eventId="evt-1",
            jobId="job-1",
            teamName="alpha",
            workerName="worker-1",
            eventType=CodingEventType.created,
            state=CodingJobState.queued,
        )

        store.append_event(event)
        events = store.list_events("alpha", "job-1")
        event_path = next(
            (
                store.job_path("alpha", "job-1").parent.parent.parent
                / "events"
                / "alpha"
                / "job-1"
            ).glob("*.json"),
            None,
        )

        assert len(events) == 1
        assert events[0].event_id == "evt-1"
        assert events[0].state == CodingJobState.queued
        assert event_path is not None
        assert json.loads(event_path.read_text(encoding="utf-8"))["schemaVersion"] == 1

    def test_save_and_load_result(self):
        store = CodingJobStore()
        result = CodingExecResult(
            jobId="job-1",
            provider=CodingProvider.claude,
            effectiveCwd="/tmp/project",
            status=CodingJobState.completed,
            summary="Implemented feature",
        )

        path = store.save_result("alpha", "job-1", result)
        loaded = store.load_result("alpha", "job-1")
        persisted = json.loads(Path(path).read_text(encoding="utf-8"))

        assert loaded is not None
        assert persisted["schemaVersion"] == 1
        assert loaded.summary == "Implemented feature"
        assert Path(path).exists()

    def test_save_text_and_json_artifacts(self):
        store = CodingJobStore()

        text_path = store.save_text_artifact("alpha", "job-1", "stdout.log", "output")
        json_path = store.save_json_artifact("alpha", "job-1", "summary.json", {"ok": True})

        assert Path(text_path).read_text(encoding="utf-8") == "output"
        assert json.loads(Path(json_path).read_text(encoding="utf-8")) == {"ok": True}

    def test_list_jobs_returns_all_valid_records(self):
        store = CodingJobStore()
        store.create_job(_job_record())
        store.create_job(_job_record().model_copy(update={"job_id": "job-2"}))

        jobs = store.list_jobs("alpha")

        assert [job.job_id for job in jobs] == ["job-1", "job-2"]

    def test_get_job_raises_corruption_error_for_malformed_json(self):
        store = CodingJobStore()
        path = store.job_path("alpha", "job-bad")
        path.write_text("{not-json", encoding="utf-8")

        with pytest.raises(CodingStoreCorruptionError, match="corrupt"):
            store.get_job("alpha", "job-bad")

    def test_get_job_raises_schema_error_for_incompatible_version(self):
        store = CodingJobStore()
        path = store.job_path("alpha", "job-future")
        payload = json.loads(_job_record().model_dump_json(by_alias=True))
        payload["jobId"] = "job-future"
        payload["schemaVersion"] = 99
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(CodingStoreSchemaError, match="schema"):
            store.get_job("alpha", "job-future")

    def test_list_jobs_raises_aggregate_error_and_keeps_valid_records(self):
        store = CodingJobStore()
        store.create_job(_job_record())
        bad_path = store.job_path("alpha", "job-bad")
        bad_path.write_text("{bad-json", encoding="utf-8")

        with pytest.raises(CodingStoreAggregateReadError) as exc_info:
            store.list_jobs("alpha")

        assert [job.job_id for job in exc_info.value.records] == ["job-1"]
        assert len(exc_info.value.errors) == 1
        assert exc_info.value.errors[0].fault_type == "corrupt_record"
