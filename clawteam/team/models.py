"""Data models for multi-agent team coordination (aligned with teammate-tool spec)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


def get_data_dir() -> Path:
    """Return the data directory, respecting CLAWTEAM_DATA_DIR env var and config."""
    custom = os.environ.get("CLAWTEAM_DATA_DIR")
    if not custom:
        from clawteam.config import load_config
        custom = load_config().data_dir or None
    p = Path(custom) if custom else Path.home() / ".clawteam"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemberStatus(str, Enum):
    active = "active"
    idle = "idle"
    shutdown = "shutdown"


class TaskStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    blocked = "blocked"


class MessageType(str, Enum):
    message = "message"
    join_request = "join_request"
    join_approved = "join_approved"
    join_rejected = "join_rejected"
    plan_approval_request = "plan_approval_request"
    plan_approved = "plan_approved"
    plan_rejected = "plan_rejected"
    shutdown_request = "shutdown_request"
    shutdown_approved = "shutdown_approved"
    shutdown_rejected = "shutdown_rejected"
    idle = "idle"
    broadcast = "broadcast"


class WorkerCodingDecision(str, Enum):
    continue_ = "continue"
    report_progress = "report_progress"
    escalate = "escalate"
    complete = "complete"
    blocked = "blocked"


class TeamReusePolicy(str, Enum):
    reuse_existing = "reuse_existing"
    recreate_on_demand = "recreate_on_demand"
    fixed_profile = "fixed_profile"


class TaskLifecyclePhase(str, Enum):
    planned = "planned"
    execution = "execution"
    handoff = "handoff"
    review = "review"
    completed = "completed"
    blocked = "blocked"


class CallbackLifecyclePhase(str, Enum):
    not_required = "not_required"
    pending = "pending"
    reported = "reported"
    incomplete = "incomplete"
    escalated = "escalated"
    blocked = "blocked"
    closed = "closed"


class ReviewLifecyclePhase(str, Enum):
    not_started = "not_started"
    pending = "pending"
    in_review = "in_review"
    approved = "approved"
    changes_requested = "changes_requested"
    closed = "closed"


PERSISTED_CALLBACK_SCHEMA_VERSION = 1
PERSISTED_HANDOFF_SCHEMA_VERSION = 1


class TaskHandoffContract(BaseModel):
    """Structured worker->leader handoff artifact required for callback closure."""

    model_config = {"populate_by_name": True}

    schema_version: int = Field(default=PERSISTED_HANDOFF_SCHEMA_VERSION, alias="schemaVersion", ge=1)
    task_identity: str = Field(default="", alias="taskIdentity")
    objective: str = ""
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    validation: str = ""
    blockers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommended_next_step: str = Field(default="", alias="recommendedNextStep")
    callback_expectation: str = Field(default="", alias="callbackExpectation")
    metadata: dict[str, Any] = Field(default_factory=dict)

    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.task_identity.strip():
            missing.append("taskIdentity")
        if not self.objective.strip():
            missing.append("objective")
        if not self.inputs:
            missing.append("inputs")
        if not self.outputs:
            missing.append("outputs")
        if not self.validation.strip():
            missing.append("validation")
        if not self.blockers:
            missing.append("blockers")
        if not self.risks:
            missing.append("risks")
        if not self.recommended_next_step.strip():
            missing.append("recommendedNextStep")
        if not self.callback_expectation.strip():
            missing.append("callbackExpectation")
        return missing

    def is_complete(self) -> bool:
        return len(self.missing_fields()) == 0


class TeamMember(BaseModel):
    """A member of a team."""

    model_config = {"populate_by_name": True}

    name: str = Field(alias="name")
    user: str = Field(default="", alias="user")
    agent_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12], alias="agentId")
    agent_type: str = Field(default="general-purpose", alias="agentType")
    member_id: str = Field(default_factory=lambda: f"member-{uuid.uuid4().hex[:10]}", alias="memberId")
    member_nickname: str = Field(default="", alias="memberNickname")
    member_display_name: str = Field(default="", alias="memberDisplayName")
    member_role: str = Field(default="", alias="memberRole")
    preferred_session_key: str = Field(default="", alias="preferredSessionKey")
    session_routing: dict[str, Any] = Field(default_factory=dict, alias="sessionRouting")
    external_channel: str | None = Field(default=None, alias="externalChannel")
    joined_at: str = Field(default_factory=_now_iso, alias="joinedAt")

    @model_validator(mode="after")
    def hydrate_identity_defaults(self) -> "TeamMember":
        if not self.member_nickname:
            self.member_nickname = self.name
        if not self.member_display_name:
            self.member_display_name = self.member_nickname
        if not self.member_role:
            self.member_role = self.agent_type
        if not self.preferred_session_key:
            self.preferred_session_key = (
                f"{self.user}:{self.name}" if self.user else self.name
            )
        if not self.session_routing:
            self.session_routing = {
                "preferredSessionKey": self.preferred_session_key,
                "durableAuthority": "id_session_key",
                "liveNoticeEnabled": False,
            }
        return self


class TeamConfig(BaseModel):
    """Team configuration stored in config.json."""

    model_config = {"populate_by_name": True}

    name: str
    description: str = ""
    lead_agent_id: str = Field(default="", alias="leadAgentId")
    team_profile_id: str = Field(default_factory=lambda: f"teamprof-{uuid.uuid4().hex[:10]}", alias="teamProfileId")
    product_key: str = Field(default="", alias="productKey")
    team_reuse_policy: TeamReusePolicy = Field(
        default=TeamReusePolicy.reuse_existing,
        alias="teamReusePolicy",
    )
    session_bridge_mode: str = Field(default="durable_only", alias="sessionBridgeMode")
    created_at: str = Field(default_factory=_now_iso, alias="createdAt")
    members: list[TeamMember] = Field(default_factory=list)
    budget_cents: float = Field(default=0.0, alias="budgetCents")

    @model_validator(mode="after")
    def hydrate_team_defaults(self) -> "TeamConfig":
        if not self.product_key:
            self.product_key = self.name
        return self


class TeamMessage(BaseModel):
    """A message in the team mailbox system (aligned with teammate-tool).

    Uses exclude_none=True when serializing so only relevant fields appear.
    """

    model_config = {"populate_by_name": True}

    type: MessageType = MessageType.message
    from_agent: str = Field(alias="from", serialization_alias="from")
    to: str | None = None
    content: str | None = None
    request_id: str | None = Field(default=None, alias="requestId")
    timestamp: str = Field(default_factory=_now_iso)
    key: str | None = None
    # join_request fields
    proposed_name: str | None = Field(default=None, alias="proposedName")
    capabilities: str | None = None
    # join_approved fields
    assigned_name: str | None = Field(default=None, alias="assignedName")
    agent_id: str | None = Field(default=None, alias="agentId")
    team_name: str | None = Field(default=None, alias="teamName")
    # plan fields
    plan_file: str | None = Field(default=None, alias="planFile")
    summary: str | None = None
    plan: str | None = None
    # rejection/feedback
    feedback: str | None = None
    reason: str | None = None
    # idle notification fields
    last_task: str | None = Field(default=None, alias="lastTask")
    status: str | None = None


class TaskItem(BaseModel):
    """A task in the shared task list (aligned with teammate-tool)."""

    model_config = {"populate_by_name": True}

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    subject: str
    description: str = ""
    status: TaskStatus = TaskStatus.pending
    owner: str = ""
    locked_by: str = Field(default="", alias="lockedBy")
    locked_at: str = Field(default="", alias="lockedAt")
    blocks: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list, alias="blockedBy")
    started_at: str = Field(default="", alias="startedAt")
    task_lifecycle_phase: TaskLifecyclePhase = Field(default=TaskLifecyclePhase.planned, alias="taskLifecyclePhase")
    callback_lifecycle_phase: CallbackLifecyclePhase = Field(
        default=CallbackLifecyclePhase.not_required,
        alias="callbackLifecyclePhase",
    )
    review_lifecycle_phase: ReviewLifecyclePhase = Field(
        default=ReviewLifecyclePhase.not_started,
        alias="reviewLifecyclePhase",
    )
    handoff_complete: bool = Field(default=False, alias="handoffComplete")
    handoff_missing_fields: list[str] = Field(default_factory=list, alias="handoffMissingFields")
    created_at: str = Field(default_factory=_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=_now_iso, alias="updatedAt")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def hydrate_lifecycle_defaults(self) -> "TaskItem":
        if self.status == TaskStatus.in_progress:
            self.task_lifecycle_phase = TaskLifecyclePhase.execution
        elif self.status == TaskStatus.completed:
            self.task_lifecycle_phase = TaskLifecyclePhase.completed
        elif self.status == TaskStatus.blocked:
            self.task_lifecycle_phase = TaskLifecyclePhase.blocked
        elif self.task_lifecycle_phase not in {
            TaskLifecyclePhase.planned,
            TaskLifecyclePhase.handoff,
            TaskLifecyclePhase.review,
        }:
            self.task_lifecycle_phase = TaskLifecyclePhase.planned
        return self


class WorkerCodingCallbackReport(BaseModel):
    """Structured summary that a worker can send upward after `coding_exec` returns."""

    model_config = {"populate_by_name": True}

    schema_version: int = Field(default=PERSISTED_CALLBACK_SCHEMA_VERSION, alias="schemaVersion", ge=1)
    task_id: str | None = Field(default=None, alias="taskId")
    job_id: str = Field(alias="jobId")
    session_id: str | None = Field(default=None, alias="sessionId")
    provider_session_id: str | None = Field(default=None, alias="providerSessionId")
    worker_name: str | None = Field(default=None, alias="workerName")
    provider: str
    status: str
    decision: WorkerCodingDecision
    summary: str
    artifact_paths: dict[str, str] = Field(default_factory=dict, alias="artifactPaths")
    next_step: str = Field(default="", alias="nextStep")
    callback_expectation: str = Field(default="", alias="callbackExpectation")
    handoff_contract: TaskHandoffContract | None = Field(default=None, alias="handoffContract")
    escalation_reason: str | None = Field(default=None, alias="escalationReason")
    reported_at: str = Field(default_factory=_now_iso, alias="reportedAt")

    @classmethod
    def from_coding_result(
        cls,
        *,
        task_id: str | None,
        job_id: str,
        session_id: str | None = None,
        provider_session_id: str | None = None,
        worker_name: str | None = None,
        provider: str,
        status: str,
        decision: WorkerCodingDecision,
        summary: str,
        artifact_paths: dict[str, str] | None = None,
        next_step: str = "",
        callback_expectation: str = "team_leader_ack",
        handoff_contract: TaskHandoffContract | None = None,
        escalation_reason: str | None = None,
    ) -> "WorkerCodingCallbackReport":
        resolved_artifacts = artifact_paths or {}
        resolved_handoff = handoff_contract or TaskHandoffContract(
            taskIdentity=task_id or job_id,
            objective=summary,
            inputs=[],
            outputs=sorted(resolved_artifacts.keys()),
            validation="",
            blockers=[],
            risks=[],
            recommendedNextStep=next_step,
            callbackExpectation=callback_expectation,
        )
        return cls(
            taskId=task_id,
            jobId=job_id,
            sessionId=session_id,
            providerSessionId=provider_session_id,
            workerName=worker_name,
            provider=provider,
            status=status,
            decision=decision,
            summary=summary,
            artifactPaths=resolved_artifacts,
            nextStep=next_step,
            callbackExpectation=callback_expectation,
            handoffContract=resolved_handoff,
            escalationReason=escalation_reason,
        )

    def to_leader_summary(self) -> str:
        parts = [
            "Coding callback report:",
            f"job={self.job_id}",
            f"provider={self.provider}",
            f"status={self.status}",
            f"decision={self.decision.value}",
        ]
        if self.task_id:
            parts.append(f"task={self.task_id}")
        parts.append(f"summary={self.summary}")
        if self.next_step:
            parts.append(f"next={self.next_step}")
        if self.callback_expectation:
            parts.append(f"expectation={self.callback_expectation}")
        if self.handoff_contract is not None:
            missing = self.handoff_contract.missing_fields()
            parts.append(f"handoff={'complete' if not missing else 'incomplete'}")
            if missing:
                parts.append(f"missing={','.join(missing)}")
        if self.escalation_reason:
            parts.append(f"escalation={self.escalation_reason}")
        if self.artifact_paths:
            parts.append(f"artifacts={json.dumps(self.artifact_paths, ensure_ascii=False)}")
        return " | ".join(parts)
