"""Phase 0 tests for coding runtime contracts."""

from __future__ import annotations

import json

import pytest

from clawteam.coding.models import (
    ACTIVE_CODING_JOB_STATES,
    CODING_CONTROL_COMMANDS,
    CodingAttemptKind,
    CodingControlCommand,
    CodingEventType,
    CodingExecRequest,
    CodingExecResult,
    CodingJobEvent,
    CodingJobRecord,
    CodingJobState,
    CodingProvider,
    ResolvedStartupPolicy,
    build_replay_lineage,
    build_retry_lineage,
    default_startup_flags,
    resolve_effective_cwd,
    validate_state_transition,
)


class TestCodingExecRequest:
    def test_alias_fields_roundtrip(self):
        request = CodingExecRequest(
            teamName="alpha",
            workerName="worker-1",
            workerId="worker-id-1",
            taskId="task-1",
            provider="claude",
            prompt="Implement retries",
            cwd="/tmp/project/subdir",
            workerWorkspaceCwd="/tmp/project",
            workerRuntimeCwd="/tmp/runtime",
            skipProviderPermissions=True,
            providerArgs=["--verbose"],
            maxInfraRetries=2,
        )

        dumped = json.loads(request.model_dump_json(by_alias=True))

        assert dumped["teamName"] == "alpha"
        assert dumped["workerName"] == "worker-1"
        assert dumped["cwd"] == "/tmp/project/subdir"
        assert dumped["workerWorkspaceCwd"] == "/tmp/project"
        assert dumped["skipProviderPermissions"] is True
        assert dumped["providerArgs"] == ["--verbose"]
        assert dumped["maxInfraRetries"] == 2

    def test_resolve_effective_cwd_prefers_request_override(self):
        request = CodingExecRequest(
            teamName="alpha",
            workerName="worker-1",
            workerId="worker-id-1",
            provider="claude",
            prompt="Implement retries",
            cwd="/tmp/project/subdir",
            workerWorkspaceCwd="/tmp/project",
            workerRuntimeCwd="/tmp/runtime",
        )

        assert request.resolve_effective_cwd() == "/tmp/project/subdir"

    def test_rejects_relative_paths(self):
        with pytest.raises(ValueError, match="must be an absolute path"):
            CodingExecRequest(
                teamName="alpha",
                workerName="worker-1",
                workerId="worker-id-1",
                provider="claude",
                prompt="Implement retries",
                cwd="relative/path",
            )


class TestEffectiveCwdResolution:
    def test_falls_back_to_workspace_then_runtime(self):
        assert (
            resolve_effective_cwd(
                requested_cwd=None,
                worker_workspace_cwd="/tmp/worktree",
                worker_runtime_cwd="/tmp/runtime",
            )
            == "/tmp/worktree"
        )
        assert (
            resolve_effective_cwd(
                requested_cwd=None,
                worker_workspace_cwd=None,
                worker_runtime_cwd="/tmp/runtime",
            )
            == "/tmp/runtime"
        )

    def test_fails_fast_when_no_cwd_can_be_resolved(self):
        with pytest.raises(ValueError, match="Unable to resolve effective cwd"):
            resolve_effective_cwd(None, None, None)

    def test_rejects_workspace_escape_by_default(self):
        with pytest.raises(ValueError, match="workspace/worktree boundary"):
            resolve_effective_cwd(
                requested_cwd="/tmp/elsewhere",
                worker_workspace_cwd="/tmp/worktree",
                worker_runtime_cwd="/tmp/runtime",
            )

    def test_allows_workspace_escape_only_when_explicitly_enabled(self):
        assert (
            resolve_effective_cwd(
                requested_cwd="/tmp/elsewhere",
                worker_workspace_cwd="/tmp/worktree",
                worker_runtime_cwd="/tmp/runtime",
                allow_cwd_escape=True,
            )
            == "/tmp/elsewhere"
        )


class TestStateMachine:
    def test_all_required_transitions_are_valid(self):
        validate_state_transition(CodingJobState.queued, CodingJobState.running)
        validate_state_transition(CodingJobState.queued, CodingJobState.cancelled)
        validate_state_transition(CodingJobState.running, CodingJobState.completed)
        validate_state_transition(CodingJobState.running, CodingJobState.failed)
        validate_state_transition(CodingJobState.running, CodingJobState.timeout)
        validate_state_transition(CodingJobState.running, CodingJobState.cancelled)

    def test_terminal_states_do_not_transition_implicitly(self):
        with pytest.raises(ValueError, match="Invalid coding job transition"):
            validate_state_transition(CodingJobState.completed, CodingJobState.running)

        with pytest.raises(ValueError, match="Invalid coding job transition"):
            validate_state_transition(CodingJobState.failed, CodingJobState.completed)


class TestStartupFlags:
    def test_provider_defaults_are_frozen(self):
        assert default_startup_flags(CodingProvider.claude, True) == [
            "--dangerously-skip-permissions"
        ]
        assert default_startup_flags(CodingProvider.codex, True) == [
            "--dangerously-bypass-approvals-and-sandbox"
        ]

    def test_permission_skip_can_be_disabled(self):
        assert default_startup_flags(CodingProvider.claude, False) == []
        assert default_startup_flags(CodingProvider.codex, False) == []


class TestResultContract:
    def test_result_schema_version_defaults_for_new_and_old_payloads(self):
        result = CodingExecResult(
            jobId="job-1",
            provider="claude",
            effectiveCwd="/tmp/project",
            status="completed",
        )

        dumped = json.loads(result.model_dump_json(by_alias=True))

        assert dumped["schemaVersion"] == 1
        restored = CodingExecResult.model_validate(
            {
                "jobId": "job-legacy",
                "provider": "claude",
                "effectiveCwd": "/tmp/project",
                "status": "failed",
            }
        )
        assert restored.schema_version == 1

    def test_result_requires_terminal_status(self):
        with pytest.raises(ValueError, match="terminal state"):
            CodingExecResult(
                jobId="job-1",
                provider="claude",
                effectiveCwd="/tmp/project",
                status="running",
            )

    def test_result_allows_terminal_failure_status(self):
        result = CodingExecResult(
            jobId="job-1",
            provider="claude",
            effectiveCwd="/tmp/project",
            status="failed",
            exitCode=2,
            summary="Provider returned non-zero exit code",
            error="cli exited 2",
        )

        assert result.status == CodingJobState.failed
        assert result.exit_code == 2


class TestLineageSemantics:
    def _job(
        self,
        *,
        job_id: str = "job-1",
        state: CodingJobState = CodingJobState.failed,
        attempt_kind: CodingAttemptKind = CodingAttemptKind.initial,
        retry_count: int = 0,
        replay_count: int = 0,
        root_job_id: str | None = None,
        parent_job_id: str | None = None,
    ) -> CodingJobRecord:
        return CodingJobRecord(
            jobId=job_id,
            teamName="alpha",
            workerName="worker-1",
            workerId="worker-id-1",
            provider="claude",
            state=state,
            requestedCwd="/tmp/project",
            workerWorkspaceCwd="/tmp/project",
            workerRuntimeCwd="/tmp/runtime",
            effectiveCwd="/tmp/project",
            startupPolicy=ResolvedStartupPolicy(
                skipProviderPermissions=True,
                appliedFlags=["--dangerously-skip-permissions"],
            ),
            request={"prompt": "Fix tests"},
            rootJobId=root_job_id,
            parentJobId=parent_job_id,
            attemptKind=attempt_kind,
            retryCount=retry_count,
            replayCount=replay_count,
        )

    def test_retry_increments_retry_count_and_keeps_logical_lineage(self):
        previous = self._job()

        lineage = build_retry_lineage(previous)

        assert lineage["rootJobId"] == "job-1"
        assert lineage["parentJobId"] == "job-1"
        assert lineage["attemptKind"] == CodingAttemptKind.retry
        assert lineage["retryCount"] == 1
        assert lineage["replayCount"] == 0

    def test_replay_creates_new_execution_from_persisted_request(self):
        previous = self._job(state=CodingJobState.completed)

        lineage = build_replay_lineage(previous)

        assert lineage["rootJobId"] == "job-1"
        assert lineage["parentJobId"] == "job-1"
        assert lineage["attemptKind"] == CodingAttemptKind.replay
        assert lineage["retryCount"] == 0
        assert lineage["replayCount"] == 1

    def test_retry_is_not_allowed_for_non_infrastructure_states(self):
        previous = self._job(state=CodingJobState.completed)

        with pytest.raises(ValueError, match="Retry is only valid"):
            build_retry_lineage(previous)

    def test_replay_requires_terminal_state(self):
        previous = self._job(state=CodingJobState.running)

        with pytest.raises(ValueError, match="Replay requires a terminal"):
            build_replay_lineage(previous)


class TestEventAndControlSurface:
    def test_event_schema_aliases(self):
        event = CodingJobEvent(
            eventId="evt-1",
            jobId="job-1",
            teamName="alpha",
            workerName="worker-1",
            eventType=CodingEventType.created,
            state=CodingJobState.queued,
        )

        dumped = json.loads(event.model_dump_json(by_alias=True))

        assert dumped["schemaVersion"] == 1
        assert dumped["eventId"] == "evt-1"
        assert dumped["jobId"] == "job-1"
        assert dumped["eventType"] == "created"
        assert dumped["state"] == "queued"

    def test_job_record_schema_version_defaults_for_legacy_payloads(self):
        record = CodingJobRecord.model_validate(
            {
                "jobId": "job-1",
                "teamName": "alpha",
                "workerName": "worker-1",
                "workerId": "worker-id-1",
                "provider": "claude",
                "state": "queued",
                "requestedCwd": "/tmp/project",
                "workerWorkspaceCwd": "/tmp/project",
                "workerRuntimeCwd": "/tmp/runtime",
                "effectiveCwd": "/tmp/project",
                "startupPolicy": {
                    "skipProviderPermissions": True,
                    "appliedFlags": ["--dangerously-skip-permissions"],
                },
                "request": {"prompt": "Fix tests"},
            }
        )

        dumped = json.loads(record.model_dump_json(by_alias=True))

        assert record.schema_version == 1
        assert dumped["schemaVersion"] == 1

    def test_control_plane_surface_is_stable(self):
        assert CODING_CONTROL_COMMANDS == (
            "exec",
            "status",
            "wait",
            "cancel",
            "retry",
            "replay",
        )
        assert CodingControlCommand.exec.value == "exec"
        assert ACTIVE_CODING_JOB_STATES == {
            CodingJobState.queued,
            CodingJobState.running,
        }
