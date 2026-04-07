# Runtime Console Remediation Tasking

**Date:** 2026-04-05
**Repository:** ClawTeam-OpenClaw
**Audience:** The coding agent continuing Runtime Console hardening work
**Primary Inputs:**

- [Runtime Console Commit Review](/root/github.com/ClawTeam-OpenClaw/docs/agent/reviews/2026-04-05-runtime-console-commit-review.md)
- [Runtime Console Design for CLI + Web Board](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-05-runtime-console-cli-board-design.md)
- [Runtime Console Implementation Tasking](/root/github.com/ClawTeam-OpenClaw/docs/agent/plans/2026-04-05-runtime-console-implementation-tasking.md)

## Mission

Continue from the current Runtime Console implementation and close the remaining gaps that still reduce trust, control-plane honesty, and operator usability.

This is not a redesign.

This is a focused hardening pass on the existing implementation.

## Non-Negotiable Constraints

- do not weaken current coding-runtime correctness or durability guarantees
- do not expand into provider config orchestration
- do not change cancel semantics
- do not invent provider session ids or resume support
- do not collapse `task`, `job`, `provider session`, `callback`, and `fault`
- do not hide degraded behavior behind silent fallback
- every fix must include tests
- every degraded path must either remain inspectable or emit an explicit fault

## Required Work Order

Implement in this order:

1. reliability and fault honesty
2. callback/session closure correctness
3. CLI degraded-read resilience
4. session timeline completeness
5. Web board interaction correctness
6. Web board artifact inspection completeness

## Work Package 1: Surface Runtime Console Sync Failures

### Problem

Runtime-console synchronization failures are currently swallowed, which means the coding job may be correct while the Runtime Console becomes stale or incomplete without any visible signal to operators.

### Primary Evidence

- [clawteam/coding/service.py:614](/root/github.com/ClawTeam-OpenClaw/clawteam/coding/service.py#L614)
- [clawteam/coding/service.py:619](/root/github.com/ClawTeam-OpenClaw/clawteam/coding/service.py#L619)
- [clawteam/runtime_console/service.py:255](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/service.py#L255)

### Required Change

- keep coding job execution non-fatal
- on runtime-console sync failure, emit an explicit runtime fault record
- include enough context to diagnose what failed:
  - team
  - worker
  - task id if available
  - job id if available
  - provider session id if available
  - operation or phase
- use a clear fault type such as `runtime_console_sync_failed`
- ensure the emitted fault is visible through:
  - CLI faults surfaces
  - board fault surfaces
  - any relevant aggregate health payload

### Acceptance Criteria

- a sync failure no longer disappears silently
- operators can distinguish job success from console-sync degradation
- tests prove job execution remains non-fatal while fault visibility is preserved

## Work Package 2: Close Callback -> Session Loop Without Mandatory callback.sessionId

### Problem

Provider session closure still depends on `WorkerCodingCallbackReport.sessionId`, but that field is optional. This can leave callback state and provider session state inconsistent.

### Primary Evidence

- [clawteam/team/models.py:157](/root/github.com/ClawTeam-OpenClaw/clawteam/team/models.py#L157)
- [clawteam/runtime_console/service.py:159](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/service.py#L159)

### Required Change

- if callback report includes `sessionId`, use it
- otherwise load the job record and fall back to `providerSessionRef`
- if neither linkage exists, emit an explicit runtime fault
- ensure session status, callback state, and timeline stay causally aligned

### Acceptance Criteria

- callback completion updates provider session state when job linkage exists
- absence of both `sessionId` and `providerSessionRef` is visible as a fault
- no silent skip remains in the callback/session closure path

## Work Package 3: Make CLI List Surfaces Degrade Gracefully

### Problem

Several Runtime Console list commands fail closed on partial store corruption instead of returning valid records plus explicit faults.

### Primary Evidence

- [clawteam/cli/commands.py:1900](/root/github.com/ClawTeam-OpenClaw/clawteam/cli/commands.py#L1900)
- [clawteam/cli/commands.py:2010](/root/github.com/ClawTeam-OpenClaw/clawteam/cli/commands.py#L2010)
- [clawteam/cli/commands.py:2055](/root/github.com/ClawTeam-OpenClaw/clawteam/cli/commands.py#L2055)
- [clawteam/runtime_console/store.py:210](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/store.py#L210)
- [clawteam/runtime_console/store.py:304](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/store.py#L304)
- [clawteam/runtime_console/store.py:338](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/store.py#L338)

### Required Change

- use inspect-style collection where list commands read persisted Runtime Console objects
- preserve valid records even when some entries are corrupt
- surface read faults clearly in both:
  - machine output
  - human-readable output
- only fail the command when the operation truly cannot proceed

### Acceptance Criteria

- partial corruption no longer makes the full list surface unusable
- valid objects remain visible
- read faults are explicit and test-covered

## Work Package 4: Include Callback-Linked Events In Session Timelines

### Problem

Session event views only include direct `provider_session` scope events and ignore events linked through `links.sessionId`.

### Primary Evidence

- [clawteam/cli/commands.py:1976](/root/github.com/ClawTeam-OpenClaw/clawteam/cli/commands.py#L1976)
- [clawteam/board/collector.py:132](/root/github.com/ClawTeam-OpenClaw/clawteam/board/collector.py#L132)
- [clawteam/runtime_console/service.py:208](/root/github.com/ClawTeam-OpenClaw/clawteam/runtime_console/service.py#L208)

### Required Change

Session event collection must include:

- events where `scopeType == provider_session` and `scopeId == sessionId`
- events where `links.sessionId == sessionId`

Apply this consistently to:

- CLI session event views
- board collector session event views
- any shared timeline/detail helper used by these surfaces

### Acceptance Criteria

- session timelines show callback causality
- CLI and board session views remain consistent
- no duplicate event inflation in merged results

## Work Package 5: Preserve Board Selection Across Refresh

### Problem

The Web board currently resets selected fault/session/job/task during live refresh, which breaks operator inspection flow.

### Primary Evidence

- [clawteam/board/static/index.html:575](/root/github.com/ClawTeam-OpenClaw/clawteam/board/static/index.html#L575)

### Required Change

- preserve current selection when the selected object still exists in the new payload
- only auto-select when:
  - nothing is selected
  - or the selected object no longer exists
- ensure SSE refresh does not override deliberate operator focus

### Acceptance Criteria

- manual selection is stable during refresh
- selection only changes when the selected object disappears
- add UI-level test coverage if such tests already exist for the board

## Work Package 6: Make stdout/stderr Tabs Real Inspectors

### Problem

The board exposes `stdout` and `stderr` tabs but currently renders only artifact paths instead of actual content inspection.

### Primary Evidence

- [clawteam/board/server.py:112](/root/github.com/ClawTeam-OpenClaw/clawteam/board/server.py#L112)
- [clawteam/board/static/index.html:1041](/root/github.com/ClawTeam-OpenClaw/clawteam/board/static/index.html#L1041)

### Required Change

- add server/API support for single artifact retrieval or preview
- wire the board detail drawer to fetch and render artifact content
- handle missing artifact content honestly:
  - unavailable
  - unreadable
  - truncated preview
- do not fake live streaming if the implementation is snapshot-based

### Acceptance Criteria

- `stdout` and `stderr` tabs provide real content inspection
- missing or unreadable artifacts are shown explicitly
- API and UI behavior are test-covered

## Test Requirements

At minimum, add or update targeted tests for:

- runtime-console sync failure fault emission
- callback completion with missing `sessionId` but present `providerSessionRef`
- callback completion with no linkage, producing a fault
- CLI list behavior under partial corrupted runtime-console records
- session event aggregation including `links.sessionId`
- board selection preservation across refresh
- board artifact content fetch/render behavior

Do not rely on manual testing alone.

## Delivery Format

When reporting completion, provide:

1. files changed
2. tests added or updated
3. commands run
4. what was fixed
5. remaining residual risks

## Direct Instruction To Agent

```text
Read:
1. docs/agent/reviews/2026-04-05-runtime-console-commit-review.md
2. docs/design/specs/2026-04-05-runtime-console-cli-board-design.md
3. docs/agent/plans/2026-04-05-runtime-console-remediation-tasking.md

Then implement the remediation work in the required order.

Rules:
- keep runtime correctness and durability intact
- do not expand scope
- do not silently degrade
- add tests for every fix
- report residual risk honestly

Priority order:
P0: sync-failure fault visibility
P0: callback -> session closure fallback
P1: CLI degrade-with-fault list behavior
P1: session timeline completeness via links.sessionId
P2: board selection persistence
P2: board stdout/stderr content inspection
```
