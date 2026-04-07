# Multi-Level Task Callback Implementation Tasking

**Date:** 2026-04-06  
**Audience:** Coding agent implementing the next orchestration layer for ClawTeam-OpenClaw  
**Prerequisite Document:** [Multi-Level Task Callback System Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-multi-level-task-callback-system-design.md)

## 1. Goal

Implement the next major system layer that turns ClawTeam-OpenClaw from a useful multi-agent tool into a closed-loop task orchestration runtime.

This work must introduce:

- OpenClaw lifecycle hook bridge as the first failure-signal layer
- formal task contract artifacts
- worker -> team leader callback closure
- team leader -> main leader callback closure
- durable worker/leader failure reporting
- board/CLI visibility for these new states

This plan is explicitly ordered around one rule:

- lifecycle hooks are P0, not a later enhancement
- lifecycle hooks are the primary immediate-failure signal
- watchdogs are secondary and only cover alive-but-silent cases
- self-report remains the normal-path signal, not the only failure signal

## 2. Non-Negotiable Constraints

- do not collapse task truth and runtime fault truth
- do not make tmux the authority model
- do not treat worker inbox summary as equivalent to team callback
- do not auto-complete coding-runtime-required tasks without coding job/callback evidence
- do not depend on the failing actor still being able to execute `clawteam` in order to surface failure
- do not make watchdogs the primary failure detector when OpenClaw lifecycle signals already exist
- do not redesign provider config orchestration
- do not redesign detached async callback in this phase
- do not weaken current standalone or OpenClaw integration smoke coverage

## 3. Required Reading Order

Read these before coding:

1. [Worker / Leader Failure Auto-Report Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-worker-leader-failure-auto-report-design.md)
2. [OpenClaw Native Failure Reporting Integration Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-openclaw-native-failure-reporting-integration-design.md)
3. [Runtime Reconciliation and Recovery Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-runtime-reconciliation-recovery-design.md)
4. [Multi-Level Task Callback System Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-multi-level-task-callback-system-design.md)

## 4. Phased Workstreams

Implement in this order.

### Phase 0: OpenClaw Lifecycle Hook Bridge

Implement the runtime signal bridge before any higher-level callback closure work.

Required deliverables:

- OpenClaw lifecycle/hook observer bridge
- normalized runtime signal model for worker and team-leader sessions
- mapping from OpenClaw native events to ClawTeam durable fault/timeline events
- synthesized upward failure notification path that does not depend on the failed actor self-reporting
- tests proving failure becomes visible even when worker bootstrap/self-report path is broken

Primary signal sources:

- `error`
- `end`
- `session_end`
- `agent_end`
- tool-call failure hooks when available

Requirements:

- this is the authoritative immediate-failure path for OpenClaw-backed sessions
- signal ingestion must be durable and idempotent
- session `alive=true` must no longer imply healthy when lifecycle bridge already observed error/end/crash semantics
- bridge output must reach ClawTeam durable state:
  - runtime faults
  - timeline
  - leader-visible notification
  - board/CLI JSON
- if OpenClaw-native cross-session send is available, it may be used as an acceleration path
- durable ClawTeam records remain the source of truth

### Phase 1: Contract Artifacts

Introduce the durable task contract layer.

Required deliverables:

- mission artifact support
- team spec artifact support
- worker spec artifact support
- worker result artifact support
- machine-readable status artifact support

Minimum viable file set:

- `MISSION.md`
- `TEAM_SPEC.md`
- `WORKER_SPEC.md`
- `RESULT.md`
- `STATUS.json`

Requirements:

- define canonical storage locations
- ensure paths are stable and discoverable
- expose references in CLI/JSON where useful
- add tests for creation and persistence

### Phase 2: Worker Callback Closure

Implement a formal worker -> team leader callback path.

Required deliverables:

- structured worker callback record model
- durable worker callback persistence
- CLI or runtime helper for worker callback emission
- team leader visible callback discovery path
- tests proving worker callback is not just inbox text

Requirements:

- worker completion must reference `RESULT.md` and `STATUS.json`
- worker callback must be durable even if optional human-readable inbox messaging also exists
- board/CLI must render worker callback state

### Phase 3: Team Callback Closure

Implement a formal team leader -> main leader callback path.

Required deliverables:

- structured team callback record model
- durable team callback persistence
- leader-side aggregation logic
- main leader visible callback discovery path
- tests proving team completion is distinct from worker completion

Requirements:

- main leader must not rely on scanning all worker inbox messages
- team callback must summarize worker states, faults, and output locations
- board/CLI must show when a team is waiting on leader aggregation vs already reported upward

### Phase 4: Watchdog and Reconciliation Observers

Implement secondary failure auto-reporting for silent/no-progress states.

Required deliverables:

- worker no-progress observer
- leader failure observer
- stalled-progress synthesis on top of lifecycle truth
- durable fault records for these conditions

Requirements:

- this phase is secondary to Phase 0 rather than a replacement for it
- failure reporting must not depend on the failing actor still being able to execute `clawteam`
- tmux/pane/log data may be used as evidence only
- new fault types must be visible in board/CLI
- startup-failed workers must stop looking healthy simply because `alive=true`

Watchdog priority rules:

- use lifecycle hook bridge for immediate crash/error/end detection
- use watchdog only for "alive but silent" and "expected progress missing"
- do not emit duplicate faults when lifecycle bridge already produced the canonical fault

### Phase 5: Execution Policy Enforcement

Introduce stronger execution policy where required.

Required deliverables:

- support `analysis_only` tasks
- support `coding_runtime_required` tasks
- validation logic that rejects silent completion when coding runtime is required but no coding job/callback exists
- tests for both modes

Requirements:

- this policy should come from worker/team spec, not free-form prompt inference
- worker completion semantics must differ based on declared execution policy

## 5. Suggested File Targets

Likely implementation areas:

- `clawteam/team/`
- `clawteam/runtime_console/`
- `clawteam/board/`
- `clawteam/cli/commands.py`
- `clawteam/spawn/`
- `tests/`
- `docs/runtime-console-operator-guide.md`
- `README.md`

Create additional models/services as needed, but keep authority boundaries explicit.

## 6. Required Tests

At minimum, add or update tests covering:

### Lifecycle Bridge Tests

- worker bootstrap failure becomes durable fault without worker self-report
- worker session end/error becomes leader-visible fault
- leader session end/error becomes main-leader-visible fault
- hook-driven failure does not require tmux inspection to discover
- duplicate hook delivery is idempotently folded into one canonical durable fault/timeline path

### Contract Tests

- mission/team/worker spec creation
- result/status persistence
- canonical path layout

### Callback Tests

- worker callback durable persistence
- team callback durable persistence
- team completion distinct from worker completion
- main leader waiting on team callback behavior

### Failure Tests

- worker alive but no progress produces watchdog fault
- leader silent stall produces watchdog fault and escalation visibility
- failure can be seen from board/CLI without tmux

### Execution Policy Tests

- `analysis_only` task may complete without coding job
- `coding_runtime_required` task cannot complete without coding job and callback

## 7. Required Validation Before Marking Done

Run and report at minimum:

```bash
python -m pytest tests/test_smoke_clawteam_full_chain.py -q
python -m pytest tests/test_smoke_openclaw_integration.py -q
python -m pytest tests/test_callback_decision_matrix.py -q
python -m pytest tests/test_coding_integration.py tests/test_spawn_backends.py tests/test_spawn_cli.py tests/test_manager.py -q
```

Add and run any new focused tests introduced by this work.

If new board/CLI surfaces are added, include those tests explicitly in the report.

## 8. Reporting Format

When done, report back in this exact structure:

1. files changed
2. workstreams completed
3. exact callback/failure semantics now covered
4. commands run
5. pass/fail summary
6. residual risks

## 9. Expected Residual Risks After This Phase

Even after this implementation, some risks may remain by scope:

- detached async callback still not implemented
- provider config orchestration still external
- reconciliation/repair still future work
- real provider/network behavior still partially outside test coverage

These are acceptable.

What is **not** acceptable after this phase:

- OpenClaw worker or leader error/end/session_end still not bridged into ClawTeam durable fault truth
- worker completion still not durably distinguishable from team completion
- main leader still not receiving a formal team callback
- worker/leader failures still requiring tmux as the primary discovery path
- coding-runtime-required tasks still silently completing without runtime evidence
