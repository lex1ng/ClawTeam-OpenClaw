# Callback Operator Board Re-Review

**Date:** 2026-04-07
**Repository:** ClawTeam-OpenClaw
**Scope:** Re-review the new callback operator board implementation after the board/API/CLI/evidence surfaces were added on top of the existing runtime console

## Review Outcome

The direction is correct, but the implementation is not yet semantically correct enough to accept as complete.

The current board upgrade improved breadth:

- callback chain surfaces now exist
- fault provenance is exposed
- evidence surfaces exist
- worker health/progress/callback states are rendered
- board/API/CLI now expose more of the orchestration chain

However, several operator-facing state semantics are still wrong in ways that will mislead users.

This means the current round should be treated as:

- meaningful progress
- not yet final
- requires targeted remediation before it can be called trustworthy

## Findings

### 1. High: `ended` is being treated as `faulted`

Current logic collapses process/liveness uncertainty and normal end-of-life into fault semantics.

Relevant code:

- [clawteam/board/collector.py:658](/root/github.com/ClawTeam-OpenClaw/clawteam/board/collector.py#L658)
- [clawteam/board/collector.py:1058](/root/github.com/ClawTeam-OpenClaw/clawteam/board/collector.py#L1058)

Observed behavior:

- `is_agent_alive() == None` becomes effectively `ended`
- `processState == ended` becomes `health == faulted`

This causes at least two false conclusions:

- a worker that completed normally and exited can be shown as faulted
- a leader/worker with no spawn registry entry can be shown as faulted instead of unknown

This violates the required semantic split between:

- `alive`
- `ended`
- `unknown`
- `faulted`

### 2. High: any associated fault overrides real callback success

Current worker callback-state derivation treats any worker-associated fault as enough to mark callback state as `faulted`.

Relevant code:

- [clawteam/board/collector.py:626](/root/github.com/ClawTeam-OpenClaw/clawteam/board/collector.py#L626)

Observed behavior:

- a worker can have a successful callback record
- a non-fatal runtime warning such as `session_ephemeral` can still be associated to that worker
- the board will then show the callback chain row as `faulted`

This is materially wrong.

Callback state and fault state must remain distinct.

Warnings and degraded session metadata are not the same as callback closure failure.

### 3. High: team callback state machine is incorrect

Current team-level chain state does not distinguish execution-in-progress from aggregation-waiting.

Relevant code:

- [clawteam/board/collector.py:579](/root/github.com/ClawTeam-OpenClaw/clawteam/board/collector.py#L579)
- [clawteam/board/static/index.html:770](/root/github.com/ClawTeam-OpenClaw/clawteam/board/static/index.html#L770)

Observed behavior:

- if workers are still pending/in progress, the board can still show `waiting_aggregate`
- the Web board UI currently collapses non-upward team states into `waiting_aggregate`

This is not an acceptable operator model.

The operator must be able to distinguish:

- workers still executing
- workers done but team callback not yet formed
- team callback formed but not yet reported upward
- team callback reported upward

### 4. Medium: `Evidence History` currently overstates what is actually implemented

The implementation introduced evidence surfaces, but most records are still collector-synthesized excerpts from existing durable objects.

Relevant code:

- [clawteam/board/collector.py:721](/root/github.com/ClawTeam-OpenClaw/clawteam/board/collector.py#L721)
- [clawteam/runtime_console/service.py:305](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/service.py#L305)

Observed behavior:

- `record_evidence()` exists
- but the board mostly builds evidence dynamically from artifacts/callbacks/faults at read time
- the product wording presents this as `Evidence History`

That wording is too strong unless durable evidence capture points are actually implemented.

At minimum, the UI and API language must stay honest about whether this is:

- a bounded evidence view
- or a true historical snapshot system

## Validation Run During Review

The following suites were run from the repository root:

- `python -m pytest tests/test_board_collector.py tests/test_board_server.py tests/test_board_web_ui.py -q`
- `python -m pytest tests/test_smoke_clawteam_full_chain.py tests/test_smoke_openclaw_integration.py tests/test_coding_integration.py -q`

Result:

- `18 passed`
- `13 passed`

These passing tests are useful, but they do not invalidate the findings above because the problem is state semantics, not a crash or missing route.

## Reproduction Note

One concrete local reproduction showed:

- worker completed successfully
- worker persisted callback successfully
- a runtime warning fault existed on the provider session
- the board still rendered that worker callback row as `faulted`

That is exactly the kind of operator-facing semantic error this review is blocking on.

## Required Remediation

The next patch must fix:

1. process state semantics
2. callback-state vs fault-state decoupling
3. team callback state machine
4. evidence naming vs actual durability level

Use the remediation tasking document below as the implementation guide:

- [2026-04-07-callback-operator-board-remediation-tasking.md](/root/github.com/ClawTeam-OpenClaw/docs/agent/plans/2026-04-07-callback-operator-board-remediation-tasking.md)

## Final Judgement

This board round is not rejected on architecture.

It is blocked on correctness.

The direction is right.

The remaining work is semantic closure, not redesign.

## Direct Instruction To Agent

```text
Read:
1. docs/agent/reviews/2026-04-07-callback-operator-board-rereview.md
2. docs/agent/plans/2026-04-07-callback-operator-board-remediation-tasking.md

Do not spend this round on cosmetic UI polish.

Fix the operator-state semantics first:
- ended vs faulted vs unknown
- callback state vs fault state
- team callback state machine
- evidence naming vs true durability level

After fixing, rerun:
- python -m pytest tests/test_board_collector.py tests/test_board_server.py tests/test_board_web_ui.py -q
- python -m pytest tests/test_smoke_clawteam_full_chain.py tests/test_smoke_openclaw_integration.py tests/test_coding_integration.py -q

Report:
1. files changed
2. exact semantic fixes
3. tests added/updated
4. commands run
5. pass/fail summary
6. residual risks
```
