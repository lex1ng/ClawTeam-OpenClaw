from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


REPO_ROOT = Path(__file__).resolve().parents[2]


def _ensure_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_clawteam_wrapper(path: Path) -> None:
    script = (
        "#!/bin/sh\n"
        f"exec {sys.executable!r} -m clawteam.cli.commands \"$@\"\n"
    )
    path.write_text(script, encoding="utf-8")
    _ensure_executable(path)


def _write_exec_wrapper(path: Path, target: str) -> None:
    script = (
        "#!/bin/sh\n"
        f"exec {target!r} \"$@\"\n"
    )
    path.write_text(script, encoding="utf-8")
    _ensure_executable(path)


def _copy_fake_claude(path: Path) -> None:
    source = REPO_ROOT / "tests" / "smoke" / "bin" / "claude"
    shutil.copy2(source, path)
    _ensure_executable(path)


def _copy_fake_openclaw(path: Path) -> None:
    source = REPO_ROOT / "tests" / "smoke" / "bin" / "openclaw"
    shutil.copy2(source, path)
    _ensure_executable(path)


def _copy_fake_worker(path: Path) -> None:
    source = REPO_ROOT / "tests" / "smoke" / "fake_worker.py"
    shutil.copy2(source, path)
    _ensure_executable(path)


def _candidate_port(offset: int = 0) -> int:
    base = 20000 + ((os.getpid() + int(time.time() * 1000)) % 20000)
    return base + offset


def _kill_pid(pid: int) -> None:
    if pid <= 0:
        return
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.kill(pid, 9)
    except ProcessLookupError:
        return


@dataclass
class BoardServerHandle:
    process: subprocess.Popen[str]
    host: str
    port: int

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass
class SmokeContext:
    root: Path
    home: Path
    data_dir: Path
    bin_dir: Path
    env: dict[str, str]
    clawteam_bin: Path
    python_bin: str
    team_registrations: list[tuple[str, Path | None]] = field(default_factory=list)
    board_servers: list[BoardServerHandle] = field(default_factory=list)
    worker_pids: set[int] = field(default_factory=set)

    def register_team(self, team_name: str, repo: Path | None = None) -> None:
        self.team_registrations.append((team_name, repo))

    def register_worker_pid(self, pid: int) -> None:
        if pid > 0:
            self.worker_pids.add(pid)

    def run_cli(
        self,
        *args: str,
        json_output: bool = False,
        cwd: Path | None = None,
        timeout: float = 30.0,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = [str(self.clawteam_bin)]
        if json_output:
            command.append("--json")
        command.extend(args)
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else str(REPO_ROOT),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and completed.returncode != 0:
            raise AssertionError(
                "CLI command failed:\n"
                f"cmd={' '.join(command)}\n"
                f"code={completed.returncode}\n"
                f"stdout=\n{completed.stdout}\n"
                f"stderr=\n{completed.stderr}"
            )
        return completed

    def run_cli_json(
        self,
        *args: str,
        cwd: Path | None = None,
        timeout: float = 30.0,
        last_line: bool = False,
        check: bool = True,
    ) -> Any:
        completed = self.run_cli(
            *args,
            json_output=True,
            cwd=cwd,
            timeout=timeout,
            check=check,
        )
        payload_text = completed.stdout.strip().splitlines()[-1] if last_line else completed.stdout
        return json.loads(payload_text)

    def read_spawn_registry(self, team_name: str) -> dict[str, dict[str, Any]]:
        path = self.data_dir / "teams" / team_name / "spawn_registry.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def register_worker_from_registry(self, team_name: str, agent_name: str) -> int:
        registry = self.read_spawn_registry(team_name)
        pid = int(registry.get(agent_name, {}).get("pid") or 0)
        self.register_worker_pid(pid)
        return pid

    def openclaw_invocations(self) -> list[dict[str, Any]]:
        path = self.data_dir / "smoke-logs" / "openclaw-invocations.jsonl"
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def worker_log(self, agent_name: str) -> str:
        path = self.data_dir / "smoke-logs" / f"worker-{agent_name}.log"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def tmux_capture(self, team_name: str, agent_name: str) -> str:
        target = f"clawteam-{team_name}:{agent_name}"
        result = subprocess.run(
            ["tmux", "capture-pane", "-pt", target],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return ""
        return result.stdout

    def start_board_server(
        self,
        team_name: str,
        *,
        host: str = "127.0.0.1",
        interval: float = 0.2,
    ) -> BoardServerHandle:
        last_failure = ""
        for attempt in range(10):
            port = _candidate_port(attempt)
            process = subprocess.Popen(
                [
                    str(self.clawteam_bin),
                    "board",
                    "serve",
                    team_name,
                    "--host",
                    host,
                    "--port",
                    str(port),
                    "--interval",
                    str(interval),
                ],
                cwd=str(REPO_ROOT),
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            handle = BoardServerHandle(process=process, host=host, port=port)
            self.board_servers.append(handle)
            deadline = time.monotonic() + 10
            last_error = ""
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=1)
                    combined = f"{stdout}\n{stderr}"
                    if "Address already in use" in combined or "Errno 98" in combined:
                        last_failure = combined
                        self.board_servers.remove(handle)
                        break
                    raise AssertionError(
                        "board serve exited before becoming ready:\n"
                        f"stdout=\n{stdout}\n"
                        f"stderr=\n{stderr}"
                    )
                try:
                    self.http_get_json(handle.base_url, "/api/overview", timeout=1.0)
                    return handle
                except Exception as exc:  # pragma: no cover - retried path
                    last_error = str(exc)
                    time.sleep(0.1)
            else:
                last_failure = last_error
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=5)
                self.board_servers.remove(handle)
        raise AssertionError(f"board serve did not become ready: {last_failure}")

    def http_get_json(self, base_url: str, path: str, *, timeout: float = 5.0) -> Any:
        with urllib.request.urlopen(f"{base_url}{path}", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def wait_until(
        self,
        predicate,
        *,
        timeout: float = 20.0,
        interval: float = 0.2,
        description: str = "condition",
    ) -> Any:
        deadline = time.monotonic() + timeout
        last_value = None
        while time.monotonic() < deadline:
            last_value = predicate()
            if last_value:
                return last_value
            time.sleep(interval)
        raise AssertionError(f"Timed out waiting for {description}")

    def cleanup(self) -> None:
        for handle in self.board_servers:
            process = handle.process
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)
        for pid in list(self.worker_pids):
            _kill_pid(pid)
        for team_name, repo in reversed(self.team_registrations):
            subprocess.run(
                ["tmux", "kill-session", "-t", f"clawteam-{team_name}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if repo is not None:
                self.run_cli(
                    "workspace",
                    "cleanup",
                    team_name,
                    "--repo",
                    str(repo),
                    check=False,
                    timeout=15.0,
                    cwd=repo,
                )
            self.run_cli(
                "team",
                "cleanup",
                team_name,
                "--force",
                check=False,
                timeout=15.0,
            )
        shutil.rmtree(self.root, ignore_errors=True)


@contextmanager
def isolated_smoke_context(
    tmp_path: Path,
    name: str,
    *,
    provider_binaries: dict[str, str | Path] | None = None,
) -> Iterator[SmokeContext]:
    root = tmp_path / name
    home = root / "home"
    data_dir = root / "data"
    bin_dir = root / "bin"
    for path in (home, data_dir, bin_dir):
        path.mkdir(parents=True, exist_ok=True)

    clawteam_bin = bin_dir / "clawteam"
    fake_claude_bin = bin_dir / "claude"
    fake_openclaw_bin = bin_dir / "openclaw"
    fake_worker_bin = bin_dir / "fake_worker.py"
    _write_clawteam_wrapper(clawteam_bin)
    provider_binaries = provider_binaries or {}
    claude_binary = provider_binaries.get("claude")
    if claude_binary:
        _write_exec_wrapper(fake_claude_bin, str(claude_binary))
    else:
        _copy_fake_claude(fake_claude_bin)
    openclaw_binary = provider_binaries.get("openclaw")
    if openclaw_binary:
        _write_exec_wrapper(fake_openclaw_bin, str(openclaw_binary))
    else:
        _copy_fake_openclaw(fake_openclaw_bin)
    codex_binary = provider_binaries.get("codex")
    if codex_binary:
        _write_exec_wrapper(bin_dir / "codex", str(codex_binary))
    _copy_fake_worker(fake_worker_bin)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "CLAWTEAM_DATA_DIR": str(data_dir),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "PYTHONPATH": (
                f"{REPO_ROOT}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"
                if os.environ.get("PYTHONPATH")
                else str(REPO_ROOT)
            ),
            "CLAWTEAM_BIN": str(clawteam_bin),
            "PYTHONUNBUFFERED": "1",
        }
    )

    ctx = SmokeContext(
        root=root,
        home=home,
        data_dir=data_dir,
        bin_dir=bin_dir,
        env=env,
        clawteam_bin=clawteam_bin,
        python_bin=sys.executable,
    )
    try:
        yield ctx
    finally:
        ctx.cleanup()


def init_git_repo(path: Path, *, commit: bool) -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "smoke@example.com"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Smoke Test"], cwd=path, check=True, capture_output=True, text=True)
    if commit:
        (path / "README.md").write_text("smoke\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, text=True)
    return subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
