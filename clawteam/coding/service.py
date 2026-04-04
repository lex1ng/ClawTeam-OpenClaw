"""Runtime core for durable coding job lifecycle management."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from clawteam.coding.models import (
    ACTIVE_CODING_JOB_STATES,
    CodingAttemptKind,
    CodingEventType,
    CodingExecRequest,
    CodingExecResult,
    CodingJobEvent,
    CodingJobRecord,
    CodingJobState,
    ResolvedStartupPolicy,
    build_replay_lineage,
    build_retry_lineage,
    default_startup_flags,
    validate_state_transition,
)
from clawteam.coding.harness.base import HarnessArtifact, HarnessExecution
from clawteam.coding.registry import CodingHarnessRegistry, build_default_registry
from clawteam.coding.store import CodingJobStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_job_id() -> str:
    return f"job-{uuid.uuid4().hex[:12]}"


def _new_event_id() -> str:
    return f"evt-{uuid.uuid4().hex[:12]}"


def _dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump_json"):
        return json.loads(model.model_dump_json(by_alias=True, exclude_none=True))
    return json.loads(json.dumps(model))


class CodingJobNotFoundError(ValueError):
    """Raised when a requested coding job record does not exist."""


class CodingJobConflictError(ValueError):
    """Raised when a V1 concurrency boundary would be violated."""


class CodingService:
    """Durable job lifecycle service.

    This layer owns business-level job records and explicit terminal results.
    It does not infer completion from provider process exit alone.
    """

    def __init__(
        self,
        store: CodingJobStore | None = None,
        registry: CodingHarnessRegistry | None = None,
    ):
        self.store = store or CodingJobStore()
        self.registry = registry or build_default_registry()

    def resolve_startup_policy(
        self,
        request: CodingExecRequest,
        *,
        source: str = "provider_default",
    ) -> ResolvedStartupPolicy:
        skip = True if request.skip_provider_permissions is None else request.skip_provider_permissions
        return ResolvedStartupPolicy(
            skipProviderPermissions=skip,
            source=source,
            appliedFlags=default_startup_flags(request.provider, skip),
            extraArgs=list(request.provider_args),
        )

    def create_job(
        self,
        request: CodingExecRequest,
        *,
        startup_policy: ResolvedStartupPolicy | None = None,
        job_id_factory: Callable[[], str] | None = None,
        lineage: dict[str, Any] | None = None,
    ) -> CodingJobRecord:
        job_id = (job_id_factory or _new_job_id)()
        effective_cwd = request.resolve_effective_cwd()
        policy = startup_policy or self.resolve_startup_policy(request)
        lineage_data = {
            "rootJobId": job_id,
            "parentJobId": None,
            "attemptKind": CodingAttemptKind.initial,
            "retryCount": 0,
            "replayCount": 0,
        }
        if lineage:
            lineage_data.update(lineage)

        record = CodingJobRecord(
            jobId=job_id,
            teamName=request.team_name,
            workerName=request.worker_name,
            workerId=request.worker_id,
            leaderName=request.leader_name,
            taskId=request.task_id,
            provider=request.provider,
            mode=request.mode,
            state=CodingJobState.queued,
            requestedCwd=request.cwd,
            workerWorkspaceCwd=request.worker_workspace_cwd,
            workerRuntimeCwd=request.worker_runtime_cwd,
            effectiveCwd=effective_cwd,
            startupPolicy=policy,
            artifactPaths={"jobRecord": str(self.store.job_path(request.team_name, job_id))},
            request=_dump_model(request),
            **lineage_data,
        )
        self.store.create_job_atomically(
            record,
            created_event=self._event_for_record(record, CodingEventType.created),
            ensure_capacity=lambda jobs: self._ensure_v1_capacity(request, existing_jobs=jobs),
        )
        return record

    def mark_running(self, team_name: str, job_id: str) -> CodingJobRecord:
        record = self.require_job(team_name, job_id)
        validate_state_transition(record.state, CodingJobState.running)
        now = _now_iso()
        updated = record.model_copy(
            update={
                "state": CodingJobState.running,
                "started_at": record.started_at or now,
                "updated_at": now,
            }
        )
        self.store.save_job(updated)
        self.store.append_event(self._event_for_record(updated, CodingEventType.started))
        return updated

    def complete_job(
        self,
        team_name: str,
        job_id: str,
        result: CodingExecResult,
        *,
        artifact_paths: dict[str, str] | None = None,
    ) -> CodingJobRecord:
        record = self.require_job(team_name, job_id)
        validate_state_transition(record.state, result.status)
        result_path = self.store.save_result(team_name, job_id, result)
        merged_artifacts = dict(record.artifact_paths)
        merged_artifacts["resultJson"] = result_path
        if artifact_paths:
            merged_artifacts.update(artifact_paths)
        now = _now_iso()
        updated = record.model_copy(
            update={
                "state": result.status,
                "exit_code": result.exit_code,
                "summary": result.summary,
                "error": result.error,
                "artifact_paths": merged_artifacts,
                "result": _dump_model(result),
                "updated_at": now,
                "finished_at": now,
            }
        )
        self.store.save_job(updated)
        self.store.append_event(self._event_for_record(updated, self._event_type_for_state(result.status)))
        return updated

    def create_retry_job(
        self,
        team_name: str,
        job_id: str,
        *,
        job_id_factory: Callable[[], str] | None = None,
    ) -> CodingJobRecord:
        previous = self.require_job(team_name, job_id)
        request = CodingExecRequest.model_validate(previous.request)
        startup_policy = previous.startup_policy
        lineage = build_retry_lineage(previous)
        new_record = self.create_job(
            request,
            startup_policy=startup_policy,
            job_id_factory=job_id_factory,
            lineage=lineage,
        )
        self.store.append_event(
            CodingJobEvent(
                eventId=_new_event_id(),
                jobId=new_record.job_id,
                teamName=new_record.team_name,
                workerName=new_record.worker_name,
                eventType=CodingEventType.retry_requested,
                state=new_record.state,
                attemptKind=new_record.attempt_kind,
                retryCount=new_record.retry_count,
                replayCount=new_record.replay_count,
                details={"sourceJobId": previous.job_id},
            )
        )
        return new_record

    def create_replay_job(
        self,
        team_name: str,
        job_id: str,
        *,
        job_id_factory: Callable[[], str] | None = None,
    ) -> CodingJobRecord:
        previous = self.require_job(team_name, job_id)
        request = CodingExecRequest.model_validate(previous.request)
        startup_policy = previous.startup_policy
        lineage = build_replay_lineage(previous)
        new_record = self.create_job(
            request,
            startup_policy=startup_policy,
            job_id_factory=job_id_factory,
            lineage=lineage,
        )
        self.store.append_event(
            CodingJobEvent(
                eventId=_new_event_id(),
                jobId=new_record.job_id,
                teamName=new_record.team_name,
                workerName=new_record.worker_name,
                eventType=CodingEventType.replay_requested,
                state=new_record.state,
                attemptKind=new_record.attempt_kind,
                retryCount=new_record.retry_count,
                replayCount=new_record.replay_count,
                details={"sourceJobId": previous.job_id},
            )
        )
        return new_record

    def execute(
        self,
        request: CodingExecRequest,
        *,
        startup_policy: ResolvedStartupPolicy | None = None,
        job_id_factory: Callable[[], str] | None = None,
    ) -> CodingExecResult:
        record = self.create_job(
            request,
            startup_policy=startup_policy,
            job_id_factory=job_id_factory,
        )
        return self._execute_prepared_job(record, request)

    def retry_job(
        self,
        team_name: str,
        job_id: str,
        *,
        job_id_factory: Callable[[], str] | None = None,
    ) -> CodingExecResult:
        previous = self.require_job(team_name, job_id)
        request = CodingExecRequest.model_validate(previous.request)
        record = self.create_retry_job(team_name, job_id, job_id_factory=job_id_factory)
        return self._execute_prepared_job(record, request)

    def replay_job(
        self,
        team_name: str,
        job_id: str,
        *,
        job_id_factory: Callable[[], str] | None = None,
    ) -> CodingExecResult:
        previous = self.require_job(team_name, job_id)
        request = CodingExecRequest.model_validate(previous.request)
        record = self.create_replay_job(team_name, job_id, job_id_factory=job_id_factory)
        return self._execute_prepared_job(record, request)

    def cancel_job(self, team_name: str, job_id: str, *, reason: str = "") -> CodingJobRecord:
        record = self.require_job(team_name, job_id)
        if record.state in {
            CodingJobState.completed,
            CodingJobState.failed,
            CodingJobState.timeout,
            CodingJobState.cancelled,
        }:
            raise ValueError(f"Coding job '{job_id}' is already terminal ({record.state.value}).")
        summary = reason or "Coding job cancelled by control-plane request."
        result = CodingExecResult(
            jobId=record.job_id,
            provider=record.provider,
            effectiveCwd=record.effective_cwd,
            status=CodingJobState.cancelled,
            summary=summary,
            error=reason or "cancelled",
            artifacts={},
            metrics={"failureKind": "cancelled"},
        )
        return self.complete_job(team_name, job_id, result)

    def _execute_prepared_job(
        self,
        record: CodingJobRecord,
        request: CodingExecRequest,
    ) -> CodingExecResult:
        running_record = self.mark_running(record.team_name, record.job_id)
        harness = self.registry.get(request.provider)

        try:
            execution = harness.exec(
                running_record.job_id,
                request,
                running_record.effective_cwd,
                running_record.startup_policy,
            )
        except Exception as exc:
            execution = self._service_failure_execution(
                request=request,
                job_id=running_record.job_id,
                effective_cwd=running_record.effective_cwd,
                error_text=str(exc),
            )

        persisted_artifacts: dict[str, str] = {}
        try:
            persisted_artifacts = self._persist_artifact_payloads(
                team_name=running_record.team_name,
                job_id=running_record.job_id,
                artifact_payloads=execution.artifact_payloads,
            )
            cancelled_result = self._cancelled_result_if_terminal(
                running_record.team_name,
                running_record.job_id,
                persisted_artifacts,
            )
            if cancelled_result is not None:
                return cancelled_result
            final_result = execution.result.model_copy(update={"artifacts": persisted_artifacts})
            self.complete_job(
                running_record.team_name,
                running_record.job_id,
                final_result,
                artifact_paths=persisted_artifacts,
            )
            return final_result
        except Exception as exc:
            cancelled_result = self._cancelled_result_if_terminal(
                running_record.team_name,
                running_record.job_id,
                persisted_artifacts,
            )
            if cancelled_result is not None:
                return cancelled_result
            failure_result = CodingExecResult(
                jobId=running_record.job_id,
                provider=request.provider,
                effectiveCwd=running_record.effective_cwd,
                status=CodingJobState.failed,
                summary="Coding job persistence failed before terminal result durability was complete.",
                responseText="",
                artifacts=persisted_artifacts,
                metrics={"failureKind": "persistence"},
                error=f"persistence failure: {exc}",
            )
            self._best_effort_mark_failed_without_result(
                running_record,
                failure_result,
                persisted_artifacts,
            )
            return failure_result

    def require_job(self, team_name: str, job_id: str) -> CodingJobRecord:
        record = self.store.get_job(team_name, job_id)
        if record is None:
            raise CodingJobNotFoundError(f"Coding job '{job_id}' not found for team '{team_name}'")
        return record

    def _cancelled_result_if_terminal(
        self,
        team_name: str,
        job_id: str,
        artifact_paths: dict[str, str],
    ) -> CodingExecResult | None:
        record = self.store.get_job(team_name, job_id)
        if record is None or record.state != CodingJobState.cancelled:
            return None
        if artifact_paths:
            record = self._best_effort_attach_terminal_artifacts(record, artifact_paths)
        return self._result_from_record(record)

    def _best_effort_attach_terminal_artifacts(
        self,
        record: CodingJobRecord,
        artifact_paths: dict[str, str],
    ) -> CodingJobRecord:
        merged_artifacts = dict(record.artifact_paths)
        merged_artifacts.update(artifact_paths)
        updated_result_payload = record.result
        try:
            if record.result is not None:
                existing_result = CodingExecResult.model_validate(record.result)
                updated_result = existing_result.model_copy(
                    update={
                        "artifacts": {
                            **existing_result.artifacts,
                            **artifact_paths,
                        }
                    }
                )
                result_path = self.store.save_result(record.team_name, record.job_id, updated_result)
                merged_artifacts["resultJson"] = result_path
                updated_result_payload = _dump_model(updated_result)
            updated = record.model_copy(
                update={
                    "artifact_paths": merged_artifacts,
                    "result": updated_result_payload,
                    "updated_at": _now_iso(),
                }
            )
            self.store.save_job(updated)
            return updated
        except Exception:
            return record

    def _result_from_record(self, record: CodingJobRecord) -> CodingExecResult:
        if record.result is not None:
            try:
                return CodingExecResult.model_validate(record.result)
            except Exception:
                pass
        return CodingExecResult(
            jobId=record.job_id,
            provider=record.provider,
            effectiveCwd=record.effective_cwd,
            status=record.state,
            exitCode=record.exit_code,
            summary=record.summary,
            error=record.error,
            artifacts={
                key: value
                for key, value in record.artifact_paths.items()
                if key not in {"jobRecord", "resultJson"}
            },
        )

    def _event_for_record(
        self,
        record: CodingJobRecord,
        event_type: CodingEventType,
    ) -> CodingJobEvent:
        return CodingJobEvent(
            eventId=_new_event_id(),
            jobId=record.job_id,
            teamName=record.team_name,
            workerName=record.worker_name,
            eventType=event_type,
            state=record.state,
            attemptKind=record.attempt_kind,
            retryCount=record.retry_count,
            replayCount=record.replay_count,
            summary=record.summary,
        )

    def _event_type_for_state(self, state: CodingJobState) -> CodingEventType:
        mapping = {
            CodingJobState.completed: CodingEventType.completed,
            CodingJobState.failed: CodingEventType.failed,
            CodingJobState.timeout: CodingEventType.timeout,
            CodingJobState.cancelled: CodingEventType.cancelled,
        }
        return mapping[state]

    def _ensure_v1_capacity(
        self,
        request: CodingExecRequest,
        existing_jobs: list[CodingJobRecord] | None = None,
    ) -> None:
        active_jobs = [
            job for job in (existing_jobs if existing_jobs is not None else self.store.list_jobs(request.team_name))
            if job.state in ACTIVE_CODING_JOB_STATES
        ]
        for job in active_jobs:
            if job.worker_id == request.worker_id:
                raise CodingJobConflictError(
                    "V1 allows only one active coding job per worker. "
                    f"Worker '{request.worker_name}' already has active job '{job.job_id}'."
                )
            if request.task_id and job.task_id and job.task_id == request.task_id:
                raise CodingJobConflictError(
                    "V1 allows only one active coding job per task. "
                    f"Task '{request.task_id}' already has active job '{job.job_id}'."
                )

    def _persist_artifact_payloads(
        self,
        *,
        team_name: str,
        job_id: str,
        artifact_payloads: dict[str, HarnessArtifact],
    ) -> dict[str, str]:
        artifact_paths: dict[str, str] = {}
        for key, artifact in artifact_payloads.items():
            if artifact.content_type == "application/json":
                artifact_paths[key] = self.store.save_json_artifact(
                    team_name,
                    job_id,
                    artifact.filename,
                    artifact.data or {},
                )
            else:
                artifact_paths[key] = self.store.save_text_artifact(
                    team_name,
                    job_id,
                    artifact.filename,
                    artifact.text or "",
                )
        return artifact_paths

    def _service_failure_execution(
        self,
        *,
        request: CodingExecRequest,
        job_id: str,
        effective_cwd: str,
        error_text: str,
    ) -> HarnessExecution:
        artifact = HarnessArtifact(
            filename="service-error.txt",
            contentType="text/plain",
            text=error_text,
        )
        result = CodingExecResult(
            jobId=job_id,
            provider=request.provider,
            effectiveCwd=effective_cwd,
            status=CodingJobState.failed,
            summary=f"{request.provider.value} harness execution failed before callback completion.",
            error=f"service failure: {error_text}",
            artifacts={"serviceError": "service-error.txt"},
            metrics={"failureKind": "service"},
        )
        return HarnessExecution(
            result=result,
            command=[],
            artifactPayloads={"serviceError": artifact},
        )

    def _best_effort_mark_failed_without_result(
        self,
        record: CodingJobRecord,
        result: CodingExecResult,
        artifact_paths: dict[str, str],
    ) -> None:
        now = _now_iso()
        updated = record.model_copy(
            update={
                "state": CodingJobState.failed,
                "summary": result.summary,
                "error": result.error,
                "artifact_paths": {**record.artifact_paths, **artifact_paths},
                "result": _dump_model(result),
                "updated_at": now,
                "finished_at": now,
            }
        )
        try:
            self.store.save_job(updated)
            self.store.append_event(self._event_for_record(updated, CodingEventType.failed))
        except Exception:
            pass
