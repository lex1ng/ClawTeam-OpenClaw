# Callback Operator Board Tasking

**Date:** 2026-04-07  
**Audience:** Coding agent implementing the next board/runtime-console upgrade  
**Primary Spec:** [Callback Operator Board Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-07-callback-operator-board-design.md)

## 1. Goal

Upgrade the current Web board and aligned CLI/API surfaces so callback, fault provenance, team aggregation state, and bounded runtime evidence are professionally visible.

This is not a cosmetic UI pass.

It is an observability and operator-surface upgrade for:

- worker -> team leader callback
- team leader -> main leader callback
- hook/watchdog/self-report fault provenance
- bounded tmux/session evidence and history

## 2. Non-Negotiable Constraints

- durable state remains authority
- board must not invent business truth from tmux/session text
- tmux/session output may be shown only as evidence
- board and CLI JSON must stay semantically aligned
- do not silently hide read faults or evidence read failures
- do not ship an evidence panel before callback/fault semantics are explicit
- do not dump unbounded transcript content into the board

## 3. Required Reading

Read these before implementation:

1. [Runtime Console Design for CLI + Web Board](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-05-runtime-console-cli-board-design.md)
2. [Multi-Level Task Callback System Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-multi-level-task-callback-system-design.md)
3. [OpenClaw Native Failure Reporting Integration Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-openclaw-native-failure-reporting-integration-design.md)
4. [Callback Operator Board Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-07-callback-operator-board-design.md)

## 4. Delivery Phases

Implement in this order.

### Phase 1: Callback Chain Surface

Required deliverables:

- callback-chain aggregate model
- worker callback status presentation
- team callback status presentation
- explicit `waiting_aggregate` and `reported_upward` semantics
- board/API visibility for callback chain

Acceptance requirements:

- operators can tell whether worker callback happened
- operators can tell whether team callback happened
- worker callback and team callback are not conflated

### Phase 2: Worker Health / Progress / Fault Semantics

Required deliverables:

- worker row health model
- worker row progress-state model
- worker row callback-state model
- fault badges with provenance

Acceptance requirements:

- `alive=true` is no longer misleading
- worker can be `alive + faulted`
- worker can be `alive + stalled`
- worker can be `completed + waiting team aggregation`

### Phase 3: Fault Provenance and Escalation Views

Required deliverables:

- provenance display for hook/watchdog/self-report/read-fault
- escalation visibility in board and JSON
- leader-visible and main-leader-visible summaries where data exists

Acceptance requirements:

- operator can answer "how did we learn about this fault?"
- operator can answer "was it reported upward?"

### Phase 4: Detail Drawer Upgrade

Required deliverables:

- callback detail panel
- fault detail panel
- related timeline panel
- contract artifact linkage panel
- job/session/fault/callback cross-links

Acceptance requirements:

- selecting a worker, callback, or fault gives a useful explanation path
- callback/fault drill-down does not require tmux

### Phase 5: Evidence and History Layer

Required deliverables:

- evidence record model or equivalent durable payload
- bounded evidence API
- snapshot evidence capture points
- evidence history UI
- optional live tail view if bounded and clearly labeled

Acceptance requirements:

- operators can inspect last useful evidence without opening tmux
- operators can inspect historical evidence after the tmux pane is gone
- evidence is visibly marked non-authoritative

## 5. Suggested File Targets

Likely implementation areas:

- `clawteam/board/collector.py`
- `clawteam/board/server.py`
- `clawteam/board/static/index.html`
- `clawteam/board/static/runtime_console_helpers.js`
- `clawteam/runtime_console/`
- `clawteam/team/`
- `clawteam/cli/commands.py`
- `tests/test_board_collector.py`
- `tests/test_board_server.py`
- `tests/test_board_web_ui.py`

Add new test modules as needed.

## 6. API Work

At minimum, implement or prepare:

- callback chain aggregate in team payload or dedicated route
- worker-level callback/fault/evidence routes
- evidence list/detail routes
- escalation visibility fields

Minimum acceptable route set:

- `GET /api/teams/:team/callback-chain`
- `GET /api/teams/:team/evidence`
- `GET /api/teams/:team/workers/:worker/evidence`

Equivalent route naming is acceptable if consistent and documented.

## 7. UI Work

At minimum, update the Web board to show:

- callback flow panel
- explicit worker health/progress/callback badges
- fault provenance badges
- team aggregation status
- callback/fault detail drawer content
- evidence/history panel or tab

The UI must prioritize density and clarity over novelty.

## 8. Test Requirements

You must add or update tests for:

### Callback Visualization

- callback chain payload contains worker and team levels
- missing team callback is visible distinctly from missing worker callback
- callback pending and waiting-aggregate states render correctly

### Health Semantics

- `alive=true` with hook fault renders faulted/degraded state
- watchdog stalled state renders distinctly from crash/error
- CLI JSON and board JSON agree on these labels

### Fault Provenance

- hook fault provenance is preserved
- watchdog fault provenance is preserved
- self-report provenance is preserved

### Evidence / History

- evidence payload is bounded
- evidence preview marks truncation
- evidence read failure surfaces as explicit error state
- historical evidence remains available without live tmux

### UI Rendering

- callback panel renders expected states
- detail drawer can render callback and fault details
- evidence tab can render empty/present/error states honestly

## 9. Validation Commands

At minimum, run and report:

```bash
python -m pytest tests/test_board_collector.py tests/test_board_server.py tests/test_board_web_ui.py -q
python -m pytest tests/test_smoke_clawteam_full_chain.py tests/test_smoke_openclaw_integration.py -q
```

If you add evidence-specific tests, run them explicitly in the report.

## 10. Reporting Format

When done, report back in exactly this structure:

1. files changed
2. phases completed
3. new board/API/CLI surfaces
4. callback/fault semantics now visible
5. evidence/history semantics now visible
6. commands run
7. pass/fail summary
8. residual risks

## 11. Explicit Non-Goals

Do not expand this task into:

- board-first authority logic
- provider config orchestration
- unbounded session transcript storage
- browser E2E automation
- full reconciliation engine

## 12. Final Standard

This task is done only when the operator can answer, from board plus CLI JSON alone:

- what each worker is doing
- whether it truly called back
- whether team leader truly called back upward
- what fault happened
- how the fault was discovered
- what the last useful evidence is

without relying on raw tmux inspection as the primary path.
