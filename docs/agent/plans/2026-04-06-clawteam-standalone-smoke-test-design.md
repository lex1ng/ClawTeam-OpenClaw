# 2026-04-06 ClawTeam Standalone Full-Chain Smoke Test Design

## Goal

Design a full-chain smoke test that validates `ClawTeam-OpenClaw` itself without relying on OpenClaw orchestration.

This smoke test must prove that the core `clawteam` system is operational before any OpenClaw-driven integration is trusted.

The smoke test must also be self-cleaning:

- no persistent pollution of the real operator environment
- no residual team/task/runtime files under the real home directory
- no residual worker processes
- no residual tmux sessions
- no residual worktrees
- no residual board server processes

## Why This Smoke Layer Is Required

Recent first-install failures showed that OpenClaw-driven real usage exposed problems before baseline clawteam behavior had been validated end to end.

That is the wrong order.

The correct order is:

1. validate `clawteam` itself in isolation
2. validate `clawteam` workspace behavior
3. validate `clawteam` board/operator surfaces
4. only then validate OpenClaw-driven worker integration

This document defines the first three layers as a standalone smoke suite.

## Non-Goals

This standalone smoke suite does **not** attempt to validate:

- OpenClaw default worker behavior
- OpenClaw TUI delivery semantics
- Discord routing, channels, or thread binding
- ACP session integration
- real Claude/Codex provider accounts

Those belong in later OpenClaw integration smoke tests.

## Core Design Principles

1. Do not require OpenClaw.
2. Do not require real Claude/Codex binaries.
3. Do not require manual interaction.
4. Do not depend on the operator's real `HOME` or `~/.clawteam`.
5. Make every artifact disposable.
6. Fail fast and clean up even on partial failure.
7. Use real `clawteam` CLI commands, not only direct Python module calls.

## Test Architecture

The standalone smoke suite should be implemented as automated `pytest` integration tests.

Recommended new files:

- `tests/test_smoke_clawteam_full_chain.py`
- `tests/smoke/fake_worker.py`
- `tests/smoke/bin/claude`

Optional:

- `tests/smoke/helpers.py`

## Environment Isolation Model

Every smoke test run must create a temp root, for example under `tmp_path`.

Within that temp root, create:

- `home/`
- `data/`
- `bin/`
- `repo/` when a healthy git repo is needed

The test must set environment variables for every subprocess:

- `HOME=<tmp>/home`
- `CLAWTEAM_DATA_DIR=<tmp>/data`
- `PATH=<tmp>/bin:<existing PATH>`

This is mandatory because:

- clawteam config uses `HOME/.clawteam/config.json`
- data files can be redirected with `CLAWTEAM_DATA_DIR`
- fake provider binaries must shadow any real provider binaries via `PATH`

## Cleanup Contract

Every smoke test must clean up all created state.

The cleanup sequence must run in `finally` blocks even when assertions fail.

Required cleanup actions:

1. stop board server process if started
2. terminate spawned worker processes if still alive
3. run `clawteam team cleanup <team> --force` when applicable
4. remove any temporary workspace repo/worktree roots
5. remove the entire temp root directory

If a tmux-based subtest is ever added later, cleanup must also kill the test tmux session explicitly.

## Smoke Layers

### Layer A: Core Full Chain Smoke Without Workspace

This is the required baseline smoke.

It must validate the following chain:

- leader creates team
- leader creates task
- leader spawns worker with `subprocess` backend and `--no-workspace`
- worker claims task
- worker invokes `clawteam coding exec claude ...`
- fake Claude returns structured result
- coding runtime persists job/result/events/artifacts
- worker marks task completed
- worker sends inbox summary to leader
- leader inspects board/runtime surfaces successfully

This proves the baseline clawteam orchestration substrate is operational.

### Layer B: Board/API Smoke

This validates the operator surfaces without requiring a browser.

It must start:

```bash
clawteam board serve --host 127.0.0.1 --port <ephemeral>
```

Then verify API endpoints such as:

- `/api/overview`
- `/api/team/<team>`
- `/api/teams/<team>/tasks`
- `/api/teams/<team>/coding/jobs`
- `/api/teams/<team>/callbacks`
- `/api/teams/<team>/faults`
- `/api/teams/<team>/timeline`

This proves the board service is wired to the durable model.

### Layer C: Healthy Workspace Smoke

This validates workspace isolation when a real healthy repo is provided.

It must:

- create a temporary healthy git repo
- create an initial commit
- spawn a worker with `--workspace --repo <repo>`
- run the same worker/coding callback chain
- verify workspace records exist and cleanup succeeds

### Layer D: Bad Repo Workspace Smoke

This validates workspace failure/degradation behavior.

It must:

- create a git repo with no valid commit/HEAD baseline
- exercise `workspace=auto`
- exercise `workspace=always`

Expected outcome after remediation:

- `auto` should not fail with an opaque raw git error
- `always` may fail, but must fail with explicit diagnostics

## Fake Provider Design

The smoke suite must not rely on a real Claude binary.

Instead, create a fake `claude` executable at:

- `tests/smoke/bin/claude`

During test setup, copy or symlink that file into `<tmp>/bin/claude` and prepend `<tmp>/bin` to `PATH`.

The fake provider must satisfy the Claude harness contract used by `clawteam coding exec claude ...`.

It should:

- accept the prompt passed via `-p`
- print a structured result block using the expected markers
- exit `0`

Recommended output format:

```text
CLAWTEAM_RESULT_JSON_START
{"summary":"smoke ok","responseText":"stub response","nextSuggestion":"","signals":{"needsReview":false}}
CLAWTEAM_RESULT_JSON_END
```

This allows the coding runtime to exercise:

- provider invocation
- normalization
- durable result persistence
- event emission
- artifact persistence
- callback recording

without needing a real provider account.

## Fake Worker Design

The smoke suite should use a deterministic fake worker script, for example:

- `tests/smoke/fake_worker.py`

This script should behave like a minimal autonomous worker.

Required behavior:

1. read these env vars:
   - `CLAWTEAM_TEAM_NAME`
   - `CLAWTEAM_AGENT_NAME`
   - `CLAWTEAM_AGENT_ID`
2. list tasks for itself:
   - `clawteam --json task list <team> --owner <agent>`
3. pick the owned task id
4. mark it `in_progress`
5. notify leader via inbox that work started
6. run `clawteam --json coding exec claude ... --team <team> --task-id <task-id>`
7. wait for job completion via `coding wait`
8. fetch `coding result`
9. mark task `completed`
10. send completion summary via inbox

This worker must use only real `clawteam` CLI calls.

The point is to validate the actual operator-facing behavior, not internal helper functions.

## Detailed Smoke Flow

### Smoke A: Core Full Chain Without Workspace

Test setup:

1. create temp root
2. create isolated `HOME`, `CLAWTEAM_DATA_DIR`, and `PATH`
3. install fake `claude` into temp `bin`
4. ensure the test invokes the intended `clawteam` binary

Execution steps:

1. `clawteam team spawn-team <team> -d "smoke" -n leader`
2. `clawteam task create <team> "smoke task" -o worker1`
3. `clawteam spawn subprocess python tests/smoke/fake_worker.py --team <team> --agent-name worker1 --task "Execute smoke task" --no-workspace`
4. `clawteam task wait <team> --timeout <bounded>`
5. inspect runtime and board surfaces

Assertions:

1. team exists
2. task reaches `completed`
3. inbox log contains start and completion messages
4. `coding list --team <team>` returns at least one job
5. `coding status <job>` is `completed`
6. `coding result <job>` has summary `smoke ok`
7. `coding events <job>` is non-empty
8. `coding artifacts <job>` includes `stdoutLog`
9. `faults list --team <team>` is empty
10. `audit timeline --team <team>` is non-empty
11. `board show <team>` succeeds
12. `--json board show <team>` exposes consistent task/runtime state

### Smoke B: Board/API Smoke

After Smoke A has produced data, start the board server.

Execution steps:

1. start `clawteam board serve --host 127.0.0.1 --port <ephemeral>` in background
2. request JSON endpoints

Assertions:

1. `/api/overview` returns 200
2. `/api/team/<team>` returns 200
3. `/api/teams/<team>/tasks` returns tasks and summary
4. `/api/teams/<team>/coding/jobs` returns the smoke job
5. `/api/teams/<team>/callbacks` returns callback data if present
6. `/api/teams/<team>/faults` returns empty or expected shape
7. `/api/teams/<team>/timeline` returns events

### Smoke C: Healthy Workspace Smoke

Setup:

1. create temp git repo
2. create a file
3. `git init`
4. `git add .`
5. `git commit -m "init"`

Execution steps:

1. create team and owned task
2. spawn fake worker with:

```bash
clawteam spawn subprocess python tests/smoke/fake_worker.py \
  --team <team> \
  --agent-name worker-ws \
  --task "workspace smoke" \
  --workspace \
  --repo <repo_path>
```

Assertions:

1. task completes
2. coding runtime completes
3. `clawteam workspace list <team>` shows a workspace entry
4. `clawteam team cleanup <team> --force` removes team state
5. `clawteam workspace cleanup <team>` leaves no residual worktree state

### Smoke D: Bad Repo Workspace Smoke

Setup:

1. create temp git repo
2. do **not** create an initial commit

Execution steps:

1. exercise `spawn` under `workspace=auto`
2. exercise `spawn` under `workspace=always`

Assertions after remediation:

1. `auto` does not fail with an opaque raw git stderr as the primary message
2. `auto` either degrades safely or provides a structured actionable warning
3. `always` fails explicitly with clear diagnostics

## Why Subprocess Backend Is Preferred For Baseline Smoke

Baseline smoke must minimize moving parts.

Use `subprocess` backend by default because:

- it avoids tmux lifecycle complexity
- it avoids interactive terminal timing issues
- it makes cleanup simpler and more deterministic
- it isolates the clawteam substrate from OpenClaw/TUI-specific behavior

Tmux-based smoke may be added later as a separate operator-experience layer.

## Board Server Notes

The smoke suite should validate the board service via HTTP JSON endpoints rather than browser automation.

This is sufficient for the standalone layer because the purpose is to verify:

- the service starts
- the service reads durable state correctly
- the expected JSON resources exist and are coherent

The standalone smoke suite does not need to validate front-end rendering details.

## Required Residual-State Guarantees

After each smoke test finishes, the following must be true:

1. no test teams remain under the temp data directory
2. no board server process remains alive
3. no spawned worker process remains alive
4. no workspace/worktree path remains under the temp root
5. no temp repo remains after the temp root is removed
6. the real operator `HOME` and real `~/.clawteam` remain untouched

## Required Pytest Marking

Mark this suite clearly, for example:

- `@pytest.mark.smoke`

This allows operators and CI to run:

```bash
pytest -q -m smoke tests/test_smoke_clawteam_full_chain.py
```

## Required Documentation Follow-Up

After implementing the smoke suite, update documentation to mention:

- the standalone smoke command
- that this smoke suite is the required baseline before OpenClaw integration smoke
- that all smoke runs are isolated and self-cleaning

Recommended docs to update:

- `README.md`
- `docs/upgrade-and-rollback-guide.md`
- `docs/runtime-console-operator-guide.md`

## Acceptance Criteria

This design is considered implemented only when:

1. the standalone smoke suite runs without OpenClaw installed
2. the suite uses only fake provider binaries and temp directories
3. the suite validates team/task/spawn/coding/callback/board behavior end to end
4. the suite leaves no residual state after completion
5. the suite is suitable for CI execution
6. OpenClaw integration testing is no longer the first place baseline clawteam defects are discovered
