---
name: ClawTeam Multi-Agent Coordination
description: >
  Use this skill when the user wants to create or reuse a persistent team,
  spawn workers, assign tasks with dependencies, coordinate multi-agent work,
  inspect team state, inspect coding runtime jobs/sessions/faults/timeline,
  monitor progress through board surfaces, or operate the ClawTeam-OpenClaw fork.
  This fork defaults to OpenClaw for worker spawning and supports Claude Code and
  Codex as coding-runtime providers. Trigger phrases include clawteam, team,
  swarm, openclaw team, spawn worker, callback, coding runtime, runtime console,
  board, provider session, fault, and timeline.
version: 0.3.0
---

# ClawTeam Multi-Agent Coordination

## Overview

ClawTeam-OpenClaw is a durable multi-agent coordination CLI.

In this fork:

- OpenClaw is the default worker/swarm backend
- workers normally run in tmux with git worktree isolation
- Claude Code and Codex are supported through `clawteam coding exec`
- provider configuration remains external
- runtime truth is persisted under `~/.clawteam/`

Use this skill when a task benefits from role separation, persistent team reuse, explicit dependencies, or callback-aware coding execution.

## Fork-Specific Truths

Do not use stale upstream assumptions.

For this fork:

- do not describe ordinary spawn default as `claude`; the default path is OpenClaw
- do not describe PyPI upstream `clawteam` as the required install for this behavior; operators should install this fork
- do not claim the Web board is authoritative
- do not claim provider process exit alone proves task success

## Install Expectations

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
pip install -e .
```

Prerequisites:

- Python 3.10+
- `tmux`
- `openclaw` for default spawning
- optionally `claude` and/or `codex` for coding runtime

## Authority Model

Authoritative sources are:

- persisted files under `~/.clawteam/`
- `clawteam` CLI output
- Rich board output

`clawteam board serve` is a convenience Web UI over the same durable model.

## Core Object Model

Keep these objects separate:

- task
- coding job
- provider session
- callback report
- runtime fault
- timeline event

This distinction matters for correct operator reasoning.

## Quick Start

### Create a Team

```bash
clawteam team spawn-team my-team -d "Build the feature" -n leader
clawteam task create my-team "Design API" -o architect
clawteam task create my-team "Implement backend" -o backend --blocked-by <api-task-id>
clawteam task create my-team "Build frontend" -o frontend --blocked-by <api-task-id>
```

### Spawn Workers

```bash
# Recommended default path: OpenClaw + tmux + worktree isolation
clawteam spawn --team my-team --agent-name architect --task "Design the API"
clawteam spawn --team my-team --agent-name backend --task "Implement backend"
clawteam spawn --team my-team --agent-name frontend --task "Build frontend"
```

### Observe the Team

```bash
clawteam board show my-team
clawteam --json board show my-team
clawteam board attach my-team
clawteam board serve --port 8080
```

## Spawn Semantics

Default expectations in this fork:

- backend: `tmux`
- worker path: `openclaw`
- workspace: git worktree when available
- execution cwd: worker workspace/worktree

When Claude-based spawn/runtime paths are used, `--dangerously-skip-permissions` is enabled by default where configured so worker automation does not stall on approval prompts.

Avoid overriding normal team-worker spawn to `claude` unless you explicitly want to bypass the OpenClaw path.

## Coding Runtime

Use `clawteam coding exec` when a worker needs a coding provider to execute implementation work and then deliver a structured callback back to that same worker.

Supported provider adapters:

```bash
clawteam coding exec claude "Implement retry handling" --team my-team --task-id task-123
clawteam coding exec codex "Implement retry handling" --team my-team --task-id task-123
```

Runtime expectations:

- execution stays inside the worker workspace/worktree by default
- the worker owns the execution context
- the provider result returns to the same worker as structured callback data
- the worker decides whether to continue, report progress, escalate, complete, or block
- durable artifacts, events, sessions, callbacks, and faults remain inspectable after execution

Inspect with:

```bash
clawteam coding list --team my-team
clawteam coding status <job-id> --team my-team
clawteam coding result <job-id> --team my-team
clawteam coding events <job-id> --team my-team
clawteam coding artifacts <job-id> --team my-team
clawteam coding artifact <job-id> --name stdoutLog --team my-team
clawteam coding session list --team my-team
clawteam faults list --team my-team
clawteam audit timeline --team my-team
```

## Messaging and Control

Use inbox commands for team communication:

```bash
clawteam inbox send my-team worker1 "Start the auth implementation" --from leader
clawteam inbox broadcast my-team "Sync status in 10 minutes" --from leader
clawteam inbox peek my-team -a worker1
clawteam inbox receive my-team
```

Use task dependencies for sequencing rather than ad hoc memory.

## Recommended Operating Pattern

1. Create or reuse the team.
2. Define tasks with explicit owners and dependency edges.
3. Spawn only the required workers.
4. Monitor immediately.
5. Use coding runtime only inside the correct worker/task context.
6. Diagnose with CLI and durable state first.
7. Report summarized outcomes upward.
8. Merge worktrees and clean up only after durable truth confirms completion.

## Current V1 Limits

- `1 worker = 1 active coding job`
- `1 task = 1 active provider execution`
- live cancel remains durable-state only
- detached async callback delivery is not implemented
- stronger live control semantics are not implemented
- reconciliation/recovery is not implemented
- provider session metadata may be `ephemeral` or `unavailable`
- Web board remains convenience UI and still depends on external CDN assets

## Data Location

State lives under `~/.clawteam/`.

Key paths:

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

## References

Use these repo documents for authoritative operator semantics:

- `README.md`
- `docs/runtime-console-operator-guide.md`
- `docs/upgrade-and-rollback-guide.md`
