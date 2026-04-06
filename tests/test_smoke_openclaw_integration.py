from __future__ import annotations

import subprocess
from pathlib import Path

from tests.smoke.helpers import isolated_smoke_context


def _run_openclaw_chain(ctx, *, team_name: str, worker_name: str) -> dict:
    run_dir = ctx.root / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    ctx.run_cli("team", "spawn-team", team_name, "-d", "openclaw integration smoke", "-n", "leader")
    ctx.register_team(team_name, None)
    task = ctx.run_cli_json("task", "create", team_name, "openclaw integration smoke", "--owner", worker_name)

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
        f"Execute OpenClaw integration smoke task {task['id']}",
    )

    inbox_progress = ctx.wait_until(
        lambda: _inbox_with_status(ctx, team_name, "status=in_progress"),
        timeout=25.0,
        interval=0.2,
        description="OpenClaw worker progress signal",
    )
    wait_payload = ctx.run_cli_json(
        "task",
        "wait",
        team_name,
        "--timeout",
        "25",
        "--poll-interval",
        "0.2",
        last_line=True,
    )
    task_payload = ctx.run_cli_json("task", "get", team_name, task["id"])
    coding_list = ctx.run_cli_json("coding", "list", "--team", team_name)
    job = next(job for job in coding_list["jobs"] if job["taskId"] == task["id"])
    job_id = job["jobId"]
    coding_status = ctx.run_cli_json("coding", "status", job_id, "--team", team_name)
    coding_result = ctx.run_cli_json("coding", "result", job_id, "--team", team_name)
    coding_events = ctx.run_cli_json("coding", "events", job_id, "--team", team_name)
    coding_artifacts = ctx.run_cli_json("coding", "artifacts", job_id, "--team", team_name)
    faults = ctx.run_cli_json("faults", "list", "--team", team_name)
    timeline = ctx.run_cli_json("audit", "timeline", "--team", team_name)
    board_show = ctx.run_cli("board", "show", team_name)
    board_json = ctx.run_cli_json("board", "show", team_name)
    board = ctx.start_board_server(team_name, host="127.0.0.1")
    callbacks_api = ctx.http_get_json(board.base_url, f"/api/teams/{team_name}/callbacks")
    timeline_api = ctx.http_get_json(board.base_url, f"/api/teams/{team_name}/timeline")
    invocations = ctx.wait_until(
        lambda: ctx.openclaw_invocations() or None,
        timeout=10.0,
        interval=0.1,
        description="fake OpenClaw invocation log",
    )

    return {
        "task": task,
        "taskPayload": task_payload,
        "spawn": spawn_payload,
        "inboxProgress": inbox_progress,
        "wait": wait_payload,
        "codingList": coding_list,
        "jobId": job_id,
        "codingStatus": coding_status,
        "codingResult": coding_result,
        "codingEvents": coding_events,
        "codingArtifacts": coding_artifacts,
        "faults": faults,
        "timeline": timeline,
        "boardShow": board_show,
        "boardJson": board_json,
        "callbacksApi": callbacks_api,
        "timelineApi": timeline_api,
        "openclawInvocations": invocations,
        "workerLog": ctx.worker_log(worker_name),
    }


def _inbox_with_status(ctx, team_name: str, marker: str) -> dict | None:
    payload = ctx.run_cli_json("inbox", "log", team_name)
    if any(marker in message["content"] for message in payload["messages"]):
        return payload
    return None


def test_smoke_openclaw_default_spawn_makes_progress(tmp_path):
    root = tmp_path / "openclaw-default-progress"
    team_name = "smoke-openclaw-progress"
    session_name = f"clawteam-{team_name}"

    with isolated_smoke_context(tmp_path, "openclaw-default-progress") as ctx:
        result = _run_openclaw_chain(ctx, team_name=team_name, worker_name="worker1")

        assert result["spawn"]["status"] == "spawned"
        assert result["spawn"]["backend"] == "tmux"
        assert result["spawn"]["workspace"]["status"] == "disabled"
        assert result["wait"]["status"] == "completed"
        assert result["taskPayload"]["status"] == "completed"
        assert any(
            "status=in_progress" in message["content"]
            for message in result["inboxProgress"]["messages"]
        )
        assert "worker completed job=" in result["workerLog"]
        assert result["faults"]["faults"] == []

        invocation = result["openclawInvocations"][0]
        assert invocation["mode"] == "tui"
        assert invocation["deliver"] is True
        assert invocation["status"] == "ok"
        assert invocation["session"] == f"clawteam-{team_name}-worker1"
        assert "Execute OpenClaw integration smoke task" in (invocation["message"] or "")
        assert "First action: run `clawteam task list" in (invocation["message"] or "")

    assert not root.exists()
    session_check = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert session_check.returncode != 0


def test_smoke_openclaw_path_persists_callback(tmp_path):
    with isolated_smoke_context(tmp_path, "openclaw-callback-persistence") as ctx:
        result = _run_openclaw_chain(ctx, team_name="smoke-openclaw-callback", worker_name="worker1")

        assert result["codingStatus"]["state"] == "completed"
        assert result["codingResult"]["status"] == "completed"
        assert result["codingResult"]["summary"] == "smoke ok"
        assert [event["eventType"] for event in result["codingEvents"]["events"]] == [
            "created",
            "started",
            "completed",
        ]
        artifact_names = {artifact["name"] for artifact in result["codingArtifacts"]["artifacts"]}
        assert {"stdoutLog", "stderrLog", "invocation", "jobRecord", "resultJson"}.issubset(artifact_names)
        callbacks = result["callbacksApi"]["callbacks"]
        assert callbacks, "expected callback record on the OpenClaw-driven path"
        callback = callbacks[0]
        assert callback["jobId"] == result["jobId"]
        assert callback["taskId"] == result["task"]["id"]
        assert callback["decision"] == "report_progress"
        assert callback["summary"] == "smoke ok"
        assert result["boardJson"]["runtimeConsole"]["callbacks"][0]["jobId"] == result["jobId"]
        assert result["boardJson"]["runtimeConsole"]["callbacks"][0]["decision"] == "report_progress"
        timeline_event_types = {event["eventType"] for event in result["timeline"]["events"]}
        assert "callback_reported" in timeline_event_types
        assert any(event["eventType"] == "callback_reported" for event in result["timelineApi"]["events"])
        assert "Task Board" in result["boardShow"].stdout


def test_smoke_openclaw_launch_failure_is_explicit(tmp_path):
    with isolated_smoke_context(tmp_path, "openclaw-malformed") as ctx:
        openclaw_bin = ctx.bin_dir / "openclaw"
        failed = subprocess.run(
            [str(openclaw_bin), "tui", "--session", "broken-session", "--message", "missing deliver"],
            cwd=str(ctx.root),
            env=ctx.env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert failed.returncode != 0
        assert "requires `--deliver`" in failed.stderr
        invocation = ctx.openclaw_invocations()[0]
        assert invocation["mode"] == "tui"
        assert invocation["deliver"] is False
        assert invocation["status"] == "error"
        assert invocation["error"] == "fake openclaw smoke shim requires `--deliver` for TUI delivery."
