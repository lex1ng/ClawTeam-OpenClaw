from __future__ import annotations

from pathlib import Path

from tests.smoke.helpers import REPO_ROOT, init_git_repo, isolated_smoke_context


FAKE_WORKER = REPO_ROOT / "tests" / "smoke" / "fake_worker.py"


def _run_full_chain(
    ctx,
    *,
    team_name: str,
    worker_name: str,
    task_subject: str,
    repo: Path,
    workspace_mode: str,
):
    ctx.run_cli("team", "spawn-team", team_name, "-d", "standalone smoke", "-n", "leader")
    ctx.register_team(team_name, repo if workspace_mode != "never" else None)
    task = ctx.run_cli_json("task", "create", team_name, task_subject, "--owner", worker_name)

    spawn_args = [
        "spawn",
        "subprocess",
        ctx.python_bin,
        str(FAKE_WORKER),
        "--team",
        team_name,
        "--agent-name",
        worker_name,
        "--repo",
        str(repo),
        "--task",
        f"Execute standalone smoke task {task['id']}",
    ]
    if workspace_mode == "never":
        spawn_args.append("--no-workspace")
    elif workspace_mode == "always":
        spawn_args.append("--workspace")
    spawn_payload = ctx.run_cli_json(*spawn_args)
    worker_pid = ctx.register_worker_from_registry(team_name, worker_name)

    wait_payload = ctx.run_cli_json(
        "task",
        "wait",
        team_name,
        "--timeout",
        "20",
        "--poll-interval",
        "0.2",
        last_line=True,
    )
    task_payload = ctx.run_cli_json("task", "get", team_name, task["id"])
    inbox_log = ctx.run_cli_json("inbox", "log", team_name)
    coding_list = ctx.run_cli_json("coding", "list", "--team", team_name)
    assert coding_list["jobs"], "expected at least one coding job"
    job = next(job for job in coding_list["jobs"] if job["taskId"] == task["id"])
    job_id = job["jobId"]
    coding_status = ctx.run_cli_json("coding", "status", job_id, "--team", team_name)
    coding_result = ctx.run_cli_json("coding", "result", job_id, "--team", team_name)
    coding_events = ctx.run_cli_json("coding", "events", job_id, "--team", team_name)
    coding_artifacts = ctx.run_cli_json("coding", "artifacts", job_id, "--team", team_name)
    coding_stdout = ctx.run_cli_json("coding", "artifact", job_id, "--team", team_name, "--name", "stdoutLog")
    faults = ctx.run_cli_json("faults", "list", "--team", team_name)
    timeline = ctx.run_cli_json("audit", "timeline", "--team", team_name)
    board_show = ctx.run_cli("board", "show", team_name)
    board_json = ctx.run_cli_json("board", "show", team_name)
    callbacks = ctx.http_get_json(
        ctx.start_board_server(team_name, host="127.0.0.1").base_url,
        f"/api/teams/{team_name}/callbacks",
    )

    return {
        "task": task,
        "taskPayload": task_payload,
        "spawn": spawn_payload,
        "wait": wait_payload,
        "inboxLog": inbox_log,
        "codingList": coding_list,
        "jobId": job_id,
        "codingStatus": coding_status,
        "codingResult": coding_result,
        "codingEvents": coding_events,
        "codingArtifacts": coding_artifacts,
        "codingStdout": coding_stdout,
        "faults": faults,
        "timeline": timeline,
        "boardShow": board_show,
        "boardJson": board_json,
        "callbacks": callbacks,
        "workerPid": worker_pid,
    }


def test_smoke_clawteam_full_chain_no_workspace(tmp_path):
    with isolated_smoke_context(tmp_path, "standalone-full-chain") as ctx:
        run_dir = ctx.root / "run"
        run_dir.mkdir(parents=True, exist_ok=True)

        result = _run_full_chain(
            ctx,
            team_name="smoke-full-chain",
            worker_name="worker1",
            task_subject="standalone full-chain smoke",
            repo=run_dir,
            workspace_mode="never",
        )

        assert result["spawn"]["status"] == "spawned"
        assert result["spawn"]["workspace"]["status"] == "disabled"
        assert result["wait"]["status"] == "completed"
        assert result["taskPayload"]["status"] == "completed"
        assert len(result["inboxLog"]["messages"]) >= 2
        assert any("status=in_progress" in message["content"] for message in result["inboxLog"]["messages"])
        assert any("status=completed" in message["content"] for message in result["inboxLog"]["messages"])
        assert result["codingStatus"]["state"] == "completed"
        assert result["codingResult"]["status"] == "completed"
        assert result["codingResult"]["summary"] == "smoke ok"
        assert [event["eventType"] for event in result["codingEvents"]["events"]] == [
            "created",
            "started",
            "completed",
        ]
        assert result["callbacks"]["callbacks"], "expected persisted callback reports"
        callback = result["callbacks"]["callbacks"][0]
        assert callback["jobId"] == result["jobId"]
        assert callback["taskId"] == result["task"]["id"]
        assert callback["decision"] == "report_progress"
        assert callback["summary"] == "smoke ok"
        artifact_names = {artifact["name"] for artifact in result["codingArtifacts"]["artifacts"]}
        assert {"stdoutLog", "stderrLog", "invocation", "jobRecord", "resultJson"}.issubset(artifact_names)
        assert "CLAWTEAM_RESULT_JSON_START" in (result["codingStdout"]["content"] or "")
        assert result["faults"]["faults"] == []
        timeline_event_types = {event["eventType"] for event in result["timeline"]["events"]}
        assert "coding_job_created" in timeline_event_types
        assert "coding_job_completed" in timeline_event_types
        assert "callback_reported" in timeline_event_types
        assert "Task Board" in result["boardShow"].stdout
        assert result["boardJson"]["runtimeConsole"]["jobs"][0]["jobId"] == result["jobId"]
        assert result["boardJson"]["runtimeConsole"]["callbacks"][0]["jobId"] == result["jobId"]
        assert result["boardJson"]["runtimeConsole"]["callbacks"][0]["decision"] == "report_progress"


def test_smoke_clawteam_board_api(tmp_path):
    with isolated_smoke_context(tmp_path, "standalone-board-api") as ctx:
        run_dir = ctx.root / "run"
        run_dir.mkdir(parents=True, exist_ok=True)

        result = _run_full_chain(
            ctx,
            team_name="smoke-board-api",
            worker_name="worker1",
            task_subject="board api smoke",
            repo=run_dir,
            workspace_mode="never",
        )

        board = ctx.start_board_server("smoke-board-api", host="127.0.0.1")
        overview = ctx.http_get_json(board.base_url, "/api/overview")
        team_payload = ctx.http_get_json(board.base_url, "/api/team/smoke-board-api")
        tasks_payload = ctx.http_get_json(board.base_url, "/api/teams/smoke-board-api/tasks")
        jobs_payload = ctx.http_get_json(board.base_url, "/api/teams/smoke-board-api/coding/jobs")
        callbacks_payload = ctx.http_get_json(board.base_url, "/api/teams/smoke-board-api/callbacks")
        faults_payload = ctx.http_get_json(board.base_url, "/api/teams/smoke-board-api/faults")
        timeline_payload = ctx.http_get_json(board.base_url, "/api/teams/smoke-board-api/timeline")

        assert any(team["name"] == "smoke-board-api" for team in overview)
        assert team_payload["runtimeConsole"]["jobs"][0]["jobId"] == result["jobId"]
        assert team_payload["runtimeConsole"]["callbacks"][0]["jobId"] == result["jobId"]
        assert tasks_payload["tasks"][0]["status"] == "completed"
        assert jobs_payload["jobs"][0]["jobId"] == result["jobId"]
        assert callbacks_payload["callbacks"][0]["jobId"] == result["jobId"]
        assert callbacks_payload["callbacks"][0]["taskId"] == result["task"]["id"]
        assert callbacks_payload["callbacks"][0]["decision"] == "report_progress"
        assert callbacks_payload["callbacks"][0]["summary"] == "smoke ok"
        assert faults_payload["faults"] == []
        assert any(event["eventType"] == "callback_reported" for event in timeline_payload["events"])


def test_smoke_clawteam_workspace_healthy_repo(tmp_path):
    with isolated_smoke_context(tmp_path, "standalone-workspace-healthy") as ctx:
        repo = ctx.root / "repo"
        branch = init_git_repo(repo, commit=True)

        result = _run_full_chain(
            ctx,
            team_name="smoke-workspace-healthy",
            worker_name="worker1",
            task_subject="workspace healthy smoke",
            repo=repo,
            workspace_mode="always",
        )

        workspace_payload = result["spawn"]["workspace"]
        assert workspace_payload["status"] == "created"
        assert workspace_payload["resolvedBaseRef"] == branch
        worktree_path = Path(workspace_payload["worktreePath"])
        assert worktree_path.exists()
        workspace_list = ctx.run_cli_json("workspace", "list", "smoke-workspace-healthy", "--repo", str(repo))
        assert workspace_list["workspaces"][0]["agent_name"] == "worker1"
        assert result["codingStatus"]["effectiveCwd"].startswith(str(worktree_path))

        ctx.run_cli("workspace", "cleanup", "smoke-workspace-healthy", "--repo", str(repo), cwd=repo)
        assert not worktree_path.exists()
        workspace_list_after = ctx.run_cli_json("workspace", "list", "smoke-workspace-healthy", "--repo", str(repo))
        assert workspace_list_after["workspaces"] == []
        ctx.run_cli("team", "cleanup", "smoke-workspace-healthy", "--force")
        discover = ctx.run_cli_json("team", "discover")
        assert all(team["name"] != "smoke-workspace-healthy" for team in discover)
        data_dir = ctx.data_dir
        assert not (data_dir / "teams" / "smoke-workspace-healthy").exists()
        assert not (data_dir / "tasks" / "smoke-workspace-healthy").exists()
        assert not (data_dir / "coding" / "jobs" / "smoke-workspace-healthy").exists()
        assert not (data_dir / "coding" / "results" / "smoke-workspace-healthy").exists()
        assert not (data_dir / "runtime-console" / "callbacks" / "smoke-workspace-healthy").exists()


def test_smoke_clawteam_workspace_bad_repo(tmp_path):
    with isolated_smoke_context(tmp_path, "standalone-workspace-bad") as ctx:
        repo = ctx.root / "bad-repo"
        unborn_branch = init_git_repo(repo, commit=False)

        auto_result = _run_full_chain(
            ctx,
            team_name="smoke-workspace-auto-bad",
            worker_name="worker1",
            task_subject="workspace auto bad smoke",
            repo=repo,
            workspace_mode="auto",
        )
        assert auto_result["spawn"]["workspace"]["status"] == "skipped"
        assert auto_result["spawn"]["workspace"]["headValid"] is False
        assert auto_result["spawn"]["workspace"]["currentBranch"] == unborn_branch
        assert auto_result["wait"]["status"] == "completed"
        assert auto_result["taskPayload"]["status"] == "completed"

        ctx.run_cli("team", "spawn-team", "smoke-workspace-always-bad", "-d", "strict bad repo", "-n", "leader")
        ctx.register_team("smoke-workspace-always-bad", repo)
        strict_payload = ctx.run_cli_json(
            "spawn",
            "subprocess",
            ctx.python_bin,
            str(FAKE_WORKER),
            "--team",
            "smoke-workspace-always-bad",
            "--agent-name",
            "worker2",
            "--workspace",
            "--repo",
            str(repo),
            "--task",
            "strict bad repo smoke",
            check=False,
        )
        # check=False means the JSON payload is still returned on failure.
        assert strict_payload["error"] == "workspace_preflight_failed"
        assert strict_payload["workspace"]["workspaceMode"] == "always"
        assert strict_payload["workspace"]["headValid"] is False
        assert strict_payload["workspace"]["currentBranch"] == unborn_branch
