# Coding Runtime Quality Hardening Guide

**Date:** 2026-04-05
**Audience:** The coding agent continuing work on the ClawTeam-OpenClaw coding callback runtime
**Scope:** Improve quality, stability, determinism, correctness, and reliability for the current V1 design without expanding into detached async callback runtime or provider configuration management.

## Purpose

The current implementation is already functionally solid:

- callback returns to the same worker
- job state and worker decision are separated
- worktree / cwd boundaries are explicit
- success requires structured result normalization
- coding job metadata is visible from the board and task views
- targeted tests are passing

This guide is about taking the current V1 from "working and credible" to "high-confidence and production-hardened".

## What Not To Do

Do **not** treat quality work as an excuse to expand scope.

Still out of scope for this guide:

- detached async callback runtime
- provider model/profile/config orchestration
- multi-provider scheduling
- live cross-backend process killing as a new platform promise

The goal is to harden V1, not turn it into V2.

## Current Strengths

The implementation already has the right direction in these areas:

- durable job, result, event, and artifact persistence
- explicit terminal job states
- explicit worker decision reporting model
- fail-closed normalization for provider success
- deterministic cwd resolution with worker workspace boundary checks
- one-active-job concurrency guardrails
- board/task observability hooks

These should be preserved.

## Priority 0: Protect Contract Stability

Before changing behavior, freeze and preserve these contracts:

- `CodingExecRequest`
- `CodingExecResult`
- `CodingJobRecord`
- `CodingJobEvent`
- `WorkerCodingCallbackReport`
- job state transition rules
- cwd precedence rules
- startup flag defaults

Required action:

- add contract-focused tests whenever behavior changes
- do not silently rename or reshape persisted fields
- if a persisted schema change is necessary, add explicit versioning first

## Priority 1: Fix Cancel Semantics Race

### Problem

`cancel` is currently documented as durable-state semantics, not live process termination. That is acceptable for V1.

However, there is still a correctness risk:

- a running job can be marked `cancelled` in durable state
- the underlying provider process may still finish normally
- the in-flight executor may then attempt to complete the job
- this can create a state conflict and lead to confusing terminal outcomes

### Required hardening

Implement one explicit policy and test it:

Option A: preferred for V1
- once a job is cancelled in durable state, later provider completion must not overwrite it
- the executor should detect terminal `cancelled` state before writing final success/failure
- artifacts may still be written best-effort, but the job state must remain `cancelled`

Option B: acceptable fallback
- queued jobs can be cancelled
- running jobs can only be marked `cancel_requested` in metadata
- the final terminal state is decided by the original execution path

### Acceptance

Add tests for:

- cancel before provider returns
- provider returns after cancel
- final durable state remains consistent
- emitted event history is explainable

## Priority 2: Add Persisted Schema Versioning

### Problem

Current persisted job/result/event JSON files do not appear to contain a schema version.

This is manageable now, but becomes risky as the runtime evolves.

### Required hardening

Add a lightweight schema version field to persisted durable records:

- job records
- result records
- event records
- callback report metadata if persisted into task metadata in a structured way

Recommended shape:

- `schemaVersion: 1`

### Acceptance

- new writes include schema version
- old reads fail safely or are handled explicitly
- tests cover version presence and read-path behavior

## Priority 3: Tighten Provider Output Contract Testing

### Problem

The implementation correctly requires structured JSON markers for success, but this behavior is central enough that it needs stronger negative-path coverage.

### Required hardening

Add tests for:

- missing start marker
- missing end marker
- empty payload between markers
- malformed JSON payload
- valid JSON with missing required fields
- payload with invalid signal types
- extra prose before/after markers

### Acceptance

- only valid structured payloads produce `completed`
- all malformed variants produce deterministic `failed`
- raw stdout/stderr remain available in artifacts for diagnosis

## Priority 4: Strengthen Durability Under Partial Persistence Failure

### Problem

The service already distinguishes persistence failures, which is good. But this is a critical trust boundary and should be hardened further.

### Required hardening

Add tests and behavior checks for:

- artifact write failure before result write
- result write failure after artifact write
- event append failure after job save
- job save failure during best-effort failure marking

Clarify the persistence priority order:

1. durable terminal job state
2. durable result record
3. durable artifacts
4. durable event append

If the exact order differs, document the chosen order and why.

### Acceptance

- operator can inspect what was persisted even in partial failure cases
- terminal durable state is never silently optimistic
- test suite covers the major partial-failure branches

## Priority 5: Make Concurrency Policy Explicit Everywhere

### Problem

The runtime currently enforces:

- one active coding job per worker
- one active coding job per task

This is good for V1 control, but it needs to be made explicit everywhere to avoid future accidental violations.

### Required hardening

- document both constraints in README and command help
- add tests proving the task-level guard is intentional
- ensure any future queueing logic does not silently weaken this contract

### Acceptance

- no ambiguity about concurrency limits
- tests fail if a future change weakens these limits unintentionally

## Priority 6: Reduce Ambiguity Around `allow_cwd_escape`

### Problem

`allow_cwd_escape` is explicit, which is better than silent escape, but it still creates a reliability and safety boundary worth hardening.

### Required hardening

- document when `allow_cwd_escape` is permitted operationally
- add tests for escape with and without explicit flag
- ensure board and job records preserve requested/effective cwd for auditability
- consider emitting a warning event or metadata marker when escape is used

### Acceptance

- escaped cwd execution is always intentional and visible
- no hidden boundary bypass remains

## Priority 7: Improve Board and Observability Reliability

### Problem

The board data path is useful, but observability should not depend on UI assets loading successfully.

The current static board frontend pulls assets from external CDNs.

### Required hardening

- ensure CLI/Rich board output remains the primary operational surface
- document that static frontend availability is not the source of truth
- consider vendoring or pinning frontend assets later if web UI reliability matters operationally
- make sure coding summary rendering does not break when fields are missing or partially written

### Acceptance

- terminal/CLI board remains reliable without network dependencies
- web UI degradation does not compromise operational visibility

## Priority 8: Expand Recovery-Focused Tests

### Problem

Current tests validate nominal and several failure paths, but recovery confidence improves when tests simulate interrupted or stale state.

### Required hardening

Add tests for:

- stale running job record inspection
- retry from failed state with preserved lineage
- replay from completed state with preserved lineage
- repeated cancel request on same job
- result file missing while job record exists
- artifact file missing while result record exists

### Acceptance

- recovery surfaces remain readable and deterministic
- lineage stays coherent across retries/replays

## Priority 9: Add Reviewable Invariants to README

### Problem

The README already states the main V1 limits. It should also state the invariants that operators and future agents must preserve.

### Required additions

Document these invariants clearly:

- success requires structured normalization, not exit code alone
- worker is the only decision authority after coding completion
- leader receives summarized reports, not raw provider output by default
- one worker = one active coding job in V1
- one task = one active coding job in V1
- cancel is durable-state semantics, not live process control
- provider config remains external to ClawTeam-OpenClaw

## Priority 10: Add a Dedicated Quality Gate

Before future merges to the coding runtime, require a standard validation sequence.

Recommended quality gate:

1. run coding runtime tests
2. run touched legacy tests
3. verify README and docs if behavior changed
4. inspect state/event/result file shapes with real sample output
5. verify board collector still renders coding fields

## Suggested Execution Order

Do not attack all hardening tasks at once. Use this order:

1. cancel semantics race
2. schema versioning
3. normalization negative-path tests
4. persistence-failure hardening
5. concurrency documentation/tests
6. cwd escape visibility
7. recovery-focused tests
8. README invariant update
9. optional web UI asset hardening discussion

## Definition of "10/10 V1" for This Project

Within V1 scope, the implementation can be considered near-maximal if all of the following are true:

- callback loop is correct and deterministic
- terminal job states are trustworthy under race and failure
- provider success cannot be faked by prose-only output
- worker/leader responsibility boundary remains clean
- cwd boundary is explicit and auditable
- concurrency limits are enforced and documented
- persistence failure leaves inspectable evidence
- board/task observability remains usable under degraded conditions
- tests cover both positive and failure-path behavior meaningfully

That is how this project reaches a professional 10/10 within its chosen scope, without pretending to solve V2 problems.
