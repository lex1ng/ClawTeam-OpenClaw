"""Session bridge preparation layer.

This module provides a non-authoritative durable placeholder for low-latency
session-native notices. Durable task/callback/fault records remain authority.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from clawteam.team.models import TeamMember, get_data_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bridge_root(team_name: str) -> Path:
    root = get_data_dir() / "runtime-console" / "session-bridge" / team_name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f"{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(payload)
        Path(tmp_path).replace(path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


class SessionBridgeNotice(BaseModel):
    """Durable non-authoritative session bridge notice."""

    model_config = {"populate_by_name": True}

    schema_version: int = Field(default=1, alias="schemaVersion", ge=1)
    notice_id: str = Field(alias="noticeId")
    team_name: str = Field(alias="teamName")
    notice_type: str = Field(alias="noticeType")
    from_member_id: str = Field(alias="fromMemberId")
    to_member_id: str = Field(alias="toMemberId")
    from_agent_id: str = Field(alias="fromAgentId")
    to_agent_id: str = Field(alias="toAgentId")
    from_session_key: str = Field(alias="fromSessionKey")
    to_session_key: str = Field(alias="toSessionKey")
    task_id: str | None = Field(default=None, alias="taskId")
    job_id: str | None = Field(default=None, alias="jobId")
    payload: dict[str, Any] = Field(default_factory=dict)
    transport_status: str = Field(default="not_configured", alias="transportStatus")
    delivery_mode: str = Field(default="durable_hook_only", alias="deliveryMode")
    authoritative: bool = False
    created_at: str = Field(default_factory=_now_iso, alias="createdAt")


class SessionBridge:
    """Prepares machine-facing session-native routing notices."""

    def notice_path(self, team_name: str, notice_id: str) -> Path:
        return _bridge_root(team_name) / f"{notice_id}.json"

    def notify_worker_to_leader(
        self,
        *,
        team_name: str,
        worker_member: TeamMember,
        leader_member: TeamMember,
        task_id: str | None,
        job_id: str | None,
        payload: dict[str, Any] | None = None,
    ) -> SessionBridgeNotice:
        notice = SessionBridgeNotice(
            noticeId=f"sbridge-{uuid.uuid4().hex[:12]}",
            teamName=team_name,
            noticeType="worker_to_team_leader",
            fromMemberId=worker_member.member_id,
            toMemberId=leader_member.member_id,
            fromAgentId=worker_member.agent_id,
            toAgentId=leader_member.agent_id,
            fromSessionKey=worker_member.preferred_session_key,
            toSessionKey=leader_member.preferred_session_key,
            taskId=task_id,
            jobId=job_id,
            payload=payload or {},
        )
        _atomic_write(
            self.notice_path(team_name, notice.notice_id),
            notice.model_dump_json(indent=2, by_alias=True, exclude_none=True),
        )
        return notice

    def list_notices(self, team_name: str, *, limit: int = 50) -> list[SessionBridgeNotice]:
        notices: list[SessionBridgeNotice] = []
        for path in sorted(_bridge_root(team_name).glob("*.json"), reverse=True)[: max(1, limit)]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                notices.append(SessionBridgeNotice.model_validate(data))
            except Exception:
                continue
        return notices
