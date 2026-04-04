"""Phase 2 tests for the Codex CLI harness."""

from __future__ import annotations

import json

from clawteam.coding.harness.codex_cli import CodexCliHarness
from clawteam.coding.models import CodingExecRequest, CodingJobState, ResolvedStartupPolicy


def _request(**overrides) -> CodingExecRequest:
    data = {
        "teamName": "alpha",
        "workerName": "worker-1",
        "workerId": "worker-id-1",
        "provider": "codex",
        "prompt": "Review the runtime core",
        "workerWorkspaceCwd": "/tmp/worktree",
    }
    data.update(overrides)
    return CodingExecRequest(**data)


def _structured_output(summary: str, response_text: str) -> str:
    payload = json.dumps(
        {
            "summary": summary,
            "responseText": response_text,
            "signals": {},
        }
    )
    return (
        "CLAWTEAM_RESULT_JSON_START\n"
        f"{payload}\n"
        "CLAWTEAM_RESULT_JSON_END\n"
    )


def test_codex_harness_builds_command_with_default_flag(monkeypatch):
    captured = {}

    class Result:
        returncode = 0
        stdout = _structured_output("Review completed", "Needs one cleanup pass")
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return Result()

    monkeypatch.setattr("clawteam.coding.harness.base.shutil.which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr("clawteam.coding.harness.base.subprocess.run", fake_run)

    execution = CodexCliHarness().exec(
        "job-1",
        _request(),
        "/tmp/worktree",
        ResolvedStartupPolicy(
            skipProviderPermissions=True,
            appliedFlags=["--dangerously-bypass-approvals-and-sandbox"],
        ),
    )

    assert captured["command"][:2] == [
        "codex",
        "--dangerously-bypass-approvals-and-sandbox",
    ]
    assert "Review the runtime core" in captured["command"][2]
    assert "CLAWTEAM_RESULT_JSON_START" in captured["command"][2]
    assert captured["cwd"] == "/tmp/worktree"
    assert execution.result.status == CodingJobState.completed
    assert execution.result.response_text == "Needs one cleanup pass"


def test_codex_harness_normalizes_nonzero_exit(monkeypatch):
    class Result:
        returncode = 3
        stdout = "partial output"
        stderr = "command failed"

    monkeypatch.setattr("clawteam.coding.harness.base.shutil.which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr("clawteam.coding.harness.base.subprocess.run", lambda *a, **k: Result())

    execution = CodexCliHarness().exec(
        "job-1",
        _request(),
        "/tmp/worktree",
        ResolvedStartupPolicy(
            skipProviderPermissions=True,
            appliedFlags=["--dangerously-bypass-approvals-and-sandbox"],
        ),
    )

    assert execution.result.status == CodingJobState.failed
    assert execution.result.exit_code == 3
    assert execution.result.response_text == ""
    assert execution.result.error == "command failed"


def test_codex_harness_fails_closed_when_binary_missing(monkeypatch):
    monkeypatch.setattr("clawteam.coding.harness.base.shutil.which", lambda _: None)

    execution = CodexCliHarness().exec(
        "job-1",
        _request(),
        "/tmp/worktree",
        ResolvedStartupPolicy(
            skipProviderPermissions=False,
            appliedFlags=[],
        ),
    )

    assert execution.result.status == CodingJobState.failed
    assert "not found in PATH" in execution.result.error
    assert execution.artifact_payloads["invocation"].data["jobId"] == "job-1"
