# Callback Operator Board Remediation Tasking

**Date:** 2026-04-07
**Audience:** Coding agent fixing the current callback operator board implementation
**Primary Review:** [Callback Operator Board Re-Review](/root/github.com/ClawTeam-OpenClaw/docs/agent/reviews/2026-04-07-callback-operator-board-rereview.md)

## 1. Goal

Fix the current callback operator board so the rendered runtime state is semantically correct and no longer misleads operators.

This is a remediation pass.

Do not broaden it into another architecture expansion.

## 2. Non-Negotiable Constraints

- do not collapse `ended` into `faulted`
- do not collapse `unknown` into `ended`
- do not collapse callback state into fault state
- do not collapse `in_progress` into `waiting_aggregate`
- do not claim true history if the implementation only provides bounded evidence views
- do not weaken current board/API/CLI alignment

## 3. Fix Set

### Fix A: Process State / Liveness Semantics

Files:

- `clawteam/board/collector.py`

Required outcome:

- distinguish at least:
  - `alive`
  - `ended`
  - `unknown`
- `is_agent_alive() is None` must not be treated as equivalent to dead
- `ended` must not automatically imply `faulted`
- worker/leader with no fatal fault should not appear faulted just because the process is not currently alive

Acceptance checks:

- normal completed worker can be `ended` without being `faulted`
- unknown liveness renders honestly as unknown/degraded/non-authoritative, not faulted

### Fix B: Callback State Must Survive Non-Fatal Faults

Files:

- `clawteam/board/collector.py`

Required outcome:

- worker callback state remains derived primarily from callback truth
- fault state remains separate
- non-fatal runtime warnings such as ephemeral session metadata do not erase successful callback closure

Minimum acceptable behavior:

- successful callback + warning fault => callback state stays `reported`
- escalation/block decisions still show correctly
- only callback-blocking or clearly fatal faults may force callback state to `faulted`

Acceptance checks:

- a worker with `report_progress` callback is not shown as `faulted` solely because a warning fault exists

### Fix C: Team Callback State Machine

Files:

- `clawteam/board/collector.py`
- `clawteam/board/static/index.html`

Required outcome:

- team-level chain state distinguishes:
  - `not_started`
  - `in_progress`
  - `waiting_aggregate`
  - `reported`
  - `reported_upward`
  - `blocked`
  - `faulted`

Minimum rules:

- worker still running/pending => team `in_progress`
- workers done / callbacks complete but no team callback yet => `waiting_aggregate`
- team callback persisted but not upward => `reported`
- team callback upward sent => `reported_upward`

Front-end rule:

- render team state from `team.callbackState`
- do not reduce everything to `reported_upward` vs `waiting_aggregate`

### Fix D: Evidence Honesty

Files:

- `clawteam/board/collector.py`
- `clawteam/runtime_console/service.py`
- `clawteam/runtime_console/store.py`
- `clawteam/board/static/index.html`

Required outcome:

Choose one of these and implement it consistently:

1. honest downgrade
   - rename UI/API language to `Evidence View` / `Bounded Evidence`
   - explicitly state that most records are collector-derived excerpts, not true historical snapshots

2. minimal real history
   - add at least one real durable evidence capture path
   - ensure the board actually reads persisted evidence for at least some meaningful capture points

Either path is acceptable.

What is not acceptable:

- calling it `Evidence History` while it is mostly ad-hoc read-time synthesis

## 4. Test Requirements

Add or update tests for the following.

### Process Semantics

- completed worker without fatal fault is not rendered as `faulted`
- missing spawn-registry/liveness info does not become `faulted`

### Callback vs Fault

- successful callback + runtime warning fault still renders `callbackState=reported`
- callback-blocking fault renders callback state appropriately

### Team State Machine

- worker pending/running => team `in_progress`
- workers reported but no team callback => `waiting_aggregate`
- team callback persisted but not upward => `reported`
- team callback upward => `reported_upward`

### Evidence Honesty

- UI/API wording matches actual implementation level
- if persistent evidence exists, detail route returns persisted evidence correctly
- if not, wording explicitly avoids overclaiming historical capture

## 5. Minimum Commands To Run

```bash
python -m pytest tests/test_board_collector.py tests/test_board_server.py tests/test_board_web_ui.py -q
python -m pytest tests/test_smoke_clawteam_full_chain.py tests/test_smoke_openclaw_integration.py tests/test_coding_integration.py -q
```

## 6. Reporting Format

When done, report exactly:

1. files changed
2. exact semantic fixes
3. tests added/updated
4. commands run
5. pass/fail summary
6. residual risks

## 7. Direct Instruction To Agent

```text
Read:
1. docs/agent/reviews/2026-04-07-callback-operator-board-rereview.md
2. docs/agent/plans/2026-04-07-callback-operator-board-remediation-tasking.md

This round is a semantic correction round.

Do not optimize layout first.
Do not add more surface area first.

Fix:
1. ended vs faulted vs unknown
2. callback state vs fault state
3. team callback state machine
4. evidence wording vs actual durability

Run:
- python -m pytest tests/test_board_collector.py tests/test_board_server.py tests/test_board_web_ui.py -q
- python -m pytest tests/test_smoke_clawteam_full_chain.py tests/test_smoke_openclaw_integration.py tests/test_coding_integration.py -q

Report back with:
1. files changed
2. exact semantic fixes
3. tests added/updated
4. commands run
5. pass/fail summary
6. residual risks
```
