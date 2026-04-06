---
name: clawteam-openclaw
description: "Multi-agent swarm coordination for the ClawTeam-OpenClaw fork. Use when the user wants to create or reuse a persistent team, spawn multiple workers, assign tasks with dependencies, send inbox messages, inspect coding runtime state, inspect provider sessions/callbacks/faults/timeline, monitor progress through board surfaces, or launch a team template. This fork defaults to OpenClaw for swarm spawning and supports Claude Code and Codex as coding-runtime providers. Trigger phrases: clawteam, openclaw team, team, swarm, multi-agent, spawn agents, callback, coding runtime, runtime console, provider session, board, timeline, fault."
version: 0.3.1+openclaw.1
---

# ClawTeam OpenClaw Skill

## Overview

ClawTeam-OpenClaw is a fork of ClawTeam for durable multi-agent coordination.

In this fork:

- OpenClaw is the default swarm/backend path for spawned team members
- spawned workers normally run in tmux with git worktree isolation
- the default tmux worker launch path uses `openclaw tui --deliver`
- Claude Code and Codex are supported as coding-runtime providers through `clawteam coding exec`
- provider configuration remains external to ClawTeam
- runtime state is persisted under `~/.clawteam/`

Use this skill when the task benefits from persistent team topology, parallel workers, task dependencies, role separation, or coding callback inspection.

## Support Model

Keep these support boundaries clear:

- **Default swarm backend**: OpenClaw
- **Coding-runtime providers**: `claude`, `codex`
- **Other CLI agents**: may still participate in team/task/inbox flows, but the durable coding callback runtime is currently implemented for `claude` and `codex`
- **Provider config**: external; ClawTeam-OpenClaw does not manage provider accounts, models, profiles, or provider-side config files

## Authority Model

Authoritative sources of truth are:

- persisted runtime files under `~/.clawteam/`
- `clawteam` CLI output
- Rich board output

`clawteam board serve` is a convenience Web UI only.

Do not treat Web board state, tmux panes, or raw provider exit alone as the source of truth when durable state says otherwise.

## Current Runtime Model

Keep these objects distinct:

- task
- coding job
- provider session
- callback report
- runtime fault
- timeline event

Do not collapse process exit, callback completion, task completion, session closure, and board visibility into one fact.

## Install Expectations

For this fork, do not tell operators to install upstream PyPI `clawteam` if they need the OpenClaw-default behavior.

Use the fork:

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
pip install -e .
```

Recommended prerequisites:

- Python 3.10+
- `tmux`
- `openclaw` for default swarm spawning
- optionally `claude` and/or `codex` for coding-runtime execution

## Spawn Defaults

In this fork, ordinary worker spawning should default to the OpenClaw path.

Use:

```bash
clawteam spawn --team <team> --agent-name <name> --task "<task>"
```

Effective defaults are:

- backend: `tmux`
- command/backend path: `openclaw`
- OpenClaw execution mode: `openclaw tui --deliver`
- isolation: git worktree when the repo passes workspace preflight
- cwd: worker workspace/worktree

Workspace rules:

- `workspace=auto`: create a worktree only when the repo is git-healthy and worktree-capable; otherwise continue without workspace and surface diagnostics
- `workspace=always`: fail loudly on the same preflight failures
- `--no-workspace`: skip worktree creation and run directly in the requested repo/cwd

Operational advice:

- OpenClaw scratch workspaces are not automatically trustworthy project repos
- use `clawteam workspace doctor --repo <path>` before relying on worktree isolation
- use `--repo <real-project-repo>` and often `--no-workspace` when the current cwd is just an OpenClaw scratch area
- use `--workspace-base-ref <ref>` when you need a base ref other than the current branch

Avoid overriding ordinary worker spawning to `claude` unless there is a deliberate reason to bypass the OpenClaw swarm path.

## Coding Runtime Defaults

Use the coding runtime when a worker needs a coding provider to execute real implementation work and then return a structured callback to the same worker.

Supported provider commands:

```bash
clawteam coding exec claude "Implement callback handling" --team <team> --task-id <task>
clawteam coding exec codex "Implement callback handling" --team <team> --task-id <task>
```

Important behavior:

- execution runs in the worker workspace/worktree by default
- the worker remains the owner of the task context
- the provider result is normalized and returned to the same worker
- the worker decides whether to continue, report progress, escalate, complete, or block
- success depends on structured result normalization, not process exit alone
- raw stdout/stderr are preserved even when normalization fails
- Claude Code startup includes `--dangerously-skip-permissions` by default in the runtime/spawn path where configured

## Core Commands

### Team Lifecycle

```bash
clawteam team spawn-team <team> -d "<goal>" -n leader
clawteam team discover
clawteam team status <team>
clawteam team cleanup <team> --force
```

### Task Lifecycle

```bash
clawteam task create <team> "Design API" -o architect
clawteam task create <team> "Build backend" -o backend --blocked-by <task-id>
clawteam task list <team>
clawteam task get <team> <task-id>
clawteam task update <team> <task-id> --status in_progress
clawteam task update <team> <task-id> --status completed
clawteam task stats <team>
clawteam task wait <team>
```

### Worker Messaging

```bash
clawteam inbox send <team> <agent> "<message>" --from <sender>
clawteam inbox broadcast <team> "<message>" --from <sender>
clawteam inbox peek <team> -a <agent>
clawteam inbox receive <team>
clawteam inbox log <team>
```

### Monitoring and Board Surfaces

```bash
clawteam board show <team>
clawteam --json board show <team>
clawteam board live <team>
clawteam board attach <team>
clawteam board serve --host 0.0.0.0 --port 8080
```

### Coding Runtime and Runtime Console

```bash
clawteam coding list --team <team>
clawteam coding status <job-id> --team <team>
clawteam coding result <job-id> --team <team>
clawteam coding events <job-id> --team <team>
clawteam coding artifacts <job-id> --team <team>
clawteam coding artifact <job-id> --name stdoutLog --team <team>
clawteam coding wait <job-id> --team <team>
clawteam coding cancel <job-id> --team <team> --reason "operator requested stop"
clawteam coding retry <job-id> --team <team>
clawteam coding replay <job-id> --team <team>

clawteam coding session list --team <team>
clawteam coding session show <session-id> --team <team>
clawteam coding session jobs <session-id> --team <team>
clawteam coding session events <session-id> --team <team>

clawteam faults list --team <team>
clawteam faults show <fault-id> --team <team>
clawteam audit timeline --team <team>
```

## Recommended Workflow

1. Create or reuse a persistent team.
2. Create tasks with explicit owners and `--blocked-by` dependencies.
3. Spawn only the workers that are actually needed.
4. Start monitoring immediately after spawning.
5. When a worker needs real implementation work, use `clawteam coding exec claude ...` or `codex ...` in the correct worker/task context.
6. Inspect durable state through CLI or Rich board before making decisions.
7. Summarize task-facing progress upward instead of forwarding raw provider transcripts.
8. Merge worktrees and clean up only after the authoritative state says the work is done.

## Leader Rules

When acting as leader:

- parallelize only independent tasks
- use `--blocked-by` for sequencing
- keep monitoring without waiting for the user to ask
- inspect inbox, tasks, coding jobs, faults, and timeline before assuming a worker is stuck or done
- verify completion through durable task state and callback-aware runtime state
- escalate only when a worker cannot proceed or a decision truly belongs above the worker

## Worker Rules

When acting as worker:

- operate inside the assigned workspace/worktree
- keep task state updated honestly
- use inbox messages for concise team-facing communication
- use coding runtime deliberately; do not fire multiple overlapping coding jobs for the same task
- after callback return, decide whether to continue locally or escalate to leader
- do not equate provider exit with success if normalization or durable records say otherwise

## Current V1 Limits

The current shipped runtime has these limits:

- `1 worker = 1 active coding job`
- `1 task = 1 active provider execution`
- live cancel is durable-state only
- detached async callback delivery is not implemented
- stronger live control semantics are not implemented
- reconciliation/recovery beyond current durable truth is not implemented
- provider session metadata may be `ephemeral` or `unavailable`
- `board serve` remains a convenience UI and still depends on external CDN assets

## Data Location

Durable state lives under `~/.clawteam/`.

Important paths:

- `~/.clawteam/teams/<team>/`
- `~/.clawteam/tasks/<team>/`
- `~/.clawteam/coding/jobs/<team>/`
- `~/.clawteam/coding/results/<team>/`
- `~/.clawteam/coding/events/<team>/`
- `~/.clawteam/coding/artifacts/<team>/`
- `~/.clawteam/runtime-console/provider-sessions/<team>/`
- `~/.clawteam/runtime-console/callbacks/<team>/`
- `~/.clawteam/runtime-console/faults/<team>/`
- `~/.clawteam/runtime-console/timeline/<team>/`

## Operator Guidance

Prefer these references when you need exact operator semantics:

- `README.md`
- `docs/runtime-console-operator-guide.md`
- `docs/upgrade-and-rollback-guide.md`

Version identity for this fork:

```bash
clawteam --version
# clawteam v0.3.1+openclaw.1
# fork: ClawTeam-OpenClaw
```

If those sources disagree with the Web board, trust the durable model and CLI.
