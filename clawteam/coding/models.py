"""Stable contracts for the coding-agent callback runtime.

Phase 0 freezes the runtime contract before store, service, harness, or CLI code
is added. These models define:

- the request/result schema exchanged with the worker callback loop
- the durable job and event records
- deterministic working-directory precedence
- explicit job state transitions
- retry vs replay lineage semantics
- provider startup flag defaults
- the control-plane command surface
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CodingProvider(str, Enum):
    claude = "claude"
    codex = "codex"


class CodingExecMode(str, Enum):
    implement = "implement"
    review = "review"
    analyze = "analyze"
    test = "test"
    general = "general"


class CodingJobState(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    timeout = "timeout"
    cancelled = "cancelled"


class CodingEventType(str, Enum):
    created = "created"
    started = "started"
    completed = "completed"
    failed = "failed"
    timeout = "timeout"
    cancelled = "cancelled"
    retry_requested = "retry_requested"
    replay_requested = "replay_requested"
    artifact_recorded = "artifact_recorded"


class CodingDecision(str, Enum):
    continue_ = "continue"
    report_progress = "report_progress"
    escalate = "escalate"
    complete = "complete"
    blocked = "blocked"


class CodingAttemptKind(str, Enum):
    initial = "initial"
    retry = "retry"
    replay = "replay"


class CodingControlCommand(str, Enum):
    exec = "exec"
    status = "status"
    wait = "wait"
    cancel = "cancel"
    retry = "retry"
    replay = "replay"


TERMINAL_CODING_JOB_STATES = frozenset(
    {
        CodingJobState.completed,
        CodingJobState.failed,
        CodingJobState.timeout,
        CodingJobState.cancelled,
    }
)


ACTIVE_CODING_JOB_STATES = frozenset(
    {
        CodingJobState.queued,
        CodingJobState.running,
    }
)


CODING_CONTROL_COMMANDS = tuple(command.value for command in CodingControlCommand)
PERSISTED_CODING_SCHEMA_VERSION = 1


VALID_STATE_TRANSITIONS: dict[CodingJobState, frozenset[CodingJobState]] = {
    CodingJobState.queued: frozenset({CodingJobState.running, CodingJobState.cancelled}),
    CodingJobState.running: frozenset(
        {
            CodingJobState.completed,
            CodingJobState.failed,
            CodingJobState.timeout,
            CodingJobState.cancelled,
        }
    ),
    CodingJobState.completed: frozenset(),
    CodingJobState.failed: frozenset(),
    CodingJobState.timeout: frozenset(),
    CodingJobState.cancelled: frozenset(),
}


def _normalize_absolute_cwd(raw_cwd: str | None, field_name: str) -> str | None:
    if raw_cwd in (None, ""):
        return None
    candidate = Path(raw_cwd).expanduser()
    if not candidate.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path, got: {raw_cwd}")
    return str(candidate.resolve())


def validate_state_transition(current: CodingJobState, new: CodingJobState) -> None:
    """Fail closed on invalid state changes.

    Terminal states never transition implicitly. A new attempt must be created via
    explicit retry or replay, which produces a new durable job record.
    """

    if new not in VALID_STATE_TRANSITIONS[current]:
        raise ValueError(
            f"Invalid coding job transition: {current.value} -> {new.value}"
        )


def resolve_effective_cwd(
    requested_cwd: str | None,
    worker_workspace_cwd: str | None,
    worker_runtime_cwd: str | None,
    allow_cwd_escape: bool = False,
) -> str:
    """Resolve working directory by the Phase 0 precedence contract.

    Precedence is:
    1. request cwd override
    2. worker workspace/worktree cwd
    3. worker runtime cwd
    4. fail fast
    """

    normalized_requested = _normalize_absolute_cwd(requested_cwd, "cwd")
    normalized_workspace = _normalize_absolute_cwd(
        worker_workspace_cwd,
        "worker_workspace_cwd",
    )
    if normalized_requested and normalized_workspace and not allow_cwd_escape:
        workspace_path = Path(normalized_workspace)
        requested_path = Path(normalized_requested)
        try:
            requested_path.relative_to(workspace_path)
        except ValueError as exc:
            raise ValueError(
                "cwd must stay within the worker workspace/worktree boundary unless "
                "allow_cwd_escape=true."
            ) from exc
    if normalized_requested:
        return normalized_requested

    if normalized_workspace:
        return normalized_workspace

    normalized_runtime = _normalize_absolute_cwd(
        worker_runtime_cwd,
        "worker_runtime_cwd",
    )
    if normalized_runtime:
        return normalized_runtime

    raise ValueError(
        "Unable to resolve effective cwd. Provide request cwd, worker workspace cwd, "
        "or worker runtime cwd."
    )


def default_startup_flags(
    provider: CodingProvider,
    skip_provider_permissions: bool,
) -> list[str]:
    """Return default provider flags under the trusted worker-owned runtime policy."""

    if not skip_provider_permissions:
        return []
    if provider == CodingProvider.claude:
        return ["--dangerously-skip-permissions"]
    if provider == CodingProvider.codex:
        return ["--dangerously-bypass-approvals-and-sandbox"]
    raise ValueError(f"Unsupported coding provider: {provider}")


class ResolvedStartupPolicy(BaseModel):
    """Resolved startup policy persisted for auditability."""

    model_config = {"populate_by_name": True}

    skip_provider_permissions: bool = Field(alias="skipProviderPermissions")
    source: str = "provider_default"
    applied_flags: list[str] = Field(default_factory=list, alias="appliedFlags")
    extra_args: list[str] = Field(default_factory=list, alias="extraArgs")


class CodingExecRequest(BaseModel):
    """Worker-to-runtime request contract for synchronous coding execution."""

    model_config = {"populate_by_name": True}

    team_name: str = Field(alias="teamName")
    worker_name: str = Field(alias="workerName")
    worker_id: str = Field(alias="workerId")
    leader_name: str | None = Field(default=None, alias="leaderName")
    task_id: str | None = Field(default=None, alias="taskId")
    provider: CodingProvider
    mode: CodingExecMode = CodingExecMode.implement
    prompt: str
    cwd: str | None = None
    worker_workspace_cwd: str | None = Field(default=None, alias="workerWorkspaceCwd")
    worker_runtime_cwd: str | None = Field(default=None, alias="workerRuntimeCwd")
    allow_cwd_escape: bool = Field(default=False, alias="allowCwdEscape")
    timeout_sec: int = Field(default=1800, alias="timeoutSec", ge=1)
    allow_write: bool = Field(default=True, alias="allowWrite")
    skip_provider_permissions: bool | None = Field(
        default=None,
        alias="skipProviderPermissions",
    )
    provider_args: list[str] = Field(default_factory=list, alias="providerArgs")
    max_infra_retries: int = Field(default=0, alias="maxInfraRetries", ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_paths(self) -> CodingExecRequest:
        _normalize_absolute_cwd(self.cwd, "cwd")
        _normalize_absolute_cwd(self.worker_workspace_cwd, "worker_workspace_cwd")
        _normalize_absolute_cwd(self.worker_runtime_cwd, "worker_runtime_cwd")
        return self

    def resolve_effective_cwd(self) -> str:
        return resolve_effective_cwd(
            requested_cwd=self.cwd,
            worker_workspace_cwd=self.worker_workspace_cwd,
            worker_runtime_cwd=self.worker_runtime_cwd,
            allow_cwd_escape=self.allow_cwd_escape,
        )


class CodingExecResult(BaseModel):
    """Normalized result that returns to the same worker after provider completion."""

    model_config = {"populate_by_name": True}

    schema_version: int = Field(default=PERSISTED_CODING_SCHEMA_VERSION, alias="schemaVersion", ge=1)
    job_id: str = Field(alias="jobId")
    provider: CodingProvider
    effective_cwd: str = Field(alias="effectiveCwd")
    status: CodingJobState
    exit_code: int | None = Field(default=None, alias="exitCode")
    summary: str = ""
    response_text: str = Field(default="", alias="responseText")
    next_suggestion: str = Field(default="", alias="nextSuggestion")
    signals: dict[str, bool] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @model_validator(mode="after")
    def validate_terminal_status(self) -> CodingExecResult:
        if self.status not in TERMINAL_CODING_JOB_STATES:
            raise ValueError(
                "CodingExecResult.status must be a terminal state, "
                f"got: {self.status.value}"
            )
        _normalize_absolute_cwd(self.effective_cwd, "effective_cwd")
        return self


class CodingJobEvent(BaseModel):
    """Durable event schema for job lifecycle inspection and replay."""

    model_config = {"populate_by_name": True}

    schema_version: int = Field(default=PERSISTED_CODING_SCHEMA_VERSION, alias="schemaVersion", ge=1)
    event_id: str = Field(alias="eventId")
    job_id: str = Field(alias="jobId")
    team_name: str = Field(alias="teamName")
    worker_name: str = Field(alias="workerName")
    state: CodingJobState | None = None
    event_type: CodingEventType = Field(alias="eventType")
    attempt_kind: CodingAttemptKind = Field(default=CodingAttemptKind.initial, alias="attemptKind")
    retry_count: int = Field(default=0, alias="retryCount", ge=0)
    replay_count: int = Field(default=0, alias="replayCount", ge=0)
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso, alias="createdAt")


class CodingJobRecord(BaseModel):
    """Durable job record persisted independently from process lifetime."""

    model_config = {"populate_by_name": True}

    schema_version: int = Field(default=PERSISTED_CODING_SCHEMA_VERSION, alias="schemaVersion", ge=1)
    job_id: str = Field(alias="jobId")
    team_name: str = Field(alias="teamName")
    worker_name: str = Field(alias="workerName")
    worker_id: str = Field(alias="workerId")
    leader_name: str | None = Field(default=None, alias="leaderName")
    task_id: str | None = Field(default=None, alias="taskId")
    provider: CodingProvider
    mode: CodingExecMode = CodingExecMode.implement
    state: CodingJobState
    requested_cwd: str | None = Field(default=None, alias="requestedCwd")
    worker_workspace_cwd: str | None = Field(default=None, alias="workerWorkspaceCwd")
    worker_runtime_cwd: str | None = Field(default=None, alias="workerRuntimeCwd")
    effective_cwd: str = Field(alias="effectiveCwd")
    startup_policy: ResolvedStartupPolicy = Field(alias="startupPolicy")
    exit_code: int | None = Field(default=None, alias="exitCode")
    summary: str = ""
    error: str | None = None
    artifact_paths: dict[str, str] = Field(default_factory=dict, alias="artifactPaths")
    request: dict[str, Any]
    result: dict[str, Any] | None = None
    created_at: str = Field(default_factory=_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=_now_iso, alias="updatedAt")
    started_at: str | None = Field(default=None, alias="startedAt")
    finished_at: str | None = Field(default=None, alias="finishedAt")
    root_job_id: str | None = Field(default=None, alias="rootJobId")
    parent_job_id: str | None = Field(default=None, alias="parentJobId")
    attempt_kind: CodingAttemptKind = Field(default=CodingAttemptKind.initial, alias="attemptKind")
    retry_count: int = Field(default=0, alias="retryCount", ge=0)
    replay_count: int = Field(default=0, alias="replayCount", ge=0)

    @model_validator(mode="after")
    def validate_paths_and_lineage(self) -> CodingJobRecord:
        _normalize_absolute_cwd(self.requested_cwd, "requested_cwd")
        _normalize_absolute_cwd(self.worker_workspace_cwd, "worker_workspace_cwd")
        _normalize_absolute_cwd(self.worker_runtime_cwd, "worker_runtime_cwd")
        _normalize_absolute_cwd(self.effective_cwd, "effective_cwd")
        if self.attempt_kind == CodingAttemptKind.initial:
            if self.retry_count != 0 or self.replay_count != 0:
                raise ValueError(
                    "Initial coding jobs must start with retry_count=0 and replay_count=0"
                )
        if self.attempt_kind == CodingAttemptKind.retry and self.retry_count < 1:
            raise ValueError("Retry jobs must increment retry_count")
        if self.attempt_kind == CodingAttemptKind.replay and self.replay_count < 1:
            raise ValueError("Replay jobs must increment replay_count")
        return self


def build_retry_lineage(previous: CodingJobRecord) -> dict[str, Any]:
    """Retry re-attempts infrastructure failures within the same logical lineage."""

    if previous.state not in {
        CodingJobState.failed,
        CodingJobState.timeout,
        CodingJobState.cancelled,
    }:
        raise ValueError(
            "Retry is only valid after infrastructure-oriented terminal states: "
            "failed, timeout, or cancelled."
        )
    return {
        "rootJobId": previous.root_job_id or previous.job_id,
        "parentJobId": previous.job_id,
        "attemptKind": CodingAttemptKind.retry,
        "retryCount": previous.retry_count + 1,
        "replayCount": previous.replay_count,
    }


def build_replay_lineage(previous: CodingJobRecord) -> dict[str, Any]:
    """Replay creates a new execution from persisted request data by explicit control."""

    if previous.state not in TERMINAL_CODING_JOB_STATES:
        raise ValueError("Replay requires a terminal prior job state.")
    return {
        "rootJobId": previous.root_job_id or previous.job_id,
        "parentJobId": previous.job_id,
        "attemptKind": CodingAttemptKind.replay,
        "retryCount": 0,
        "replayCount": previous.replay_count + 1,
    }
