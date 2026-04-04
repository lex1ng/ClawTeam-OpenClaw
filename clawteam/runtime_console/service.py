"""Runtime console synchronization service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from clawteam.runtime_console.models import (
    CallbackReportRecord,
    CallbackStatusValue,
    ProviderSessionRecord,
    ProviderSessionMode,
    ProviderSessionState,
    RuntimeTimelineActorType,
    RuntimeTimelineEvent,
    RuntimeTimelineEventType,
    RuntimeTimelineScopeType,
)
from clawteam.runtime_console.store import RuntimeConsoleStore
from clawteam.spawn.sessions import SessionStore
from clawteam.team.models import WorkerCodingCallbackReport, WorkerCodingDecision

if TYPE_CHECKING:
    from clawteam.coding.models import CodingJobRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_timeline_event_id() -> str:
    return f"rt-{uuid.uuid4().hex[:12]}"


class RuntimeConsoleService:
    """Maintains durable runtime-console state without changing core job semantics."""

    def __init__(self, store: RuntimeConsoleStore | None = None):
        self.store = store or RuntimeConsoleStore()

    def initialize_for_job(self, record: CodingJobRecord) -> None:
        session = self._provider_session_from_job(record, state=ProviderSessionState.initializing)
        self.store.save_provider_session(session)
        self.store.append_timeline_event(
            record.team_name,
            RuntimeTimelineEvent(
                eventId=_new_timeline_event_id(),
                eventType=RuntimeTimelineEventType.coding_job_created,
                teamName=record.team_name,
                scopeType=RuntimeTimelineScopeType.coding_job,
                scopeId=record.job_id,
                actorType=RuntimeTimelineActorType.worker,
                actorId=record.worker_id,
                summary=f"Coding job {record.job_id} created for {record.worker_name}",
                links={
                    "jobId": record.job_id,
                    "taskId": record.task_id or "",
                    "sessionId": record.provider_session_ref or "",
                },
            ),
        )
        self.store.append_timeline_event(
            record.team_name,
            RuntimeTimelineEvent(
                eventId=_new_timeline_event_id(),
                eventType=RuntimeTimelineEventType.provider_session_attached,
                teamName=record.team_name,
                scopeType=RuntimeTimelineScopeType.provider_session,
                scopeId=record.provider_session_ref or "",
                actorType=RuntimeTimelineActorType.runtime,
                actorId=record.worker_id,
                summary=(
                    f"Provider session {record.provider_session_ref or 'unavailable'} attached "
                    f"to job {record.job_id}"
                ),
                links={
                    "jobId": record.job_id,
                    "sessionId": record.provider_session_ref or "",
                },
            ),
        )

    def mark_job_running(self, record: CodingJobRecord) -> None:
        session = self._load_provider_session(record)
        updated = session.model_copy(
            update={
                "state": ProviderSessionState.waiting_provider,
                "current_job_id": record.job_id,
                "current_task_id": record.task_id,
                "last_activity_at": _now_iso(),
                "updated_at": _now_iso(),
            }
        )
        self.store.save_provider_session(updated)
        self.store.append_timeline_event(
            record.team_name,
            RuntimeTimelineEvent(
                eventId=_new_timeline_event_id(),
                eventType=RuntimeTimelineEventType.coding_job_started,
                teamName=record.team_name,
                scopeType=RuntimeTimelineScopeType.coding_job,
                scopeId=record.job_id,
                actorType=RuntimeTimelineActorType.worker,
                actorId=record.worker_id,
                summary=f"Coding job {record.job_id} started",
                links={"jobId": record.job_id, "sessionId": record.provider_session_ref or ""},
            ),
        )

    def mark_job_terminal(self, record: CodingJobRecord) -> None:
        state_value = getattr(record.state, "value", record.state)
        state = {
            "completed": ProviderSessionState.callback_pending,
            "failed": ProviderSessionState.callback_pending,
            "timeout": ProviderSessionState.callback_pending,
            "cancelled": ProviderSessionState.cancelled,
        }.get(state_value, ProviderSessionState.callback_pending)
        session = self._load_provider_session(record)
        updated = session.model_copy(
            update={
                "state": state,
                "last_job_id": record.job_id,
                "current_job_id": record.job_id if state == ProviderSessionState.callback_pending else None,
                "current_task_id": record.task_id if state == ProviderSessionState.callback_pending else None,
                "callback_status": record.callback_status.value,
                "last_activity_at": _now_iso(),
                "updated_at": _now_iso(),
            }
        )
        self.store.save_provider_session(updated)
        event_type = {
            "completed": RuntimeTimelineEventType.coding_job_completed,
            "failed": RuntimeTimelineEventType.coding_job_failed,
            "timeout": RuntimeTimelineEventType.coding_job_failed,
            "cancelled": RuntimeTimelineEventType.coding_job_cancelled,
        }[state_value]
        self.store.append_timeline_event(
            record.team_name,
            RuntimeTimelineEvent(
                eventId=_new_timeline_event_id(),
                eventType=event_type,
                teamName=record.team_name,
                scopeType=RuntimeTimelineScopeType.coding_job,
                scopeId=record.job_id,
                actorType=RuntimeTimelineActorType.provider,
                actorId=record.provider.value,
                summary=f"Coding job {record.job_id} reached terminal state {record.state.value}",
                links={"jobId": record.job_id, "sessionId": record.provider_session_ref or ""},
            ),
        )

    def record_callback(
        self,
        *,
        team_name: str,
        report: WorkerCodingCallbackReport,
    ) -> CallbackReportRecord:
        session_id = report.session_id
        callback = CallbackReportRecord(
            teamName=team_name,
            taskId=report.task_id,
            jobId=report.job_id,
            sessionId=session_id,
            providerSessionId=report.provider_session_id,
            workerName=report.worker_name,
            provider=report.provider,
            status=report.status,
            decision=report.decision.value,
            summary=report.summary,
            nextStep=report.next_step,
            escalationReason=report.escalation_reason,
            artifactPaths=report.artifact_paths,
            reportedAt=report.reported_at,
        )
        self.store.save_callback_report(callback)
        if session_id:
            session = self.store.get_provider_session(team_name, session_id)
            if session is not None:
                callback_status = self._callback_status_for_decision(report.decision)
                next_state = (
                    ProviderSessionState.idle_reusable
                    if session.session_mode == ProviderSessionMode.attached
                    else ProviderSessionState.ended
                )
                updated = session.model_copy(
                    update={
                        "state": next_state,
                        "current_job_id": None,
                        "current_task_id": None,
                        "last_job_id": report.job_id,
                        "callback_status": callback_status.value,
                        "last_callback_at": report.reported_at,
                        "last_activity_at": report.reported_at,
                        "updated_at": report.reported_at,
                    }
                )
                self.store.save_provider_session(updated)
        self.store.append_timeline_event(
            team_name,
            RuntimeTimelineEvent(
                eventId=_new_timeline_event_id(),
                eventType=self._timeline_event_for_decision(report.decision),
                teamName=team_name,
                scopeType=RuntimeTimelineScopeType.callback,
                scopeId=report.job_id,
                actorType=RuntimeTimelineActorType.worker,
                actorId=report.worker_name or "unknown-worker",
                summary=f"Callback reported for job {report.job_id}: {report.decision.value}",
                links={
                    "jobId": report.job_id,
                    "taskId": report.task_id or "",
                    "sessionId": session_id or "",
                },
            ),
        )
        return callback

    def list_provider_sessions(self, team_name: str) -> list[ProviderSessionRecord]:
        return self.store.list_provider_sessions(team_name)

    def list_callback_reports(self, team_name: str) -> list[CallbackReportRecord]:
        return self.store.list_callback_reports(team_name)

    def list_timeline(self, team_name: str) -> list[RuntimeTimelineEvent]:
        return self.store.list_timeline(team_name)

    def _provider_session_from_job(self, record: CodingJobRecord, *, state: ProviderSessionState) -> ProviderSessionRecord:
        agent_session = SessionStore(record.team_name).load(record.worker_name)
        now = _now_iso()
        return ProviderSessionRecord(
            sessionId=record.provider_session_ref or f"psess-{record.job_id}",
            providerSessionId=record.provider_session_id,
            provider=record.provider.value,
            teamName=record.team_name,
            workerName=record.worker_name,
            workerId=record.worker_id,
            agentSessionId=agent_session.session_id or None if agent_session else None,
            state=state,
            sessionMode=record.session_mode.value,
            resumeSupported=False,
            currentJobId=record.job_id,
            lastJobId=record.job_id if state != ProviderSessionState.initializing else None,
            currentTaskId=record.task_id,
            effectiveCwd=record.effective_cwd,
            worktreePath=record.worker_workspace_cwd,
            runtimeCwd=record.worker_runtime_cwd,
            backend=None,
            startedAt=record.started_at or record.created_at,
            updatedAt=now,
            lastActivityAt=now,
            callbackStatus=record.callback_status.value,
        )

    def _load_provider_session(self, record: CodingJobRecord) -> ProviderSessionRecord:
        session_id = record.provider_session_ref or f"psess-{record.job_id}"
        session = self.store.get_provider_session(record.team_name, session_id)
        if session is not None:
            return session
        return self._provider_session_from_job(record, state=ProviderSessionState.initializing)

    def _timeline_event_for_decision(
        self,
        decision: WorkerCodingDecision,
    ) -> RuntimeTimelineEventType:
        mapping = {
            WorkerCodingDecision.continue_: RuntimeTimelineEventType.callback_continued,
            WorkerCodingDecision.report_progress: RuntimeTimelineEventType.callback_reported,
            WorkerCodingDecision.escalate: RuntimeTimelineEventType.callback_escalated,
            WorkerCodingDecision.complete: RuntimeTimelineEventType.callback_reported,
            WorkerCodingDecision.blocked: RuntimeTimelineEventType.callback_reported,
        }
        return mapping[decision]

    def _callback_status_for_decision(
        self,
        decision: WorkerCodingDecision,
    ) -> CallbackStatusValue:
        mapping = {
            WorkerCodingDecision.continue_: CallbackStatusValue.continue_with_provider,
            WorkerCodingDecision.report_progress: CallbackStatusValue.reported,
            WorkerCodingDecision.escalate: CallbackStatusValue.escalated_to_leader,
            WorkerCodingDecision.complete: CallbackStatusValue.closed,
            WorkerCodingDecision.blocked: CallbackStatusValue.blocked_waiting_decision,
        }
        return mapping[decision]
