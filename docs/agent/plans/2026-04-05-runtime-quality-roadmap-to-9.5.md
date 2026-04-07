# Runtime Quality Roadmap To 9.5+

**Date:** 2026-04-05
**Repository:** ClawTeam-OpenClaw
**Audience:** The coding agent continuing reliability, correctness, and operator-surface hardening
**Purpose:** Record the current reliability assessment, remaining risks, next optimization directions, and the concrete path required to move the project from a strong V1 to a 9.5+ quality bar.

## Current Position

The project is now usable.

It is no longer a prototype-only system.

The current state is best described as:

- a strong V1
- suitable for real internal usage
- structurally credible
- trustworthy inside its declared scope
- not yet at the "nearly fully trusted" 9.5+ level

Current overall judgement:

- design quality: high
- core callback runtime: strong
- Runtime Console: real subsystem
- CLI + board operator surface: useful and credible
- remaining gap: next-stage control, delivery, reconciliation, and hostile-state assurance

Current overall score:

- approximately `9.0 ~ 9.1 / 10`

Target:

- `9.5+ / 10`

That target is reachable, but not by cosmetic polish.

It requires another quality pass focused on:

- degraded-path honesty
- fault-aware operational resilience
- stronger recovery behavior
- stronger test coverage for bad-state scenarios

## Read Before Coding

Read these documents in order:

1. [Coding Agent Callback Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-04-coding-agent-callback-design.md)
2. [Runtime Console Design for CLI + Web Board](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-05-runtime-console-cli-board-design.md)
3. [Coding Callback Runtime Re-Review](/root/github.com/ClawTeam-OpenClaw/docs/agent/reviews/2026-04-05-coding-callback-runtime-rereview.md)
4. [Runtime Console Commit Review](/root/github.com/ClawTeam-OpenClaw/docs/agent/reviews/2026-04-05-runtime-console-commit-review.md)
5. [Runtime Console Remediation Tasking](/root/github.com/ClawTeam-OpenClaw/docs/agent/plans/2026-04-05-runtime-console-remediation-tasking.md)
6. [Runtime Console V1 Gap Closure Plan](/root/github.com/ClawTeam-OpenClaw/docs/agent/plans/2026-04-05-runtime-console-gap-closure-plan.md)
7. [Runtime Quality Roadmap To 9.5+](/root/github.com/ClawTeam-OpenClaw/docs/agent/plans/2026-04-05-runtime-quality-roadmap-to-9.5.md)

## Current Strengths

Preserve these qualities.

Do not regress them while hardening:

- callback returns to the worker rather than bypassing the team runtime
- durable state remains the source of truth
- `task`, `job`, `provider session`, `callback`, and `fault` remain distinct objects
- Runtime Console remains a first-class subsystem, not a UI-only layer
- CLI and board operate on the same durable runtime model
- callback/session mismatch is now explicitly faulted
- artifact preview now respects artifact-root boundaries
- task metadata no longer updates before missing-job callback validation

## Current Residual Risks

These are the main remaining risks after the current `9.1` baseline.

### 1. Callback delivery is still the synchronous V1 model

The current architecture intentionally keeps callback delivery coupled to the present worker-driven flow.

This is acceptable for the current baseline.

It is still a gap relative to the `9.5+` target because detached async delivery and stronger callback recovery are not implemented.

### 2. Control semantics remain the current durable-state V1 model

The current system exposes durable job/session/task truth clearly.

It does not yet provide stronger live control semantics such as:

- stronger kill/cancel acknowledgement
- richer attach/reattach control
- explicit control-operation records beyond the current durable state model

### 3. Reconciliation and hostile-state recovery are not yet first-class

The current implementation preserves truth boundaries and surfaces corruption honestly.

It does not yet provide a dedicated reconciliation layer for:

- callback recovery
- session/job truth re-establishment
- crash/interruption rebuild flows
- stronger post-failure recovery semantics

### 4. Documentation and operator guidance must stay aligned with the shipped surfaces

The runtime has grown into a real subsystem.

The README and operator-facing guidance must stay synchronized with:

- the actual CLI/runtime-console surfaces
- the board authority model
- the current OpenClaw versus non-OpenClaw support boundary
- current V1 limits and non-goals

## Progress Snapshot After This Hardening Pass

The immediate Layer 1 and Layer 2 gaps are now materially smaller.

Completed in code and tests:

- task operational call sites now degrade with explicit `readFaults` instead of failing wholesale on one corrupt task file
- waiter, task list/stats, and lifecycle cleanup preserve healthy task visibility under partial corruption
- board JSON/API, Rich board, and Web board now surface task, coding, and runtime fault classes explicitly instead of implying a fully healthy view
- mixed-fault coverage now includes corrupt task + corrupt job + explicit runtime fault in one operator payload

What this did **not** do:

- it did not redesign the current synchronous callback architecture
- it did not change cancel semantics
- it did not expand into provider config orchestration
- it did not invent provider session identity or resume support where none exists

## Non-Negotiable Constraints

- do not redesign the callback architecture
- do not expand into provider config orchestration
- do not change current cancel semantics
- do not invent provider session ids or resume support
- do not hide corruption as missing state
- do not collapse runtime object boundaries
- do not let board diverge semantically from CLI
- do not "fix" fault visibility by suppressing errors
- do not weaken durable truth in order to improve superficial UX

## Roadmap

This work should be implemented in three layers.

At the current `9.1` baseline:

- Layer 1 is materially complete
- Layer 2 is materially complete for the currently declared hardening scope
- the active next step is documentation alignment followed by Layer 3 design preparation

## Layer 1: Finish The Strong V1

This layer is now substantially complete.

Keep it here as the closure record for the hardening work that established the `9.1` baseline.

### Workstream A: Make task list/read surfaces degrade with explicit faults

#### Goal

Keep operational surfaces useful under partial task corruption without pretending corruption does not exist.

#### Required Changes

- identify every operational path that currently uses `TaskStore.list_tasks()` where degrade-with-fault is more appropriate
- convert those paths to use `TaskStore.inspect_tasks()` or an equivalent fault-aware helper
- preserve valid tasks
- surface `readFaults` or explicit task-fault payloads where applicable
- only fail closed where the operation truly requires an exact fully-valid task set

#### Immediate Priority Targets

- waiter progress loop
- waiter dead-agent recovery scan
- task list CLI
- agent cleanup/recovery paths
- any list/scan route that should remain diagnostically useful under partial corruption

#### Acceptance Criteria

- one corrupt task file does not blind or abort the whole operational view
- healthy tasks still remain inspectable
- corruption is explicit and visible
- degrade behavior is consistent across affected call sites

### Workstream B: Render task read faults prominently in the Web board

#### Goal

Make task-layer degradation visible to the operator without requiring raw JSON inspection.

#### Required Changes

- expose task read-fault counts in a visible board health area
- render task read-fault warnings in the board UI
- ensure the UI clearly communicates that part of task data is degraded
- keep wording aligned with the durable-truth model

#### Acceptance Criteria

- the board cannot silently look healthy when task corruption exists
- the operator can distinguish runtime faults from task read faults
- the board remains honest about partial task visibility

### Workstream C: Add targeted task corruption integration tests

#### Goal

Raise confidence that the task-layer degraded paths behave professionally.

#### Required Changes

Add or update tests for:

- waiter under corrupt task state
- dead-agent recovery under corrupt task state
- task list CLI under corrupt task state
- cleanup paths under corrupt task state
- board UI rendering of task read faults

#### Acceptance Criteria

- corrupted task-state handling is explicitly tested at integration level
- regressions in fault-aware task handling become hard to reintroduce

## Layer 2: Raise Operator Trust And Diagnostic Quality

This layer is also materially complete for the currently declared V1 hardening scope.

Keep it here as the closure record for fault-surface and mixed-fault hardening work.

### Workstream D: Unify fault presentation across task, coding, runtime-console, and board

#### Goal

Make all fault surfaces feel like one professional operator system.

#### Required Changes

- align how task read faults, coding read faults, runtime faults, and callback linkage faults are presented
- ensure both CLI and board distinguish:
  - explicit runtime faults
  - durable read faults
  - operator-visible degraded states
- improve human-readable output wording so partial-data states are obvious

#### Acceptance Criteria

- fault classes are understandable and not conflated
- CLI and board tell the same story
- operators can diagnose degradation without reading source code

### Workstream E: Strengthen failure-mode and mixed-fault tests

#### Goal

Make reliability claims defensible.

#### Required Changes

Add mixed-state tests such as:

- corrupt task + corrupt job together
- callback mismatch + task corruption
- runtime-console degraded state + task read fault in same board payload
- operator list commands under multiple simultaneous read-fault classes

#### Acceptance Criteria

- the system is tested not only for isolated failures but also for realistic combined degraded states

## Layer 3: Reach 9.5+ Territory

This layer is not required to call the project usable.

It is required to call it near fully trusted.

This is the difference between a strong V1 and a nearly mature operator runtime.

### Workstream F: Detached async callback delivery design and implementation

#### Goal

Reduce coupling to synchronous callback return timing and improve recovery options.

#### Design Preparation Notes

- do this only after the current V1 degraded paths are strong
- do not start here before Layer 1 and Layer 2 are solid
- if introduced later, async callback delivery must be represented as a new durable object such as `callback_delivery` or equivalent, not hidden inside coding job state
- coding job terminal state must remain a provider-execution fact; callback delivery state must remain a separate delivery/control fact
- worker decision remains downstream from callback delivery completion and must not be collapsed into provider execution state
- missing or delayed callback delivery must remain explicitly inspectable rather than inferred from process exit or missing events

### Workstream G: Stronger execution/session control

#### Goal

Move beyond durable-state-only control semantics.

Design preparation directions:

- stronger live cancel semantics
- stronger attach/reattach control
- clearer process/session lifecycle control across backends
- any stronger control channel must keep current V1 durable truth as the authoritative audit plane
- future control acknowledgements should become explicit durable control records rather than ad hoc status mutation
- provider limitations must remain visible; unsupported live control cannot be surfaced as if it were guaranteed

### Workstream H: Recovery, replay, and reconciliation semantics

#### Goal

Allow the system to re-establish a coherent truth after partial failure.

Design preparation directions:

- callback reconciliation
- provider/session/job state reconciliation
- crash-recovery workflows
- replay/rebuild of operator state after interruption
- reconciliation must compare durable task/job/session/callback facts without merging those object models
- any reconciler should emit explicit faults or reconciliation records when truth cannot be fully recovered
- corruption and ambiguity must stay operator-visible; reconciliation is not allowed to fabricate clean success states

### Workstream I: Stronger chaos/corruption/recovery testing

#### Goal

Back 9.5+ reliability claims with deliberate hostile-state testing.

Potential directions:

- partial writes
- mixed corruption states
- interrupted callback flows
- stale session linkage
- board/CLI consistency under multiple simultaneous degraded conditions

## What 9.5+ Means In Practice

The project should only be considered `9.5+` when all of the following are true:

- degraded paths are consistently fault-aware across task, coding, runtime-console, CLI, and board
- operators can continue diagnosis under partial corruption without losing healthy data visibility
- board and CLI are both honest and consistent about degraded state
- callback/session/job/task truth remains causally explainable under failure
- recovery semantics are stronger than simple best-effort durability
- failure-mode testing covers realistic combinations, not just isolated happy-path fixes

## Delivery Order

Treat the current branch as a successful `9.1` baseline.

The coding agent should implement from here in this order:

1. user-facing documentation alignment for the shipped runtime-console and coding-runtime surfaces
2. operator guidance alignment for authority model, board role, support boundaries, and V1 limits
3. detached async callback design preparation
4. stronger control semantics design preparation
5. reconciliation/recovery design preparation
6. stronger hostile-state and mixed-fault assurance after the design prep is clear

## Reporting Requirements

When reporting progress or completion, always include:

1. files changed
2. tests added or updated
3. commands run
4. which roadmap layer/workstream was addressed
5. what residual risks remain
6. whether each residual risk is:
   - by design
   - by implementation
   - by provider limitation

## Direct Instruction To Agent

```text
Read:
1. docs/design/specs/2026-04-04-coding-agent-callback-design.md
2. docs/design/specs/2026-04-05-runtime-console-cli-board-design.md
3. docs/agent/reviews/2026-04-05-coding-callback-runtime-rereview.md
4. docs/agent/reviews/2026-04-05-runtime-console-commit-review.md
5. docs/agent/plans/2026-04-05-runtime-console-remediation-tasking.md
6. docs/agent/plans/2026-04-05-runtime-console-gap-closure-plan.md
7. docs/agent/plans/2026-04-05-runtime-quality-roadmap-to-9.5.md

Then continue hardening the project toward the 9.5+ quality bar.

Immediate implementation priority:
P0:
- update README and operator-facing usage guidance so the shipped runtime-console/coding-runtime surfaces are accurately documented
- align board role, authority model, support boundaries, and current V1 limits with the implementation

P1:
- prepare the next-stage design for detached async callback
- prepare the next-stage design for stronger control semantics
- prepare the next-stage design for reconciliation and recovery

P2:
- extend implementation only after documentation and design prep stay aligned with the shipped 9.1 baseline

Rules:
- do not redesign the current callback architecture in this pass
- do not expand into provider config orchestration
- do not silently degrade
- do not weaken durability or truth boundaries
- add tests for every behavior change
- report residual risks honestly
```
