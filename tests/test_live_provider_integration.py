from __future__ import annotations

import os
import shutil
import time

import pytest

from tests.smoke.helpers import isolated_smoke_context


LIVE_SMOKE_ENV = "CLAWTEAM_ENABLE_LIVE_SMOKE"
LIVE_PROVIDER_ENV = "CLAWTEAM_LIVE_PROVIDER"


def _require_live_provider() -> tuple[str, str]:
    if os.environ.get(LIVE_SMOKE_ENV) != "1":
        pytest.skip(
            f"live integration smoke disabled; set {LIVE_SMOKE_ENV}=1 to run against a real provider."
        )
    provider = os.environ.get(LIVE_PROVIDER_ENV, "claude").strip().lower()
    if provider not in {"claude", "codex"}:
        pytest.skip(
            f"unsupported live provider {provider!r}; set {LIVE_PROVIDER_ENV}=claude or codex."
        )
    binary = shutil.which(provider)
    if binary is None:
        pytest.skip(f"live provider {provider!r} is not installed or not on PATH.")
    return provider, binary


def _classify_external_failure(provider: str, text: str) -> str | None:
    lower = text.lower()
    login_markers = (
        "login",
        "log in",
        "logged in",
        "not authenticated",
        "authentication",
        "auth required",
        "sign in",
        "api key",
        "invalid api key",
        "unauthorized",
        "forbidden",
    )
    network_markers = (
        "network",
        "timed out",
        "timeout",
        "connection reset",
        "connection refused",
        "connection error",
        "enotfound",
        "econn",
        "dns",
        "tls",
        "temporary failure",
    )
    gateway_markers = (
        "gateway",
        "daemon",
        "server unavailable",
        "service unavailable",
    )
    if any(marker in lower for marker in login_markers):
        return f"{provider} is installed but not ready for authenticated use: {text.strip()}"
    if any(marker in lower for marker in network_markers):
        return f"{provider} live smoke hit an external network/provider outage: {text.strip()}"
    if any(marker in lower for marker in gateway_markers):
        return f"{provider} live smoke depends on an unavailable gateway/service: {text.strip()}"
    return None


def _wait_for_live_outcome(ctx, *, team_name: str, task_id: str, worker_name: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    last_observation: dict = {}
    while time.monotonic() < deadline:
        task = ctx.run_cli_json("task", "get", team_name, task_id)
        jobs_payload = ctx.run_cli_json("coding", "list", "--team", team_name)
        jobs = [job for job in jobs_payload["jobs"] if job.get("taskId") == task_id]
        worker_log = ctx.worker_log(worker_name)
        last_observation = {"task": task, "jobs": jobs, "workerLog": worker_log}
        if task["status"] == "completed":
            return {"kind": "completed", **last_observation}
        for job in jobs:
            if job["state"] in {"failed", "timeout", "cancelled"}:
                result = ctx.run_cli_json("coding", "result", job["jobId"], "--team", team_name)
                stderr = ctx.run_cli_json(
                    "coding",
                    "artifact",
                    job["jobId"],
                    "--team",
                    team_name,
                    "--name",
                    "stderrLog",
                )
                return {
                    "kind": "provider_failed",
                    "task": task,
                    "jobs": jobs,
                    "workerLog": worker_log,
                    "job": job,
                    "result": result,
                    "stderrArtifact": stderr,
                }
        if "error=" in worker_log:
            return {"kind": "worker_error", **last_observation}
        time.sleep(0.5)
    return {"kind": "timeout", **last_observation}


def test_live_smoke_fake_openclaw_with_real_provider(tmp_path):
    provider, binary = _require_live_provider()

    with isolated_smoke_context(
        tmp_path,
        f"live-provider-{provider}",
        provider_binaries={provider: binary},
    ) as ctx:
        ctx.env["CLAWTEAM_SMOKE_PROVIDER"] = provider
        ctx.env["CLAWTEAM_SMOKE_CODING_TIMEOUT"] = "120"

        team_name = f"live-{provider}-smoke"
        worker_name = "worker1"
        run_dir = ctx.root / "run"
        run_dir.mkdir(parents=True, exist_ok=True)

        ctx.run_cli("team", "spawn-team", team_name, "-d", "live provider smoke", "-n", "leader")
        ctx.register_team(team_name, None)
        task = ctx.run_cli_json("task", "create", team_name, f"live {provider} smoke", "--owner", worker_name)

        spawn_payload = ctx.run_cli_json(
            "spawn",
            "--team",
            team_name,
            "--agent-name",
            worker_name,
            "--no-workspace",
            "--repo",
            str(run_dir),
            "--task",
            f"Execute live {provider} smoke task {task['id']}",
        )
        assert spawn_payload["status"] == "spawned"

        ctx.wait_until(
            lambda: ctx.openclaw_invocations() or None,
            timeout=15.0,
            interval=0.2,
            description="fake OpenClaw live invocation",
        )
        outcome = _wait_for_live_outcome(
            ctx,
            team_name=team_name,
            task_id=task["id"],
            worker_name=worker_name,
            timeout=150.0,
        )

        if outcome["kind"] != "completed":
            error_text = "\n".join(
                part
                for part in (
                    outcome.get("workerLog", ""),
                    outcome.get("result", {}).get("error", "") if outcome.get("result") else "",
                    outcome.get("result", {}).get("summary", "") if outcome.get("result") else "",
                    outcome.get("stderrArtifact", {}).get("content", "") if outcome.get("stderrArtifact") else "",
                )
                if part
            )
            external_reason = _classify_external_failure(provider, error_text)
            if external_reason:
                pytest.skip(external_reason)
            pytest.fail(
                "live provider smoke did not complete successfully.\n"
                f"outcome={outcome['kind']}\n"
                f"provider={provider}\n"
                f"details=\n{error_text or outcome}"
            )

        coding_list = ctx.run_cli_json("coding", "list", "--team", team_name)
        assert coding_list["jobs"], "expected a coding job from the live provider smoke"
        job = next(job for job in coding_list["jobs"] if job["taskId"] == task["id"])
        job_id = job["jobId"]
        coding_status = ctx.run_cli_json("coding", "status", job_id, "--team", team_name)
        coding_result = ctx.run_cli_json("coding", "result", job_id, "--team", team_name)
        board_json = ctx.run_cli_json("board", "show", team_name)
        board = ctx.start_board_server(team_name, host="127.0.0.1")
        callbacks_api = ctx.http_get_json(board.base_url, f"/api/teams/{team_name}/callbacks")

        assert coding_status["provider"] == provider
        assert coding_status["state"] == "completed"
        assert coding_result["status"] == "completed"
        assert coding_result["summary"]
        assert callbacks_api["callbacks"], "expected callback persistence on the live provider path"
        callback = callbacks_api["callbacks"][0]
        assert callback["jobId"] == job_id
        assert callback["decision"] == "report_progress"
        assert board_json["runtimeConsole"]["callbacks"][0]["jobId"] == job_id
        assert board_json["runtimeConsole"]["callbacks"][0]["decision"] == "report_progress"
