# OpenClaw Lifecycle Hook Bridge Tasking

**Date:** 2026-04-07  
**Audience:** Coding agent implementing the next critical reliability layer  
**Priority:** P0  
**Prerequisites:**

1. [OpenClaw Native Failure Reporting Integration Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-openclaw-native-failure-reporting-integration-design.md)
2. [Worker / Leader Failure Auto-Report Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-worker-leader-failure-auto-report-design.md)
3. [Multi-Level Task Callback System Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-multi-level-task-callback-system-design.md)
4. [Multi-Level Task Callback Implementation Tasking](/root/github.com/ClawTeam-OpenClaw/docs/agent/plans/2026-04-06-multi-level-task-callback-implementation-tasking.md)

## 1. Why This Is P0

Current failure reporting is still structurally incomplete.

If a worker or team leader crashes, exits early, or hits an OpenClaw/runtime error, the failing actor may never successfully execute:

- `clawteam inbox send`
- `clawteam coding callback-report`
- any normal-path self-report step

That means:

- inbox self-report is not enough
- worker callback closure is not enough
- watchdog alone is not enough

OpenClaw lifecycle hooks are the earliest trustworthy signal for:

- startup failure
- immediate runtime error
- abnormal session end
- tool-call bootstrap failure

Therefore this bridge must land before the rest of the closed-loop orchestration work is considered production-grade.

## 2. Implementation Objective

Convert OpenClaw-native lifecycle/hook events into ClawTeam-native durable fault and escalation records.

Target outcome:

- worker fails
- hook bridge records canonical fault
- leader can observe it without opening tmux
- main leader can observe team-level escalation without scraping worker windows

## 3. Signal Priority Model

Implement these signal priorities explicitly.

### Primary Signal: Lifecycle Hooks

Use OpenClaw-native lifecycle/hook events as the first-class immediate-failure detector.

Examples:

- `error`
- `end`
- `session_end`
- `agent_end`
- tool-call failure / command invocation failure hooks

### Secondary Signal: Watchdog

Watchdog exists for:

- session still alive
- no claim/progress
- no callback
- no expected status transition

Watchdog is not allowed to replace lifecycle hook truth when hook truth already exists.

### Tertiary Signal: Self-Report

Worker or leader self-report remains useful, but only as a normal-path signal.

It must not be the only failure path.

## 4. Required Deliverables

### A. Hook Bridge Layer

Add a dedicated bridge layer that can ingest OpenClaw-native lifecycle/hook events and normalize them into a ClawTeam runtime signal model.

Minimum requirements:

- normalize source event type
- attach team / role / session identity
- attach timestamp
- attach available error payload
- keep original raw payload reference where safe

### B. Fault Classification

Map runtime signals to canonical ClawTeam fault types.

Minimum required classifications:

- `worker_bootstrap_failed`
- `worker_bootstrap_command_failed`
- `worker_runtime_crashed`
- `worker_session_ended_early`
- `leader_bootstrap_failed`
- `leader_runtime_crashed`
- `leader_session_ended_early`

### C. Durable Persistence

Persist hook-derived faults and events into existing authority surfaces.

Required outputs:

- runtime-console fault record
- timeline event
- board/API visibility
- CLI/JSON visibility

### D. Upward Notification

When feasible, synthesize upward notification.

Required semantics:

- worker fault becomes team-leader-visible
- team-leader fault becomes main-leader-visible
- this visibility must not require reading raw tmux panes

This can be implemented as:

- system inbox event
- structured callback-like fault envelope
- both

Durable state remains the source of truth.

### E. Health Semantics Correction

Fix operator semantics so that:

- `alive=true` no longer implies healthy
- a session that already emitted `error` or fatal `end` is shown as faulted/degraded
- board/CLI expose the difference between:
  - process alive
  - progressing
  - faulted
  - ended unexpectedly

## 5. Suggested File Targets

Likely implementation areas:

- `clawteam/openclaw/`
- `clawteam/runtime_console/`
- `clawteam/team/`
- `clawteam/board/`
- `clawteam/cli/commands.py`
- `tests/`

Create new modules if needed. Do not overload unrelated prompt-building code with runtime observation responsibilities.

## 6. Test Requirements

You must add automated coverage for the following.

### Hook Failure Tests

- worker bootstrap command failure generates durable fault
- worker session error generates durable fault
- worker session abnormal end generates durable fault
- leader session error generates durable fault
- duplicate hook delivery is idempotent

### Visibility Tests

- board JSON shows hook-derived fault
- board/API marks actor unhealthy/faulted
- CLI surface shows hook-derived fault without tmux inspection
- main-leader-visible summary contains propagated team-leader failure

### Negative / Boundary Tests

- normal clean completion does not emit fatal hook fault
- watchdog does not double-report when hook fault already exists
- missing optional raw hook fields do not crash persistence

## 7. Validation Commands

At minimum, run and report:

```bash
python -m pytest tests/test_smoke_openclaw_integration.py -q
python -m pytest tests/test_spawn_backends.py tests/test_spawn_cli.py tests/test_manager.py -q
```

Add any new hook-bridge-specific test modules and run them explicitly in the final report.

## 8. Agent Delivery Format

When reporting completion, use this exact structure:

1. files changed
2. hook sources integrated
3. canonical fault types now emitted
4. visibility surfaces updated
5. commands run
6. pass/fail summary
7. residual risks

## 9. Explicit Non-Goals For This Task

Do not broaden this task into:

- detached async callback redesign
- provider config orchestration
- full reconciliation engine
- browser E2E board work
- prompt-spec rewrite

Those come later.

The job here is narrower and more important:

- make runtime failure observable immediately
- make that observation durable
- make it visible upward
