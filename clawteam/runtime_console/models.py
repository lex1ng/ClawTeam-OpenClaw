"""Persisted models for the runtime console operator surface."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

RUNTIME_CONSOLE_SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProviderSessionState(str, Enum):
    initializing = "initializing"
    active = "active"
    waiting_provider = "waiting_provider"
    callback_pending = "callback_pending"
    idle_reusable = "idle_reusable"
    failed = "failed"
    cancelled = "cancelled"
    stale = "stale"
    ended = "ended"


class ProviderName(str, Enum):
    claude = "claude"
    codex = "codex"


class ProviderSessionMode(str, Enum):
    attached = "attached"
    ephemeral = "ephemeral"


class CallbackStatusValue(str, Enum):
    not_applicable = "not_applicable"
    pending = "pending"
    reported = "reported"
    continue_with_provider = "continue_with_provider"
    escalated_to_leader = "escalated_to_leader"
    blocked_waiting_decision = "blocked_waiting_decision"
    closed = "closed"


class RuntimeFaultSeverity(str, Enum):
    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"


class RuntimeFaultScopeType(str, Enum):
    task = "task"
    coding_job = "coding_job"
    agent_session = "agent_session"
    provider_session = "provider_session"
    callback = "callback"
    runtime = "runtime"


class RuntimeFaultStatus(str, Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"
    suppressed = "suppressed"


class RuntimeTimelineEventType(str, Enum):
    task_created = "task_created"
    task_claimed = "task_claimed"
    task_status_changed = "task_status_changed"
    coding_job_created = "coding_job_created"
    coding_job_started = "coding_job_started"
    coding_job_completed = "coding_job_completed"
    coding_job_failed = "coding_job_failed"
    coding_job_cancelled = "coding_job_cancelled"
    provider_session_attached = "provider_session_attached"
    provider_session_resumed = "provider_session_resumed"
    provider_session_released = "provider_session_released"
    callback_reported = "callback_reported"
    callback_continued = "callback_continued"
    callback_escalated = "callback_escalated"
    fault_detected = "fault_detected"
    fault_cleared = "fault_cleared"


class RuntimeTimelineScopeType(str, Enum):
    task = "task"
    coding_job = "coding_job"
    agent_session = "agent_session"
    provider_session = "provider_session"
    callback = "callback"
    fault = "fault"
    runtime = "runtime"


class RuntimeTimelineActorType(str, Enum):
    worker = "worker"
    leader = "leader"
    provider = "provider"
    control_plane = "control_plane"
    runtime = "runtime"


class ProviderSessionRecord(BaseModel):
    """Durable record for provider-side execution context."""

    model_config = {"populate_by_name": True}

    schema_version: int = Field(default=RUNTIME_CONSOLE_SCHEMA_VERSION, alias="schemaVersion", ge=1)
    session_id: str = Field(alias="sessionId")
    provider_session_id: str | None = Field(default=None, alias="providerSessionId")
    provider: ProviderName
    team_name: str = Field(alias="teamName")
    worker_name: str = Field(alias="workerName")
    worker_id: str = Field(alias="workerId")
    agent_session_id: str | None = Field(default=None, alias="agentSessionId")
    state: ProviderSessionState
    session_mode: ProviderSessionMode = Field(alias="sessionMode")
    resume_supported: bool = Field(default=False, alias="resumeSupported")
    current_job_id: str | None = Field(default=None, alias="currentJobId")
    last_job_id: str | None = Field(default=None, alias="lastJobId")
    current_task_id: str | None = Field(default=None, alias="currentTaskId")
    effective_cwd: str | None = Field(default=None, alias="effectiveCwd")
    worktree_path: str | None = Field(default=None, alias="worktreePath")
    runtime_cwd: str | None = Field(default=None, alias="runtimeCwd")
    tmux_session: str | None = Field(default=None, alias="tmuxSession")
    tmux_window: str | None = Field(default=None, alias="tmuxWindow")
    backend: str | None = None
    started_at: str = Field(default_factory=_now_iso, alias="startedAt")
    updated_at: str = Field(default_factory=_now_iso, alias="updatedAt")
    last_activity_at: str | None = Field(default=None, alias="lastActivityAt")
    last_callback_at: str | None = Field(default=None, alias="lastCallbackAt")
    ended_at: str | None = Field(default=None, alias="endedAt")
    callback_status: CallbackStatusValue = Field(
        default="not_applicable",
        alias="callbackStatus",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    artifact_paths: dict[str, str] = Field(default_factory=dict, alias="artifactPaths")
    faults: list[str] = Field(default_factory=list)


class CallbackReportRecord(BaseModel):
    """Durable callback report persisted separately from task metadata."""

    model_config = {"populate_by_name": True}

    schema_version: int = Field(default=RUNTIME_CONSOLE_SCHEMA_VERSION, alias="schemaVersion", ge=1)
    team_name: str = Field(alias="teamName")
    task_id: str | None = Field(default=None, alias="taskId")
    job_id: str = Field(alias="jobId")
    session_id: str | None = Field(default=None, alias="sessionId")
    provider_session_id: str | None = Field(default=None, alias="providerSessionId")
    worker_name: str | None = Field(default=None, alias="workerName")
    provider: str
    status: str
    decision: str
    summary: str
    next_step: str = Field(default="", alias="nextStep")
    escalation_reason: str | None = Field(default=None, alias="escalationReason")
    artifact_paths: dict[str, str] = Field(default_factory=dict, alias="artifactPaths")
    reported_at: str = Field(default_factory=_now_iso, alias="reportedAt")


class RuntimeFaultRecord(BaseModel):
    """Explicit runtime-visible fault record."""

    model_config = {"populate_by_name": True}

    schema_version: int = Field(default=RUNTIME_CONSOLE_SCHEMA_VERSION, alias="schemaVersion", ge=1)
    fault_id: str = Field(alias="faultId")
    fault_type: str = Field(alias="faultType")
    severity: RuntimeFaultSeverity
    scope_type: RuntimeFaultScopeType = Field(alias="scopeType")
    scope_id: str = Field(alias="scopeId")
    team_name: str = Field(alias="teamName")
    message: str
    detail: str = ""
    detected_at: str = Field(default_factory=_now_iso, alias="detectedAt")
    status: RuntimeFaultStatus = RuntimeFaultStatus.open
    suggested_action: str = Field(default="", alias="suggestedAction")
    artifact_paths: dict[str, str] = Field(default_factory=dict, alias="artifactPaths")


class RuntimeTimelineEvent(BaseModel):
    """Unified timeline event over runtime console objects."""

    model_config = {"populate_by_name": True}

    schema_version: int = Field(default=RUNTIME_CONSOLE_SCHEMA_VERSION, alias="schemaVersion", ge=1)
    event_id: str = Field(alias="eventId")
    event_type: RuntimeTimelineEventType = Field(alias="eventType")
    team_name: str = Field(alias="teamName")
    timestamp: str = Field(default_factory=_now_iso)
    scope_type: RuntimeTimelineScopeType = Field(alias="scopeType")
    scope_id: str = Field(alias="scopeId")
    actor_type: RuntimeTimelineActorType = Field(alias="actorType")
    actor_id: str = Field(alias="actorId")
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    links: dict[str, str] = Field(default_factory=dict)
