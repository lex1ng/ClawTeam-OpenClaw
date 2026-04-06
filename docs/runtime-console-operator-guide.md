# Runtime Console and Coding Runtime Operator Guide

This guide documents the current shipped runtime-console and coding-runtime behavior in `ClawTeam-OpenClaw`.

It reflects the current `9.1`-level baseline on the `feature/coding-agent-callback-runtime` line.

Current fork identity:

```bash
clawteam --version
# clawteam v0.3.1+openclaw.1
# fork: ClawTeam-OpenClaw
```

## What This Subsystem Does

The coding callback runtime executes a coding provider inside a worker-owned workspace/worktree, persists durable job state and artifacts, returns a structured callback result to the same worker, and exposes operator inspection surfaces over that durable state.

In the current implementation:

- the worker owns the execution context
- the coding provider runs inside the worker workspace/worktree boundary by default
- the callback result returns to the same worker
- the worker decides task-level follow-up such as `continue`, `report_progress`, `escalate`, `complete`, or `blocked`
- the leader only consumes summarized task-facing output
- operator surfaces read durable state rather than guessing from live process behavior

## Authority Model

Authoritative sources of truth are:

- persisted runtime files under `~/.clawteam/`
- CLI output
- Rich board output

The Web board started by `clawteam board serve` is a convenience UI only.

It reads the same durable data model, but it is not authoritative by itself.

## Current Object Model

The runtime keeps these objects distinct:

- task
- coding job
- provider session
- callback report
- runtime fault
- timeline event

This separation is intentional.

Do not treat process exit, callback completion, task completion, session closure, or runtime-console visibility as the same fact.

## Provider and Support Model

### OpenClaw

OpenClaw is the default swarm/backend path in this fork.

It has the most complete setup guidance in the project:

- default `spawn` experience
- skill installation guidance
- approvals/allowlist guidance

### Claude Code and Codex

Claude Code and Codex are the current coding-runtime provider executables for:

- `clawteam coding exec claude ...`
- `clawteam coding exec codex ...`

ClawTeam-OpenClaw does **not** manage:

- provider accounts
- provider profiles
- model selection orchestration
- provider-side config files

It only:

- selects the executable
- applies startup flags
- runs in the correct cwd
- captures stdout/stderr/exit/timeout
- normalizes the result
- returns the structured result to the worker

### Other CLI Agents

Other CLI agents can still participate in:

- team topology
- task tracking
- inbox/lifecycle flow
- board/overview surfaces

But the current coding callback runtime provider adapters are limited to `claude` and `codex`.

## Spawn and Workspace Truth

The default swarm-worker path in this fork is:

- backend: `tmux`
- worker executable: `openclaw`
- effective OpenClaw tmux mode: `openclaw tui --deliver`

The `--deliver` flag matters. Without it, an OpenClaw TUI can appear alive while never handing the injected prompt to a provider-backed run.

`clawteam spawn` guarantees:

- durable team/member/task visibility
- process or tmux-window launch
- identity injection
- initial prompt injection

`clawteam spawn` does not by itself prove:

- task completion
- coding job success
- provider callback success

Workspace modes:

- `auto`: preflight the repo, create a worktree only when the repo is git-healthy and worktree-capable, otherwise continue without workspace and emit diagnostics
- `always`: run the same preflight, but fail instead of falling back
- `never` / `--no-workspace`: skip worktree creation and run directly in the requested repo/cwd

Operational guidance:

- use `clawteam workspace doctor --repo <path>` before relying on a repo for worktree isolation
- use `--no-workspace` when OpenClaw dropped you into a scratch workspace that is not the real project checkout
- use `--workspace-base-ref <ref>` when the current branch is not the correct worktree base

## Durable Storage Layout

Coding runtime:

- `~/.clawteam/coding/jobs/<team>/`
- `~/.clawteam/coding/results/<team>/`
- `~/.clawteam/coding/events/<team>/`
- `~/.clawteam/coding/artifacts/<team>/`

Runtime Console:

- `~/.clawteam/runtime-console/provider-sessions/<team>/`
- `~/.clawteam/runtime-console/callbacks/<team>/`
- `~/.clawteam/runtime-console/faults/<team>/`
- `~/.clawteam/runtime-console/timeline/<team>/`

## Core Operator Commands

### Coding Job Execution and Inspection

```bash
clawteam coding exec claude "Implement callback handling" --team my-team --task-id task-123
clawteam coding list --team my-team
clawteam coding status <job-id> --team my-team
clawteam coding result <job-id> --team my-team
clawteam coding events <job-id> --team my-team
clawteam coding artifacts <job-id> --team my-team
clawteam coding artifact <job-id> --name stdoutLog --team my-team
clawteam coding wait <job-id> --team my-team
clawteam coding cancel <job-id> --team my-team --reason "operator requested stop"
clawteam coding retry <job-id> --team my-team
clawteam coding replay <job-id> --team my-team
```

What these surfaces mean:

- `coding status` shows the durable job record, including task/leader identity, attempt counters, cwd, startup policy, applied flags, extra args, callback status, and artifact paths
- `coding result` shows the normalized terminal result only
- `coding events` shows durable lifecycle events such as `created`, `started`, and terminal transitions
- `coding artifacts` and `coding artifact` inspect persisted artifact files
- `coding wait` waits on durable job state, not raw process exit
- `coding cancel` marks durable cancellation state; it does not provide a stronger live kill semantics in this V1

### Provider Session Inspection

```bash
clawteam coding session list --team my-team
clawteam coding session show <session-id> --team my-team
clawteam coding session jobs <session-id> --team my-team
clawteam coding session events <session-id> --team my-team
```

What to expect:

- provider session metadata may be explicitly shown as `ephemeral` or `unavailable`
- session timelines include provider-session-scoped events plus callback-linked events tied through `links.sessionId`
- provider session ids are never invented when unavailable

### Fault and Audit Surfaces

```bash
clawteam faults list --team my-team
clawteam faults show <fault-id> --team my-team
clawteam audit timeline --team my-team
```

What these surfaces mean:

- `faults list/show` expose explicit runtime faults such as linkage mismatches or runtime-console sync failures
- `audit timeline` shows the unified durable event stream across tasks, jobs, sessions, callbacks, and faults
- list-style surfaces may also expose `readFaults` when persisted records are corrupt but healthy records are still readable

## Board Surfaces

Use:

```bash
clawteam board show my-team
clawteam --json board show my-team
clawteam board live my-team
clawteam board serve --host 0.0.0.0 --port 8080
```

Current board semantics:

- `board show` and `--json board show` are durable-state inspection surfaces
- `board live` repeatedly re-renders the same durable model
- `board serve` exposes the convenience Web UI over the same durable model
- the Web board now surfaces task read faults, coding read faults, and runtime faults explicitly

## Current V1 Limits

- `1 worker = 1 active coding job`
- `1 task = 1 active provider execution`
- coding job state is separate from worker decision
- default cwd remains inside the worker workspace/worktree boundary unless explicit escape is allowed
- success requires structured result normalization
- raw stdout/stderr are preserved even when normalization fails
- live cancellation is durable-state only
- detached async callback delivery is not implemented
- stronger live control semantics are not implemented
- reconciliation/recovery beyond current durable truth is not implemented
- `board serve` still relies on external CDN assets

## Typical Operator Workflow

1. Start or observe a job with `clawteam coding exec ...` or `clawteam coding list --team ...`.
2. Use `clawteam coding status <job-id> --team ...` to inspect the durable job record.
3. Use `clawteam coding result`, `coding events`, and `coding artifact --name stdoutLog` to inspect terminal result, lifecycle, and output.
4. Use `clawteam coding session show/events` to inspect provider-session state and callback causality.
5. Use `clawteam faults list` and `clawteam audit timeline` if the runtime looks degraded or inconsistent.
6. Use `clawteam board show` or `clawteam --json board show` for cross-object inspection; use `board serve` only as a convenience UI.

## Residual Risks

### By Design

- callback delivery is still the synchronous V1 model
- stronger control semantics are not yet implemented
- reconciliation/recovery is not yet implemented

### By Scope

- provider config orchestration remains out of scope
- cancel semantics remain the current durable-state model

### By Provider Limitation

- Claude Code / Codex provider configuration and account state remain external
- provider session metadata may be unavailable and is surfaced honestly as `ephemeral` / `unavailable`
