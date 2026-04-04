"""Phase 1 tests for coding runtime core service behavior."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from clawteam.coding.harness.base import HarnessArtifact, HarnessExecution
from clawteam.coding.models import (
    CodingAttemptKind,
    CodingExecRequest,
    CodingExecResult,
    CodingJobState,
    CodingProvider,
)
from clawteam.coding.registry import CodingHarnessRegistry
from clawteam.coding.service import CodingJobConflictError, CodingJobNotFoundError, CodingService
from clawteam.coding.store import CodingJobStore
from clawteam.runtime_console import RuntimeConsoleStore


def _request(**overrides) -> CodingExecRequest:
    data = {
        "teamName": "alpha",
        "workerName": "worker-1",
        "workerId": "worker-id-1",
        "leaderName": "leader",
        "taskId": "task-1",
        "provider": "claude",
        "mode": "implement",
        "prompt": "Implement the runtime core",
        "cwd": None,
        "workerWorkspaceCwd": "/tmp/worktree",
        "workerRuntimeCwd": "/tmp/runtime",
        "providerArgs": ["--verbose"],
    }
    data.update(overrides)
    return CodingExecRequest(**data)


class TestCodingService:
    def test_create_job_persists_resolved_cwd_and_startup_policy(self):
        service = CodingService()
        request = _request(skipProviderPermissions=None)

        record = service.create_job(request, job_id_factory=lambda: "job-fixed")

        assert record.job_id == "job-fixed"
        assert record.state == CodingJobState.queued
        assert record.requested_cwd is None
        assert record.effective_cwd == "/tmp/worktree"
        assert record.startup_policy.applied_flags == ["--dangerously-skip-permissions"]
        assert record.provider_session_ref == "psess-job-fixed"
        assert record.provider_session_id is None
        assert record.session_mode.value == "ephemeral"
        assert Path(record.artifact_paths["jobRecord"]).exists()
        provider_session = RuntimeConsoleStore().get_provider_session("alpha", "psess-job-fixed")
        assert provider_session is not None
        assert provider_session.provider_session_id is None
        assert provider_session.session_mode.value == "ephemeral"
        assert provider_session.resume_supported is False
        events = service.store.list_events("alpha", "job-fixed")
        assert [event.event_type.value for event in events] == ["created"]

    def test_mark_running_enforces_state_transition(self):
        service = CodingService()
        service.create_job(_request(), job_id_factory=lambda: "job-fixed")

        updated = service.mark_running("alpha", "job-fixed")

        assert updated.state == CodingJobState.running
        assert updated.started_at is not None
        events = service.store.list_events("alpha", "job-fixed")
        assert [event.event_type.value for event in events] == ["created", "started"]

    def test_complete_job_persists_terminal_result_and_artifacts(self):
        service = CodingService()
        service.create_job(_request(), job_id_factory=lambda: "job-fixed")
        service.mark_running("alpha", "job-fixed")
        result = CodingExecResult(
            jobId="job-fixed",
            provider="claude",
            effectiveCwd="/tmp/worktree",
            status="completed",
            exitCode=0,
            summary="Implemented runtime core",
        )

        updated = service.complete_job(
            "alpha",
            "job-fixed",
            result,
            artifact_paths={"stdoutLog": "/tmp/fake.log"},
        )

        assert updated.state == CodingJobState.completed
        assert updated.summary == "Implemented runtime core"
        assert updated.result is not None
        assert "resultJson" in updated.artifact_paths
        assert updated.artifact_paths["stdoutLog"] == "/tmp/fake.log"
        loaded_result = service.store.load_result("alpha", "job-fixed")
        assert loaded_result is not None
        assert loaded_result.status == CodingJobState.completed

    def test_invalid_terminal_transition_fails_explicitly(self):
        service = CodingService()
        service.create_job(_request(), job_id_factory=lambda: "job-fixed")
        result = CodingExecResult(
            jobId="job-fixed",
            provider="claude",
            effectiveCwd="/tmp/worktree",
            status="completed",
        )

        with pytest.raises(ValueError, match="Invalid coding job transition"):
            service.complete_job("alpha", "job-fixed", result)

    def test_retry_and_replay_create_new_attempt_records_with_distinct_semantics(self):
        service = CodingService()
        service.create_job(_request(), job_id_factory=lambda: "job-1")
        service.mark_running("alpha", "job-1")
        failed_result = CodingExecResult(
            jobId="job-1",
            provider="claude",
            effectiveCwd="/tmp/worktree",
            status="failed",
            exitCode=2,
            error="launch failed",
        )
        service.complete_job("alpha", "job-1", failed_result)

        retry_record = service.create_retry_job(
            "alpha",
            "job-1",
            job_id_factory=lambda: "job-2",
        )

        assert retry_record.parent_job_id == "job-1"
        assert retry_record.root_job_id == "job-1"
        assert retry_record.attempt_kind == CodingAttemptKind.retry
        assert retry_record.retry_count == 1
        assert retry_record.replay_count == 0

        service.mark_running("alpha", "job-2")
        completed_retry = CodingExecResult(
            jobId="job-2",
            provider="claude",
            effectiveCwd="/tmp/worktree",
            status="completed",
            summary="done",
        )
        service.complete_job("alpha", "job-2", completed_retry)

        replay_record = service.create_replay_job(
            "alpha",
            "job-2",
            job_id_factory=lambda: "job-3",
        )

        assert replay_record.parent_job_id == "job-2"
        assert replay_record.root_job_id == "job-1"
        assert replay_record.attempt_kind == CodingAttemptKind.replay
        assert replay_record.retry_count == 0
        assert replay_record.replay_count == 1

    def test_require_job_raises_for_missing_record(self):
        service = CodingService()

        with pytest.raises(CodingJobNotFoundError, match="not found"):
            service.require_job("alpha", "missing-job")

    def test_v1_rejects_second_active_job_for_same_worker(self):
        service = CodingService()
        service.create_job(_request(taskId="task-1"), job_id_factory=lambda: "job-1")

        with pytest.raises(CodingJobConflictError, match="one active coding job per worker"):
            service.create_job(_request(taskId="task-2"), job_id_factory=lambda: "job-2")

    def test_v1_rejects_second_active_job_for_same_task(self):
        service = CodingService()
        service.create_job(_request(taskId="task-1"), job_id_factory=lambda: "job-1")

        with pytest.raises(CodingJobConflictError, match="one active coding job per task"):
            service.create_job(
                _request(workerName="worker-2", workerId="worker-id-2", taskId="task-1"),
                job_id_factory=lambda: "job-2",
            )

    def test_concurrent_create_for_same_worker_is_atomic(self):
        class CoordinatedStore(CodingJobStore):
            def __init__(self):
                super().__init__()
                self.first_inside_atomic_create = threading.Event()
                self.release_first_create = threading.Event()
                self.atomic_persist_hook_calls = 0
                self._hook_lock = threading.Lock()

            def _before_atomic_create_persist(self, *, record, existing_jobs):
                with self._hook_lock:
                    self.atomic_persist_hook_calls += 1
                    is_first = self.atomic_persist_hook_calls == 1
                if is_first:
                    self.first_inside_atomic_create.set()
                    assert self.release_first_create.wait(timeout=2)

        store = CoordinatedStore()
        service = CodingService(store=store)
        successes: list[str] = []
        failures: list[Exception] = []
        result_lock = threading.Lock()
        second_attempt_started = threading.Event()

        def create(job_id: str, task_id: str):
            try:
                service.create_job(_request(taskId=task_id), job_id_factory=lambda: job_id)
                with result_lock:
                    successes.append(job_id)
            except Exception as exc:
                with result_lock:
                    failures.append(exc)

        first = threading.Thread(target=create, args=("job-1", "task-1"))
        second = threading.Thread(
            target=lambda: (
                second_attempt_started.set(),
                create("job-2", "task-2"),
            ),
        )
        first.start()
        assert store.first_inside_atomic_create.wait(timeout=2)
        second.start()
        assert second_attempt_started.wait(timeout=2)
        store.release_first_create.set()
        first.join(timeout=2)
        second.join(timeout=2)

        assert not first.is_alive()
        assert not second.is_alive()
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], CodingJobConflictError)
        assert store.atomic_persist_hook_calls == 1
        jobs = service.store.list_jobs("alpha")
        assert [job.job_id for job in jobs] == successes

    def test_concurrent_create_for_same_task_is_atomic(self):
        class CoordinatedStore(CodingJobStore):
            def __init__(self):
                super().__init__()
                self.first_inside_atomic_create = threading.Event()
                self.release_first_create = threading.Event()
                self.atomic_persist_hook_calls = 0
                self._hook_lock = threading.Lock()

            def _before_atomic_create_persist(self, *, record, existing_jobs):
                with self._hook_lock:
                    self.atomic_persist_hook_calls += 1
                    is_first = self.atomic_persist_hook_calls == 1
                if is_first:
                    self.first_inside_atomic_create.set()
                    assert self.release_first_create.wait(timeout=2)

        store = CoordinatedStore()
        service = CodingService(store=store)
        successes: list[str] = []
        failures: list[Exception] = []
        result_lock = threading.Lock()
        second_attempt_started = threading.Event()

        def create(job_id: str, worker_name: str, worker_id: str):
            try:
                service.create_job(
                    _request(taskId="shared-task", workerName=worker_name, workerId=worker_id),
                    job_id_factory=lambda: job_id,
                )
                with result_lock:
                    successes.append(job_id)
            except Exception as exc:
                with result_lock:
                    failures.append(exc)

        first = threading.Thread(target=create, args=("job-1", "worker-1", "worker-id-1"))
        second = threading.Thread(
            target=lambda: (
                second_attempt_started.set(),
                create("job-2", "worker-2", "worker-id-2"),
            ),
        )
        first.start()
        assert store.first_inside_atomic_create.wait(timeout=2)
        second.start()
        assert second_attempt_started.wait(timeout=2)
        store.release_first_create.set()
        first.join(timeout=2)
        second.join(timeout=2)

        assert not first.is_alive()
        assert not second.is_alive()
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], CodingJobConflictError)
        assert store.atomic_persist_hook_calls == 1
        jobs = service.store.list_jobs("alpha")
        assert [job.task_id for job in jobs] == ["shared-task"]

    def test_execute_runs_provider_via_registry_and_persists_artifacts(self):
        registry = CodingHarnessRegistry()

        class FakeHarness:
            provider = CodingProvider.claude

            def exec(self, job_id, request, effective_cwd, startup_policy):
                assert job_id == "job-fixed"
                assert effective_cwd == "/tmp/worktree"
                return HarnessExecution(
                    result=CodingExecResult(
                        jobId=job_id,
                        provider=request.provider,
                        effectiveCwd=effective_cwd,
                        status="completed",
                        summary="Executed through service",
                        artifacts={"stdoutLog": "stdout.log"},
                    ),
                    command=["claude", "-p", request.prompt],
                    artifactPayloads={
                        "stdoutLog": HarnessArtifact(
                            filename="stdout.log",
                            contentType="text/plain",
                            text="provider stdout",
                        )
                    },
                )

        registry.register(CodingProvider.claude, FakeHarness())
        service = CodingService(registry=registry)

        result = service.execute(_request(), job_id_factory=lambda: "job-fixed")

        assert result.status == CodingJobState.completed
        assert Path(result.artifacts["stdoutLog"]).exists()
        record = service.require_job("alpha", "job-fixed")
        assert record.state == CodingJobState.completed
        assert record.summary == "Executed through service"
        assert record.result is not None
        events = service.store.list_events("alpha", "job-fixed")
        assert [event.event_type.value for event in events] == [
            "created",
            "started",
            "completed",
        ]

    def test_execute_distinguishes_service_failure_from_provider_failure(self):
        registry = CodingHarnessRegistry()

        class ExplodingHarness:
            provider = CodingProvider.claude

            def exec(self, job_id, request, effective_cwd, startup_policy):
                raise RuntimeError("unexpected harness crash")

        registry.register(CodingProvider.claude, ExplodingHarness())
        service = CodingService(registry=registry)

        result = service.execute(_request(), job_id_factory=lambda: "job-fixed")

        assert result.status == CodingJobState.failed
        assert result.metrics["failureKind"] == "service"
        assert result.error == "service failure: unexpected harness crash"
        record = service.require_job("alpha", "job-fixed")
        assert record.state == CodingJobState.failed
        assert "serviceError" in record.artifact_paths

    def test_execute_marks_job_failed_when_result_persistence_fails(self):
        registry = CodingHarnessRegistry()

        class FakeHarness:
            provider = CodingProvider.claude

            def exec(self, job_id, request, effective_cwd, startup_policy):
                return HarnessExecution(
                    result=CodingExecResult(
                        jobId=job_id,
                        provider=request.provider,
                        effectiveCwd=effective_cwd,
                        status="completed",
                        summary="Completed before persistence failure",
                    ),
                    command=["claude"],
                    artifactPayloads={},
                )

        registry.register(CodingProvider.claude, FakeHarness())
        service = CodingService(registry=registry)
        original_save_result = service.store.save_result

        def fail_save_result(team_name, job_id, result):
            raise OSError("disk full")

        service.store.save_result = fail_save_result
        try:
            result = service.execute(_request(), job_id_factory=lambda: "job-fixed")
        finally:
            service.store.save_result = original_save_result

        assert result.status == CodingJobState.failed
        assert result.metrics["failureKind"] == "persistence"
        assert "disk full" in result.error
        record = service.require_job("alpha", "job-fixed")
        assert record.state == CodingJobState.failed
        assert "resultJson" not in record.artifact_paths

    def test_cancelled_job_remains_cancelled_when_provider_returns_later(self):
        registry = CodingHarnessRegistry()
        started = threading.Event()
        release = threading.Event()
        results: dict[str, CodingExecResult] = {}

        class BlockingHarness:
            provider = CodingProvider.claude

            def exec(self, job_id, request, effective_cwd, startup_policy):
                started.set()
                release.wait(timeout=2)
                return HarnessExecution(
                    result=CodingExecResult(
                        jobId=job_id,
                        provider=request.provider,
                        effectiveCwd=effective_cwd,
                        status="completed",
                        summary="provider finished after cancel",
                    ),
                    command=["claude"],
                    artifactPayloads={
                        "stdoutLog": HarnessArtifact(
                            filename="stdout.log",
                            contentType="text/plain",
                            text="late provider output",
                        )
                    },
                )

        registry.register(CodingProvider.claude, BlockingHarness())
        service = CodingService(registry=registry)

        def run_job():
            results["result"] = service.execute(_request(), job_id_factory=lambda: "job-fixed")

        worker = threading.Thread(target=run_job)
        worker.start()
        assert started.wait(timeout=2)

        cancelled = service.cancel_job("alpha", "job-fixed", reason="operator requested stop")
        release.set()
        worker.join(timeout=2)

        assert not worker.is_alive()
        assert cancelled.state == CodingJobState.cancelled
        assert results["result"].status == CodingJobState.cancelled
        assert results["result"].summary == "operator requested stop"
        assert Path(results["result"].artifacts["stdoutLog"]).exists()

        record = service.require_job("alpha", "job-fixed")
        assert record.state == CodingJobState.cancelled
        assert record.summary == "operator requested stop"
        assert record.error == "operator requested stop"
        assert Path(record.artifact_paths["stdoutLog"]).exists()
        events = service.store.list_events("alpha", "job-fixed")
        assert [event.event_type.value for event in events] == [
            "created",
            "started",
            "cancelled",
        ]

    def test_retry_job_rejects_semantic_completed_attempts(self):
        service = CodingService()
        service.create_job(_request(), job_id_factory=lambda: "job-fixed")
        service.mark_running("alpha", "job-fixed")
        service.complete_job(
            "alpha",
            "job-fixed",
            CodingExecResult(
                jobId="job-fixed",
                provider="claude",
                effectiveCwd="/tmp/worktree",
                status="completed",
                summary="done",
            ),
        )

        with pytest.raises(ValueError, match="Retry is only valid"):
            service.retry_job("alpha", "job-fixed")

    def test_replay_job_reuses_persisted_request_data(self):
        registry = CodingHarnessRegistry()
        captured = {}

        class FakeHarness:
            provider = CodingProvider.claude

            def exec(self, job_id, request, effective_cwd, startup_policy):
                captured["prompt"] = request.prompt
                captured["providerArgs"] = list(request.provider_args)
                captured["cwd"] = effective_cwd
                return HarnessExecution(
                    result=CodingExecResult(
                        jobId=job_id,
                        provider=request.provider,
                        effectiveCwd=effective_cwd,
                        status="completed",
                        summary="replayed",
                    ),
                    command=["claude"],
                    artifactPayloads={},
                )

        registry.register(CodingProvider.claude, FakeHarness())
        service = CodingService(registry=registry)
        request = _request(prompt="Persist me", providerArgs=["--model", "sonnet"])
        service.create_job(request, job_id_factory=lambda: "job-1")
        service.mark_running("alpha", "job-1")
        service.complete_job(
            "alpha",
            "job-1",
            CodingExecResult(
                jobId="job-1",
                provider="claude",
                effectiveCwd="/tmp/worktree",
                status="completed",
                summary="done",
            ),
        )

        result = service.replay_job("alpha", "job-1", job_id_factory=lambda: "job-2")

        assert result.status == CodingJobState.completed
        assert captured["prompt"] == "Persist me"
        assert captured["providerArgs"] == ["--model", "sonnet"]
        assert captured["cwd"] == "/tmp/worktree"
