#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _log_path() -> Path:
    data_dir = Path(os.environ["CLAWTEAM_DATA_DIR"])
    log_dir = data_dir / "smoke-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"worker-{os.environ.get('CLAWTEAM_AGENT_NAME', 'unknown')}.log"


def log(message: str) -> None:
    path = _log_path()
    path.write_text(
        path.read_text(encoding="utf-8") + message + "\n" if path.exists() else message + "\n",
        encoding="utf-8",
    )


def run_cli(*args: str, json_output: bool = False, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    binary = os.environ.get("CLAWTEAM_BIN", "clawteam")
    command = [binary]
    if json_output:
        command.append("--json")
    command.extend(args)
    log(f"$ {' '.join(command)}")
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=os.environ.copy(),
    )
    log(f"exit={completed.returncode}")
    if completed.stdout:
        log(f"stdout={completed.stdout.strip()}")
    if completed.stderr:
        log(f"stderr={completed.stderr.strip()}")
    if completed.returncode != 0:
        raise RuntimeError(
            f"CLI failed: {' '.join(command)}\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return completed


def run_cli_json(*args: str, last_line: bool = False, timeout: float = 30.0) -> dict:
    completed = run_cli(*args, json_output=True, timeout=timeout)
    payload_text = completed.stdout.strip().splitlines()[-1] if last_line else completed.stdout
    return json.loads(payload_text)


def resolve_leader_name(team_name: str) -> str:
    status = run_cli_json("team", "status", team_name)
    lead_agent_id = status["leadAgentId"]
    for member in status["members"]:
        if member["agentId"] == lead_agent_id:
            return member["name"]
    for member in status["members"]:
        if member.get("agentType") == "leader":
            return member["name"]
    return status["members"][0]["name"]


def wait_for_owned_task(team_name: str, agent_name: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = run_cli_json("task", "list", team_name, "--owner", agent_name)
        tasks = payload.get("tasks", [])
        if tasks:
            return tasks[0]
        time.sleep(0.2)
    raise RuntimeError(f"No task owned by {agent_name} appeared within {timeout} seconds")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--prompt", default="")
    args = parser.parse_args()

    team_name = os.environ["CLAWTEAM_TEAM_NAME"]
    agent_name = os.environ["CLAWTEAM_AGENT_NAME"]
    agent_id = os.environ["CLAWTEAM_AGENT_ID"]
    provider = os.environ.get("CLAWTEAM_SMOKE_PROVIDER", "claude")
    callback_decision = os.environ.get("CLAWTEAM_SMOKE_CALLBACK_DECISION", "report_progress")
    callback_next_step = os.environ.get("CLAWTEAM_SMOKE_CALLBACK_NEXT_STEP", "notify leader and finalize task")
    callback_summary_override = os.environ.get("CLAWTEAM_SMOKE_CALLBACK_SUMMARY", "")
    escalation_reason = os.environ.get("CLAWTEAM_SMOKE_ESCALATION_REASON", "")
    coding_timeout = os.environ.get("CLAWTEAM_SMOKE_CODING_TIMEOUT", "20")
    log(f"worker started team={team_name} agent={agent_name} id={agent_id}")
    if args.prompt:
        log(f"prompt={args.prompt}")
    log(
        "smoke-config "
        f"provider={provider} decision={callback_decision} timeout={coding_timeout}"
    )

    task = wait_for_owned_task(team_name, agent_name)
    task_id = task["id"]
    leader_name = resolve_leader_name(team_name)
    run_cli("task", "update", team_name, task_id, "--status", "in_progress")
    run_cli(
        "inbox",
        "send",
        team_name,
        leader_name,
        f"worker={agent_name} task={task_id} status=in_progress",
        "--from",
        agent_name,
    )

    exec_payload = run_cli_json(
        "coding",
        "exec",
        provider,
        f"Smoke implementation for task {task_id}",
        "--team",
        team_name,
        "--task-id",
        task_id,
        "--timeout-sec",
        coding_timeout,
    )
    job_id = exec_payload["jobId"]
    wait_payload = run_cli_json(
        "coding",
        "wait",
        job_id,
        "--team",
        team_name,
        "--poll-interval",
        "0.2",
        "--timeout",
        coding_timeout,
    )
    if wait_payload["state"] != "completed":
        result_payload = run_cli_json("coding", "result", job_id, "--team", team_name)
        log(f"failed-job={result_payload}")
        raise RuntimeError(
            "Expected completed job, "
            f"got state={wait_payload['state']} summary={result_payload.get('summary', '')} "
            f"error={result_payload.get('error', '')}"
        )
    result_payload = run_cli_json("coding", "result", job_id, "--team", team_name)
    callback_summary = callback_summary_override or result_payload.get("summary", "")
    callback_payload = run_cli_json(
        "coding",
        "callback-report",
        job_id,
        "--team",
        team_name,
        "--decision",
        callback_decision,
        "--summary",
        callback_summary,
        "--next-step",
        callback_next_step,
        *(
            ["--escalation-reason", escalation_reason]
            if callback_decision == "escalate" and escalation_reason
            else []
        ),
    )
    log(f"callback={callback_payload}")

    run_cli("task", "update", team_name, task_id, "--status", "completed")
    run_cli(
        "inbox",
        "send",
        team_name,
        leader_name,
        (
            f"worker={agent_name} task={task_id} job={job_id} "
            f"status=completed summary={result_payload.get('summary', '')}"
        ),
        "--from",
        agent_name,
    )
    log(f"worker completed job={job_id}")
    print(json.dumps({"taskId": task_id, "jobId": job_id, "status": "completed"}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - failure path used for smoke debugging
        log(f"error={exc}")
        print(str(exc), file=sys.stderr)
        raise
