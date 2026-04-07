# Runtime Console Commit Review

**Date:** 2026-04-05
**Repository:** ClawTeam-OpenClaw
**Scope:** Review the three Runtime Console commits:

- `d41f8c8 feat: add runtime console models and cli surface`
- `2615863 feat: add runtime console board data api`
- `d6cf10c feat: ship runtime console web board`

## Executive Summary

The implementation direction is correct.

The runtime console now has a real foundation across:

- runtime console models
- durable runtime-console store
- CLI inspection surface
- board data APIs
- web board runtime console UI

The object split is materially improved and largely follows the approved design:

- task
- coding job
- provider session
- callback report
- fault

The implementation is now structurally credible.

However, the operator surface is not yet fully trustworthy.

The remaining issues are not cosmetic. They mostly affect:

- operator confidence under partial failure
- callback/session closure correctness
- CLI resilience under bad persisted data
- session timeline completeness
- live board usability

## Tests Run During Review

The following targeted review suite was run.

Local sandbox run:

- runtime console tests mostly passed, but `test_board_server` failed due to local port binding restriction in the sandbox, not due to an assertion failure

Escalated run to verify actual code behavior:

- `16 passed`

Reviewed test set included:

- `tests/test_runtime_console_models.py`
- `tests/test_runtime_console_store.py`
- `tests/test_runtime_console_cli.py`
- `tests/test_board_collector.py`
- `tests/test_board_server.py`
- `tests/test_board_web_ui.py`
- `tests/test_coding_integration.py`

## Findings

### 1. High: runtime console sync failures are silently swallowed

**Severity:** High  
**Category:** Reliability / Observability / Trustworthiness

The coding runtime continues to treat runtime-console synchronization as best-effort, but any failure is currently invisible to operators.

Evidence:

- [clawteam/coding/service.py:614](/root/github.com/ClawTeam-OpenClaw/clawteam/coding/service.py#L614) to [clawteam/coding/service.py:622](/root/github.com/ClawTeam-OpenClaw/clawteam/coding/service.py#L622) swallow all runtime-console sync errors
- [clawteam/runtime_console/service.py:255](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/service.py#L255) to [clawteam/runtime_console/service.py:260](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/service.py#L260) silently reconstruct a provider session view from the job record if the session record is missing

### Why this matters

This means:

- the core coding job record can be correct
- the runtime console can be partially wrong or stale
- the operator is not told that the console lost sync

This directly weakens the console's trustworthiness.

### Required fix

Do not make runtime-console sync failures fatal to coding job execution, but do make them visible.

Required approach:

- on runtime-console sync failure, create an explicit runtime fault record
- include scope and object identity where possible
- use a clear fault type such as `runtime_console_sync_failed` or `runtime_console_out_of_sync`
- make the fault visible in CLI and board

The system must degrade honestly, not silently.

---

### 2. Medium: callback-to-session closure still depends on optional `sessionId`

**Severity:** Medium  
**Category:** Correctness / Control Loop Integrity

Provider session state after callback is updated only if `WorkerCodingCallbackReport.sessionId` is present.

Evidence:

- callback report `sessionId` is optional: [clawteam/team/models.py:157](/root/github.com/ClawTeam-OpenClaw/clawteam/team/models.py#L157)
- runtime console callback handling only updates the provider session if `session_id` exists: [clawteam/runtime_console/service.py:159](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/service.py#L159) to [clawteam/runtime_console/service.py:179](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/service.py#L179)

### Why this matters

In the current design, session closure is part of the control loop.

If callback metadata omits `sessionId`, the system can end up in this inconsistent state:

- job callback status updated
- task metadata updated
- callback report persisted
- provider session remains `callback_pending`

This makes the runtime graph inconsistent.

### Required fix

Add a fallback resolution path:

- if callback report has `sessionId`, use it
- otherwise load the job record and fall back to `providerSessionRef`
- if no session linkage exists at all, emit an explicit runtime fault rather than silently skipping session closure

This ensures the callback loop is either correctly closed or explicitly marked as degraded.

---

### 3. Medium: runtime console CLI list commands fail closed on partial store corruption

**Severity:** Medium  
**Category:** Operational Resilience / CLI Reliability

Some runtime console CLI list commands currently use hard-fail read paths rather than inspect-style degrade-with-fault behavior.

Evidence:

- `coding session list` uses `list_provider_sessions()`: [clawteam/cli/commands.py:1900](/root/github.com/ClawTeam-OpenClaw/clawteam/cli/commands.py#L1900) to [clawteam/cli/commands.py:1910](/root/github.com/ClawTeam-OpenClaw/clawteam/cli/commands.py#L1910)
- `faults list` uses `list_faults()`: [clawteam/cli/commands.py:2010](/root/github.com/ClawTeam-OpenClaw/clawteam/cli/commands.py#L2010) to [clawteam/cli/commands.py:2019](/root/github.com/ClawTeam-OpenClaw/clawteam/cli/commands.py#L2019)
- `audit timeline` uses `list_timeline()`: [clawteam/cli/commands.py:2055](/root/github.com/ClawTeam-OpenClaw/clawteam/cli/commands.py#L2055) to [clawteam/cli/commands.py:2064](/root/github.com/ClawTeam-OpenClaw/clawteam/cli/commands.py#L2064)
- but inspect-style APIs already exist in store: [clawteam/runtime_console/store.py:210](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/store.py#L210), [clawteam/runtime_console/store.py:304](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/store.py#L304), [clawteam/runtime_console/store.py:338](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/store.py#L338)

### Why this matters

A serious operator CLI should keep working in degraded conditions.

If one provider session record or one timeline entry is corrupt, the CLI should still:

- return valid records
- surface the read faults explicitly
- remain usable for diagnosis

Current behavior is too brittle for an operator control plane.

### Required fix

For list-style CLI commands, prefer inspect-style collection and explicit fault reporting.

Expected behavior:

- valid records are returned
- read faults are included in payload and human output
- command does not fail unless the requested operation truly cannot continue

---

### 4. Medium: session event views are incomplete because they ignore callback-linked events

**Severity:** Medium  
**Category:** Observability / Timeline Integrity

Session event views only include events whose scope is directly `provider_session`.

Evidence:

- CLI session events filter: [clawteam/cli/commands.py:1976](/root/github.com/ClawTeam-OpenClaw/clawteam/cli/commands.py#L1976) to [clawteam/cli/commands.py:1979](/root/github.com/ClawTeam-OpenClaw/clawteam/cli/commands.py#L1979)
- board collector session events filter: [clawteam/board/collector.py:132](/root/github.com/ClawTeam-OpenClaw/clawteam/board/collector.py#L132) to [clawteam/board/collector.py:139](/root/github.com/ClawTeam-OpenClaw/clawteam/board/collector.py#L139)
- callback timeline events include `links.sessionId`: [clawteam/runtime_console/service.py:208](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/service.py#L208) to [clawteam/runtime_console/service.py:214](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/service.py#L214)

### Why this matters

A provider session timeline should show the whole control loop for that session, not just provider-session-scoped events.

Current behavior omits a critical part of causality:

- provider returned
- worker callback happened
- leader escalation or progress report followed

### Required fix

Session event views should include events where either:

- `scopeType == provider_session and scopeId == sessionId`
- or `links.sessionId == sessionId`

This should apply consistently to:

- CLI session events
- board session events
- session detail timeline view if it uses the same API/filtering logic

---

### 5. Low: live Web board selection resets on every data refresh

**Severity:** Low  
**Category:** UX / Operator Usability

The current default-selection logic reselects fault/session/job/task on every payload refresh.

Evidence:

- [clawteam/board/static/index.html:575](/root/github.com/ClawTeam-OpenClaw/clawteam/board/static/index.html#L575) to [clawteam/board/static/index.html:594](/root/github.com/ClawTeam-OpenClaw/clawteam/board/static/index.html#L594)

### Why this matters

In a live console, an operator expects to keep the current selection while inspecting details.

Current behavior can cause:

- the detail drawer to jump unexpectedly
- inspection context loss during SSE refreshes
- lower usability under active runtime churn

### Required fix

Only apply default selection when:

- there is no current selection
- or the selected object no longer exists in the new payload

Do not override a deliberate operator selection on every refresh.

---

### 6. Low: Web board `stdout` / `stderr` tabs do not yet deliver the intended inspector experience

**Severity:** Low  
**Category:** Completeness / Operator Ergonomics

The detail drawer has `stdout` and `stderr` tabs, but they currently only show artifact paths, not content or fetched previews.

Evidence:

- [clawteam/board/server.py:112](/root/github.com/ClawTeam-OpenClaw/clawteam/board/server.py#L112) exposes job artifact listing, but not object-specific artifact content retrieval
- [clawteam/board/static/index.html:1041](/root/github.com/ClawTeam-OpenClaw/clawteam/board/static/index.html#L1041) to [clawteam/board/static/index.html:1049](/root/github.com/ClawTeam-OpenClaw/clawteam/board/static/index.html#L1049) only render the artifact path label

### Why this matters

This is not a correctness bug.

However, the approved operator-console design clearly intended the detail drawer to support stronger inspection. The current implementation stops one layer short.

### Required fix

Add an API path for single artifact detail/content and use it in the board drawer so `stdout` / `stderr` become real inspection views rather than labels.

---

## What Is Already Strong

The following parts of the implementation are directionally correct and should be preserved:

- provider session is a first-class durable object
- callback report is a first-class durable object
- fault model exists as a first-class durable object
- CLI and board now have a coherent runtime-console surface
- board explicitly distinguishes provider sessions from jobs
- web board is honest about `ephemeral` and `unavailable`
- core coding runtime durability and atomic create behavior were not obviously regressed in this review

## Recommended Fix Order

### Priority 0

- surface runtime-console sync failures as explicit runtime faults
- close callback -> session linkage even when `sessionId` is omitted, using job linkage fallback

### Priority 1

- make CLI list commands resilient via inspect-style fault-aware collection
- include callback-linked events in session event views

### Priority 2

- preserve selection during SSE refresh in the Web board
- upgrade `stdout` / `stderr` board tabs from path-only to content-aware inspection

## Direct Agent Instruction

The agent should continue from the current implementation and fix the remaining Runtime Console reliability and usability gaps.

Direct instruction:

```text
Read this review and continue from the current Runtime Console implementation.

Fix in this order:

1. Runtime-console sync failures must no longer be silently invisible.
   - Keep job execution non-fatal.
   - Emit explicit runtime fault records when sync fails.

2. Callback closure must update provider session state even when callback.sessionId is missing.
   - Fall back to the coding job's providerSessionRef.
   - If no linkage exists, emit a runtime fault.

3. CLI list commands must degrade gracefully under partial runtime-console corruption.
   - Use inspect-style reads where appropriate.
   - Return valid records plus explicit faults.

4. Session event views must include events linked via links.sessionId, not only scopeType=provider_session.

5. Web board should preserve manual selection across live refreshes.

6. Web board stdout/stderr tabs should become actual artifact inspection views, not path-only placeholders.

Constraints:
- Do not weaken current coding-runtime correctness guarantees.
- Do not expand into provider config orchestration.
- Do not change cancel semantics.
- Do not invent provider session ids or resume support.
- Keep `task`, `job`, `provider session`, `callback`, and `fault` distinct.

For every fix:
- add or update tests
- run targeted tests
- report files changed, tests added, tests run, and residual risks
```

## Final Assessment

The Runtime Console is now a real subsystem, not a placeholder.

But it is not yet fully trustworthy under degraded runtime-console conditions.

The next round should focus on:

- honest degradation
- callback/session closure integrity
- CLI resilience
- session timeline completeness

After those are fixed, the remaining work is mostly operator ergonomics rather than control-plane trust.

