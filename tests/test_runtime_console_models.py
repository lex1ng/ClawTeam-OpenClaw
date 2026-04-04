"""Phase 1 tests for runtime console domain models."""

from __future__ import annotations

import json

from clawteam.runtime_console.models import ProviderSessionRecord


def test_provider_session_model_represents_ephemeral_unavailable_honestly():
    record = ProviderSessionRecord(
        sessionId="psess-job-1",
        providerSessionId=None,
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

    dumped = json.loads(record.model_dump_json(by_alias=True, exclude_none=True))

    assert dumped["schemaVersion"] == 1
    assert dumped["sessionId"] == "psess-job-1"
    assert "providerSessionId" not in dumped
    assert dumped["sessionMode"] == "ephemeral"
    assert dumped["resumeSupported"] is False
