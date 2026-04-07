# Runtime Console V1 Gap Closure Plan

**Date:** 2026-04-05
**Repository:** ClawTeam-OpenClaw
**Audience:** The coding agent continuing the Runtime Console hardening work
**Purpose:** Close the implementation gap between the current strong V1 design and a trustworthy V1 operator runtime.

## Positioning

The current design direction is correct.

This plan is not asking for redesign.

It is asking for a disciplined implementation hardening pass so that the delivered system matches the design quality more closely.

Current judgement:

- design quality is already high
- core callback runtime is already credible
- the remaining gap is mainly implementation quality, degraded-path honesty, and operator trust

## Read Before Coding

Read these documents in order:

1. [Coding Agent Callback Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-04-coding-agent-callback-design.md)
2. [Runtime Console Design for CLI + Web Board](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-05-runtime-console-cli-board-design.md)
3. [Coding Callback Runtime Re-Review](/root/github.com/ClawTeam-OpenClaw/docs/agent/reviews/2026-04-05-coding-callback-runtime-rereview.md)
4. [Runtime Console Commit Review](/root/github.com/ClawTeam-OpenClaw/docs/agent/reviews/2026-04-05-runtime-console-commit-review.md)
5. [Runtime Console Remediation Tasking](/root/github.com/ClawTeam-OpenClaw/docs/agent/plans/2026-04-05-runtime-console-remediation-tasking.md)

## Mission

Move the Runtime Console from:

- structurally credible
- mostly observable
- partly trustworthy under degraded conditions

to:

- honest under failure
- causally complete
- resilient under partial corruption
- usable as a serious operator surface

## Non-Negotiable Constraints

- do not redesign the callback architecture
- do not expand into detached async callback delivery
- do not expand into provider config orchestration
- do not change current cancel semantics
- do not invent provider session ids or resume support
- do not merge `task`, `job`, `provider session`, `callback`, and `fault`
- do not add UI-only behavior that lacks durable truth or API support
- do not hide degraded behavior behind silent fallback

## Why This Work Exists

The current implementation gap is not mainly about feature absence.

It is mainly about these trust gaps:

1. sync failures can be invisible
2. callback -> session closure is not guaranteed when callback metadata is incomplete
3. CLI degraded-read behavior is too brittle
4. session timelines are not fully causal
5. board live interaction is not stable enough for operators
6. artifact inspection is one layer short of the intended operator experience

## Target Outcome

After this work:

- the Runtime Console should be trustworthy within the declared V1 scope
- degraded conditions should be visible, not hidden
- CLI and board should tell the same story
- session timelines should explain the callback loop coherently
- board interaction should support real inspection rather than superficial browsing

## Workstream A: Fault Honesty

### Goal

Ensure runtime-console synchronization failures are visible as durable faults instead of disappearing silently.

### Required Changes

- when Runtime Console synchronization fails, emit an explicit runtime fault
- include operation context and object identity when available
- keep coding job execution non-fatal
- surface the fault in both CLI and board

### Done Means

- operators can see that the job succeeded but Runtime Console sync degraded
- no silent sync-loss path remains

## Workstream B: Callback Closure Integrity

### Goal

Ensure callback completion closes the provider-session loop even when callback metadata is incomplete.

### Required Changes

- use callback `sessionId` when present
- otherwise resolve through the coding job's `providerSessionRef`
- if no linkage exists, emit an explicit fault
- keep job status, callback status, provider session status, and timeline causality aligned

### Done Means

- callback processing no longer leaves orphaned `callback_pending` sessions when linkage is durably available
- missing linkage becomes inspectable degradation instead of silent inconsistency

## Workstream C: CLI Resilience Under Partial Corruption

### Goal

Make the CLI behave like an operator tool instead of a brittle reader.

### Required Changes

- switch list-style Runtime Console commands to fault-aware inspect-style collection where appropriate
- preserve valid records when some persisted entries are corrupt
- report read faults explicitly in machine output and human output

### Done Means

- partial corruption no longer blinds the operator
- valid records and faults can be seen together

## Workstream D: Timeline Completeness

### Goal

Make session timelines reflect the actual callback loop.

### Required Changes

- session event queries must include:
  - direct `provider_session` scoped events
  - events linked by `links.sessionId`
- apply this consistently to CLI and board aggregation
- avoid duplicate event inflation

### Done Means

- operators can follow provider completion -> callback report -> worker decision within one coherent session view

## Workstream E: Board Interaction Correctness

### Goal

Make the board stable enough for live inspection.

### Required Changes

- preserve manual selection across refresh when the selected object still exists
- only fall back to default selection when nothing is selected or the selected object disappeared

### Done Means

- the operator can inspect one object without the UI stealing focus on refresh

## Workstream F: Board Artifact Inspection

### Goal

Turn `stdout` and `stderr` into real inspectors.

### Required Changes

- add API support for single artifact content or preview retrieval
- render actual content in the board drawer
- explicitly represent unavailable, unreadable, or truncated content

### Done Means

- `stdout` and `stderr` tabs are operationally useful
- the board supports real job-output inspection

## Required Test Coverage

Add or update targeted tests for:

- runtime-console sync failure producing visible faults
- callback completion with missing `sessionId` but valid `providerSessionRef`
- callback completion with no valid linkage emitting a fault
- CLI list behavior under partial record corruption
- session event aggregation through `links.sessionId`
- board selection persistence during refresh
- board artifact content retrieval and rendering

Do not treat manual browser clicking as sufficient evidence.

## Delivery Rules

When reporting completion, include:

1. files changed
2. tests added or updated
3. commands run
4. which trust gaps were closed
5. residual risks that remain by design versus by implementation

## Final Acceptance Standard

This work is complete only when all of the following are true:

- degraded Runtime Console paths fail honestly
- callback/session closure is reliable or explicitly faulted
- CLI remains useful under partial persisted-data damage
- session timelines are causally complete enough for operator reasoning
- board refresh behavior no longer breaks inspection flow
- board artifact tabs provide actual inspection value

## Direct Instruction To Agent

```text
Read:
1. docs/design/specs/2026-04-04-coding-agent-callback-design.md
2. docs/design/specs/2026-04-05-runtime-console-cli-board-design.md
3. docs/agent/reviews/2026-04-05-coding-callback-runtime-rereview.md
4. docs/agent/reviews/2026-04-05-runtime-console-commit-review.md
5. docs/agent/plans/2026-04-05-runtime-console-gap-closure-plan.md
6. docs/agent/plans/2026-04-05-runtime-console-remediation-tasking.md

Then implement the remaining Runtime Console V1 gap-closure work.

Rules:
- do not redesign
- do not expand scope
- keep correctness and durability intact
- do not silently degrade
- add tests for every fix
- report residual risk honestly

Priority:
P0: fault honesty
P0: callback/session closure integrity
P1: CLI degraded-read resilience
P1: session timeline completeness
P2: board selection stability
P2: board artifact inspection
```
