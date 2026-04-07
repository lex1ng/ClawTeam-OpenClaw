# Runtime Test Matrix And Acceptance Plan

**Date:** 2026-04-07  
**Status:** Current-state test inventory and acceptance baseline  
**Scope:** Current repository coverage for runtime, callback, board, spawn, workspace, identity, and operator surfaces

## 1. Purpose

This document consolidates the current test surface into one matrix so the team can answer four questions quickly:

1. which existing tests already protect current behavior
2. which high-risk areas are still under-tested
3. which future changes should trigger regression runs
4. what the acceptance baseline should be before calling the runtime "ready"

This is a coverage map, not a claim that every listed suite was re-run in this task.

## 2. Source Basis

This matrix is based on:

- the current `tests/` tree
- smoke and tasking docs in `docs/agent/plans/`
- callback/runtime/board specs in `docs/design/specs/`
- latest review docs in `docs/agent/reviews/`

Key design and review anchors:

- `docs/design/specs/2026-04-04-coding-agent-callback-design.md`
- `docs/design/specs/2026-04-05-runtime-console-cli-board-design.md`
- `docs/design/specs/2026-04-06-multi-level-task-callback-system-design.md`
- `docs/design/specs/2026-04-06-runtime-reconciliation-recovery-design.md`
- `docs/design/specs/2026-04-07-callback-operator-board-design.md`
- `docs/design/specs/2026-04-07-external-skill-borrowing-integration-design.md`
- `docs/agent/reviews/2026-04-05-runtime-console-commit-review.md`
- `docs/agent/reviews/2026-04-05-runtime-hardening-rereview-9.1.md`
- `docs/agent/reviews/2026-04-05-coding-callback-runtime-rereview.md`
- `docs/agent/reviews/2026-04-07-callback-operator-board-rereview.md`

## 3. Truth And Readiness Legend

### Truth model

- `durable state authority`: the suite proves persisted task/job/session/callback/fault state or CLI/API views that read those durable records
- `evidence only`: the suite proves bounded artifact/evidence rendering or tmux/session excerpts, not business truth
- `UI rendering only`: the suite proves static or helper-level rendering behavior only

### Readiness

- `covered`: there is direct automated coverage for the current contract and it matches the current authority model
- `partially covered`: direct tests exist, but only for slices of the intended behavior or only at unit/operator level
- `planned`: design/tasking exists, but current tests do not yet prove the behavior end to end
- `missing`: no meaningful automated protection was found for the required scenario

## 4. Test-Level Inventory

| Test level | Primary suites | What this level currently proves |
| --- | --- | --- |
| unit | `tests/test_coding_models.py`, `tests/test_coding_store.py`, `tests/test_coding_service.py`, `tests/test_runtime_console_models.py`, `tests/test_runtime_console_store.py`, `tests/test_tasks.py`, `tests/test_manager.py`, `tests/test_models.py`, `tests/test_task_store_locking.py`, `tests/test_spawn_backends.py`, `tests/test_workspace_preflight.py`, `tests/test_workspace_subproject_overlay.py`, `tests/test_workspace_subproject_followups.py`, `tests/test_plan_storage.py`, `tests/test_mailbox.py` | durable model/schema rules, state machines, atomic locking, store corruption handling, workspace overlays, spawn command/env construction, lifecycle cleanup behavior |
| integration | `tests/test_runtime_console_cli.py`, `tests/test_board_collector.py`, `tests/test_board_server.py`, `tests/test_coding_integration.py`, `tests/test_callback_decision_matrix.py`, `tests/test_task_fault_tolerance.py`, `tests/test_spawn_cli.py`, `tests/test_spawn_subproject_workspace.py`, `tests/test_external_skill_borrowing_integration.py`, `tests/test_inbox_routing.py`, `tests/test_team_status_cli.py` | CLI/API/operator surfaces over durable state, callback persistence, callback decision semantics, degraded reads, identity/session metadata exposure, task/lifecycle routing |
| smoke | `tests/test_first_install_smoke.py`, `tests/test_smoke_clawteam_full_chain.py`, `tests/test_smoke_openclaw_integration.py` | disposable end-to-end-ish baseline for standalone clawteam and fake-OpenClaw runtime path, including spawn, task progression, coding runtime, callback persistence, board/API visibility |
| operator surface | `tests/test_board_web_ui.py`, `tests/test_board_ui_helpers.py`, plus the CLI/API suites above | web shell semantics, selection persistence helpers, artifact preview routing, callback/fault/evidence wording, CLI/API payload honesty |
| end-to-end planned | `docs/agent/plans/2026-04-07-e2e-test-design-tasking.md`, `docs/agent/plans/2026-04-07-openclaw-lifecycle-hook-bridge-tasking.md`, `docs/agent/plans/2026-04-07-session-bridge-channel-binding-design-tasking.md` | target multi-level runtime validation is designed, but not yet represented by a dedicated mandatory E2E suite |

## 5. Functional Matrix

| Functional area | Current suites | Levels now | Truth model | Readiness | What is actually protected now | Main caveats |
| --- | --- | --- | --- | --- | --- | --- |
| team/task persistence | `tests/test_manager.py`, `tests/test_tasks.py`, `tests/test_task_store_locking.py`, `tests/test_task_fault_tolerance.py`, `tests/test_plan_storage.py`, `tests/test_team_status_cli.py` | unit, integration | durable state authority | covered | team creation/discovery/cleanup, member add/remove, duplicate nickname rejection, task CRUD, dependency unblocking, locking, callback metadata persistence on tasks, degradation under corrupt task files, plan storage cleanup | no full multi-level team-result persistence suite yet |
| spawn/workspace | `tests/test_spawn_cli.py`, `tests/test_spawn_backends.py`, `tests/test_workspace_preflight.py`, `tests/test_spawn_subproject_workspace.py`, `tests/test_workspace_subproject_overlay.py`, `tests/test_workspace_subproject_followups.py`, `tests/test_first_install_smoke.py`, `tests/test_smoke_clawteam_full_chain.py`, `tests/test_smoke_openclaw_integration.py` | unit, integration, smoke | durable state authority | covered | spawn rollback on failure, backend PATH/env propagation, OpenClaw `--deliver` default in tmux, workspace preflight diagnostics, worktree cwd selection, subproject overlay filtering, first-install smoke, standalone smoke, fake-OpenClaw smoke | real provider session reuse and channel-bound routing are not covered here |
| coding runtime | `tests/test_coding_models.py`, `tests/test_coding_store.py`, `tests/test_coding_service.py`, `tests/test_coding_integration.py`, `tests/test_coding_harness_claude.py`, `tests/test_coding_harness_codex.py` | unit, integration | durable state authority | covered | cwd resolution, startup flags, lifecycle transitions, retry/replay lineage, atomic one-active-job enforcement, provider failure vs service failure separation, result/artifact persistence, CLI exec/status/result/wait/cancel/retry/replay | detached async callbacks remain intentionally out of scope; live-provider path is optional |
| callback runtime | `tests/test_callback_decision_matrix.py`, `tests/test_coding_integration.py`, `tests/test_tasks.py`, `tests/test_runtime_console_cli.py`, `tests/test_board_collector.py`, `tests/test_smoke_clawteam_full_chain.py`, `tests/test_smoke_openclaw_integration.py` | integration, smoke | durable state authority | covered | worker callback report persistence, decision matrix semantics (`continue`, `report_progress`, `escalate`, `complete`, `blocked`), callback-to-task metadata, session-link fallback/mismatch faulting, callback visibility in CLI/board/API, callback persistence through standalone and fake-OpenClaw smoke | worker callback is strong; team-level upward callback is only partially exercised |
| runtime-console | `tests/test_runtime_console_models.py`, `tests/test_runtime_console_store.py`, `tests/test_runtime_console_cli.py`, `tests/test_coding_service.py`, `tests/test_coding_integration.py` | unit, integration | durable state authority | covered | session/callback/fault/timeline records, explicit corruption surfacing, CLI degrade-with-read-fault behavior, callback-linked session events, runtime-console sync fault emission, session closure fallback when callback omits `sessionId` | reconciliation objects and repair operations are not implemented yet |
| runtime-console evidence | `tests/test_board_collector.py`, `tests/test_board_server.py`, `tests/test_board_web_ui.py` | integration, operator surface | evidence only | partially covered | bounded evidence payloads, artifact preview boundary enforcement, non-authoritative wording, evidence detail endpoints, artifact-preview UI hooks | current evidence is still mostly collector-derived or artifact-backed, not a full durable snapshot history |
| board/API/CLI operator surface | `tests/test_board_collector.py`, `tests/test_board_server.py`, `tests/test_board_web_ui.py`, `tests/test_board_ui_helpers.py`, `tests/test_runtime_console_cli.py`, `tests/test_team_status_cli.py` | integration, operator surface | durable state authority plus UI rendering only | partially covered | board JSON/API/CLI expose jobs, sessions, callbacks, faults, task read faults, callback chain, selection persistence helpers, artifact preview routing, explicit fault groups, bounded evidence framing | latest board review (`2026-04-07`) treats operator semantics as recently risky; keep this area as acceptance-critical until validated by green regression |
| hook/watchdog fault path | `tests/test_board_collector.py`, `tests/test_spawn_backends.py`, `tests/test_task_fault_tolerance.py` | unit, integration | durable state authority | partially covered | watchdog-derived stalled health rendering exists, lifecycle on-exit captures last tmux output with timeout handling, task cleanup degrades honestly under corruption | no dedicated automated hook-bridge suite yet; hook-derived fault persistence and self-report vs hook precedence are still planned in `docs/agent/plans/2026-04-07-openclaw-lifecycle-hook-bridge-tasking.md` |
| fixed reusable team identity | `tests/test_manager.py`, `tests/test_external_skill_borrowing_integration.py` | unit, integration | durable state authority | partially covered | product/team profile fields, member nickname/role metadata, duplicate nickname rejection, machine-facing member ids preserved while nicknames change, board/team-status exposure of profile metadata | no smoke proving reuse across run 1 -> run 2 with stable identity and session bindings |
| handoff/lifecycle contracts | `tests/test_external_skill_borrowing_integration.py`, `tests/test_tasks.py`, `tests/test_callback_decision_matrix.py` | integration | durable state authority | partially covered | handoff contract persistence, incomplete handoff detection, distinct callback lifecycle/review lifecycle/task lifecycle phases, callback state remains separate from lifecycle phase | no closed-loop team-leader review/aggregation smoke; no mandatory artifact validation in a full chain yet |
| session routing metadata | `tests/test_external_skill_borrowing_integration.py`, `tests/test_inbox_routing.py` | integration | durable state authority | partially covered | preferred session key and session-routing metadata are exposed; session bridge notice creation is machine-facing; prefixed leader inbox routing works | session bridge/channel binding delivery failure semantics remain design-only; no live session-routing smoke yet |
| end-to-end closed-loop runtime | design only in `docs/agent/plans/2026-04-07-e2e-test-design-tasking.md` and related specs | planned | durable state authority | planned | intent is defined for healthy chain, hook faults, watchdog faults, fixed-team reuse, and strong handoff | there is still no required dedicated E2E suite that proves main leader -> team leader -> worker -> coding runtime -> worker callback -> team callback -> upward visibility |

## 6. Hard Guarantees Vs Soft Confidence

### Hard guarantees already present

The strongest current guarantees are the durable-state and operator-read-path contracts proved by direct automated tests:

- coding job schema, lifecycle, retry/replay, and concurrency rules: `tests/test_coding_models.py`, `tests/test_coding_store.py`, `tests/test_coding_service.py`
- task persistence, dependency handling, lock safety, and explicit corruption behavior: `tests/test_tasks.py`, `tests/test_task_store_locking.py`, `tests/test_task_fault_tolerance.py`
- runtime-console object durability and degraded CLI/API reads: `tests/test_runtime_console_store.py`, `tests/test_runtime_console_cli.py`
- callback decision and persistence contracts: `tests/test_callback_decision_matrix.py`, `tests/test_coding_integration.py`, `tests/test_tasks.py`
- operator payload honesty for board/API: `tests/test_board_collector.py`, `tests/test_board_server.py`

### Soft confidence or harness-driven confidence

These suites are still valuable, but they do not by themselves prove the final production runtime:

- fake worker / fake provider smoke: `tests/test_smoke_clawteam_full_chain.py`, `tests/smoke/fake_worker.py`, `tests/smoke/bin/claude`
- fake OpenClaw smoke: `tests/test_smoke_openclaw_integration.py`, `tests/smoke/bin/openclaw`
- mocked harness subprocess paths: `tests/test_coding_integration.py`, `tests/test_coding_harness_claude.py`, `tests/test_coding_harness_codex.py`
- static/UI-only coverage: `tests/test_board_web_ui.py`, `tests/test_board_ui_helpers.py`
- optional real-provider smoke: `tests/test_live_provider_integration.py` is useful but explicitly opt-in and environment-gated

## 7. Highest-Risk Gaps

### 7.1 OpenClaw hook-bridge fault path is still not covered as a first-class runtime contract

The planning and spec stack treats lifecycle/hook signals as P0 for crash/bootstrap/error detection:

- `docs/agent/plans/2026-04-07-openclaw-lifecycle-hook-bridge-tasking.md`
- `docs/design/specs/2026-04-06-openclaw-native-failure-reporting-integration-design.md`
- `docs/design/specs/2026-04-07-callback-operator-board-design.md`

Current tests only cover:

- watchdog-style degraded rendering in `tests/test_board_collector.py`
- lifecycle cleanup/tmux capture behavior in `tests/test_spawn_backends.py`
- read-fault-tolerant exit cleanup in `tests/test_task_fault_tolerance.py`

What is still under-tested:

- hook-derived durable fault creation
- duplicate hook idempotency
- hook vs watchdog precedence
- leader/main-leader visibility from hook-driven failure without worker self-report

### 7.2 True multi-level team callback closure is not yet proven by smoke or mandatory E2E

Current callback coverage is strong at the worker/job level, but the multi-level design requires:

- worker callback to team leader
- team aggregation
- team callback to main leader
- upward failure visibility

Current automated proof is limited to:

- worker callback persistence and operator visibility
- board collector state-machine slices for `waiting_aggregate`, `reported`, and `reported_upward` in `tests/test_board_collector.py`

What is still missing:

- a smoke or E2E suite that makes a real team leader aggregate worker outcomes and report upward
- a failure-path suite for missing team callback, late team callback, or leader crash before upward reporting

### 7.3 Fixed-team reuse, session-routing reuse, and handoff enforcement are only covered in targeted integration tests

`tests/test_external_skill_borrowing_integration.py` proves the data model slice well, but not the operational slice.

What is still missing:

- run-1 to run-2 reuse smoke for stable team profile, nickname, and session metadata
- live routing failure handling
- full-chain validation that incomplete handoff blocks or degrades downstream review exactly as intended

### 7.4 Reconciliation and repair remain designed but not implemented

`docs/design/specs/2026-04-06-runtime-reconciliation-recovery-design.md` defines the recovery layer, but there are currently no dedicated tests for:

- `callback_missing_after_terminal_job`
- duplicate callback reconciliation
- late callback arrival handling
- operator repair actions and durable reconcile records

## 8. Future Changes That Must Trigger Regression Runs

| Change area | Required regression suites |
| --- | --- |
| coding job model, startup flags, cwd rules, retry/replay, provider adapters | `tests/test_coding_models.py`, `tests/test_coding_store.py`, `tests/test_coding_service.py`, `tests/test_coding_integration.py`, `tests/test_coding_harness_claude.py`, `tests/test_coding_harness_codex.py` |
| callback-report persistence, task metadata, callback decision semantics | `tests/test_callback_decision_matrix.py`, `tests/test_tasks.py`, `tests/test_coding_integration.py`, `tests/test_runtime_console_cli.py`, `tests/test_board_collector.py` |
| runtime-console store, CLI fault handling, session event filtering | `tests/test_runtime_console_models.py`, `tests/test_runtime_console_store.py`, `tests/test_runtime_console_cli.py`, `tests/test_coding_service.py` |
| board collector semantics, board API payloads, artifact preview/evidence behavior | `tests/test_board_collector.py`, `tests/test_board_server.py`, `tests/test_board_web_ui.py`, `tests/test_board_ui_helpers.py`, `tests/test_smoke_clawteam_full_chain.py`, `tests/test_smoke_openclaw_integration.py` |
| spawn backend, tmux/OpenClaw command building, workspace creation, repo preflight | `tests/test_spawn_backends.py`, `tests/test_spawn_cli.py`, `tests/test_workspace_preflight.py`, `tests/test_spawn_subproject_workspace.py`, `tests/test_workspace_subproject_overlay.py`, `tests/test_workspace_subproject_followups.py`, `tests/test_first_install_smoke.py`, `tests/test_smoke_openclaw_integration.py` |
| task corruption tolerance, lifecycle-on-exit cleanup, locking | `tests/test_tasks.py`, `tests/test_task_store_locking.py`, `tests/test_task_fault_tolerance.py`, `tests/test_spawn_backends.py` |
| team identity, nickname/session metadata, handoff lifecycle, session bridge notices | `tests/test_manager.py`, `tests/test_external_skill_borrowing_integration.py`, `tests/test_inbox_routing.py`, `tests/test_team_status_cli.py` |
| hook bridge or watchdog work | current minimum: `tests/test_board_collector.py`, `tests/test_spawn_backends.py`, `tests/test_task_fault_tolerance.py`, `tests/test_smoke_openclaw_integration.py`; after hook bridge lands, add dedicated hook-bridge suites as mandatory blockers |

## 9. Recommended Acceptance Baseline

### 9.1 Baseline for claiming the current V1 runtime is ready within declared scope

At minimum, all of the following should be green together:

1. durable core
   - `tests/test_coding_models.py`
   - `tests/test_coding_store.py`
   - `tests/test_coding_service.py`
   - `tests/test_tasks.py`
   - `tests/test_task_store_locking.py`
   - `tests/test_task_fault_tolerance.py`

2. callback and runtime-console contracts
   - `tests/test_callback_decision_matrix.py`
   - `tests/test_coding_integration.py`
   - `tests/test_runtime_console_models.py`
   - `tests/test_runtime_console_store.py`
   - `tests/test_runtime_console_cli.py`

3. operator surfaces
   - `tests/test_board_collector.py`
   - `tests/test_board_server.py`
   - `tests/test_board_web_ui.py`
   - `tests/test_board_ui_helpers.py`

4. spawn/workspace/runtime-path smoke
   - `tests/test_spawn_backends.py`
   - `tests/test_spawn_cli.py`
   - `tests/test_workspace_preflight.py`
   - `tests/test_first_install_smoke.py`
   - `tests/test_smoke_clawteam_full_chain.py`
   - `tests/test_smoke_openclaw_integration.py`

5. identity/lifecycle metadata slice
   - `tests/test_manager.py`
   - `tests/test_external_skill_borrowing_integration.py`
   - `tests/test_inbox_routing.py`

### 9.2 Additional baseline required before claiming the runtime is fully closed-loop ready

The current repository does **not** yet justify that stronger claim.

Before using words like `closed-loop ready`, `production-grade operator runtime`, or equivalent, the project should add and require:

1. dedicated hook-bridge tests
   - hook-derived durable fault creation
   - duplicate hook idempotency
   - hook vs watchdog precedence
   - leader/main-leader fault visibility without worker self-report

2. at least one real multi-level E2E suite
   - main leader -> team leader -> worker -> coding runtime -> worker callback -> team callback -> upward visibility

3. fixed-team reuse smoke
   - same team/profile/nickname/session-routing metadata across successive runs

4. stronger handoff/lifecycle enforcement smoke
   - incomplete handoff stays explicitly degraded across downstream operator surfaces

5. optional live-provider smoke when environment permits
   - `tests/test_live_provider_integration.py`
   - useful as a release gate in controlled environments, not as the only baseline gate

## 10. Bottom Line

### Which existing tests already protect current behavior?

The best-protected current behaviors are:

- coding job durability and state-machine correctness
- task persistence, locking, and corruption tolerance
- worker callback persistence and callback decision semantics
- runtime-console read paths and fault honesty
- standalone clawteam smoke and fake-OpenClaw runtime-path smoke
- board/API payload honesty for current durable records

### Which high-risk areas are still under-tested?

The highest-risk gaps are:

- hook-bridge failure ingestion and propagated fault visibility
- true team-level upward callback closure
- fixed-team/session-routing reuse across multiple runs
- end-to-end handoff/lifecycle enforcement
- reconciliation and repair flows for late/missing/duplicate callbacks

### Which future changes should trigger regression runs?

Any change touching coding, callback persistence, runtime-console, board semantics, spawn/workspace, identity/session metadata, or hook/watchdog logic should trigger the corresponding regression sets in section 8.

### What should the acceptance baseline be before claiming readiness?

For current V1 scope: require the baseline in section 9.1.  
For stronger closed-loop claims: do not claim readiness until section 9.2 is also satisfied.
