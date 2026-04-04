"""Phase 2 tests for the Claude CLI harness."""

from __future__ import annotations

import json
import subprocess

from clawteam.coding.harness.claude_cli import ClaudeCliHarness
from clawteam.coding.models import CodingExecRequest, CodingJobState, ResolvedStartupPolicy


def _request(**overrides) -> CodingExecRequest:
    data = {
        "teamName": "alpha",
        "workerName": "worker-1",
        "workerId": "worker-id-1",
        "provider": "claude",
        "prompt": "Implement retries",
        "workerWorkspaceCwd": "/tmp/worktree",
    }
    data.update(overrides)
    return CodingExecRequest(**data)


def _structured_output(summary: str, response_text: str, next_suggestion: str = "") -> str:
    payload = json.dumps(
        {
            "summary": summary,
            "responseText": response_text,
            "nextSuggestion": next_suggestion,
            "signals": {"needsReview": False},
        }
    )
    return (
        "preamble\n"
        "CLAWTEAM_RESULT_JSON_START\n"
        f"{payload}\n"
        "CLAWTEAM_RESULT_JSON_END\n"
    )


def test_claude_harness_builds_command_with_default_flag_and_prompt(monkeypatch):
    captured = {}

    class Result:
        returncode = 0
        stdout = _structured_output("Implemented retry policy", "Patch applied")
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        captured["timeout"] = kwargs["timeout"]
        return Result()

    monkeypatch.setattr("clawteam.coding.harness.base.shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr("clawteam.coding.harness.base.subprocess.run", fake_run)

    harness = ClaudeCliHarness()
    execution = harness.exec(
        "job-1",
        _request(timeoutSec=30),
        "/tmp/worktree",
        ResolvedStartupPolicy(
            skipProviderPermissions=True,
            appliedFlags=["--dangerously-skip-permissions"],
        ),
    )

    assert captured["command"][:3] == ["claude", "--dangerously-skip-permissions", "-p"]
    assert "Implement retries" in captured["command"][3]
    assert "CLAWTEAM_RESULT_JSON_START" in captured["command"][3]
    assert captured["cwd"] == "/tmp/worktree"
    assert captured["timeout"] == 30
    assert execution.result.status == CodingJobState.completed
    assert execution.result.summary == "Implemented retry policy"
    assert execution.result.response_text == "Patch applied"
    assert execution.result.artifacts["stdoutLog"] == "stdout.log"


def test_claude_harness_honors_startup_policy_override(monkeypatch):
    captured = {}

    class Result:
        returncode = 0
        stdout = _structured_output("ok", "usable response")
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        return Result()

    monkeypatch.setattr("clawteam.coding.harness.base.shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr("clawteam.coding.harness.base.subprocess.run", fake_run)

    execution = ClaudeCliHarness().exec(
        "job-1",
        _request(),
        "/tmp/worktree",
        ResolvedStartupPolicy(
            skipProviderPermissions=False,
            source="request",
            appliedFlags=[],
            extraArgs=["--model", "sonnet"],
        ),
    )

    assert captured["command"][:4] == ["claude", "--model", "sonnet", "-p"]
    assert "Implement retries" in captured["command"][4]
    assert execution.result.status == CodingJobState.completed


def test_claude_harness_normalizes_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["claude"],
            timeout=15,
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr("clawteam.coding.harness.base.shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr("clawteam.coding.harness.base.subprocess.run", fake_run)

    execution = ClaudeCliHarness().exec(
        "job-1",
        _request(timeoutSec=15),
        "/tmp/worktree",
        ResolvedStartupPolicy(
            skipProviderPermissions=True,
            appliedFlags=["--dangerously-skip-permissions"],
        ),
    )

    assert execution.result.status == CodingJobState.timeout
    assert execution.result.response_text == ""
    assert execution.result.error == "partial stderr"
    assert execution.artifact_payloads["stderrLog"].text == "partial stderr"


def test_claude_harness_normalizes_startup_failure(monkeypatch):
    def fake_run(*args, **kwargs):
        raise OSError("exec format error")

    monkeypatch.setattr("clawteam.coding.harness.base.shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr("clawteam.coding.harness.base.subprocess.run", fake_run)

    execution = ClaudeCliHarness().exec(
        "job-1",
        _request(),
        "/tmp/worktree",
        ResolvedStartupPolicy(
            skipProviderPermissions=True,
            appliedFlags=["--dangerously-skip-permissions"],
        ),
    )

    assert execution.result.status == CodingJobState.failed
    assert execution.result.metrics["failureKind"] == "startup"
    assert execution.result.error == "exec format error"


def test_claude_harness_fails_closed_on_normalization_error(monkeypatch):
    class Result:
        returncode = 0
        stdout = "plain prose with no markers"
        stderr = ""

    monkeypatch.setattr("clawteam.coding.harness.base.shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr("clawteam.coding.harness.base.subprocess.run", lambda *a, **k: Result())

    execution = ClaudeCliHarness().exec(
        "job-1",
        _request(),
        "/tmp/worktree",
        ResolvedStartupPolicy(
            skipProviderPermissions=True,
            appliedFlags=["--dangerously-skip-permissions"],
        ),
    )

    assert execution.result.status == CodingJobState.failed
    assert execution.result.metrics["failureKind"] == "normalization"
    assert "missing structured result markers" in execution.result.error
