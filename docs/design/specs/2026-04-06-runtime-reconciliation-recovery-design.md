# Runtime Reconciliation and Recovery Design

**Date:** 2026-04-06  
**Status:** Draft for next-stage implementation planning  
**Repository:** ClawTeam-OpenClaw  
**Scope:** Recovery, reconciliation, and operator repair semantics on top of the current V1 synchronous callback runtime

## 1. Goal

Define the recovery and reconciliation layer required to move the current runtime from a strong V1 toward the `9.5+` quality bar without redesigning the current callback architecture in this pass.

This design keeps the existing truths:

- coding job execution remains a durable provider-execution fact
- worker callback decision remains a separate downstream control fact
- task, coding job, provider session, callback report, and runtime fault remain distinct objects
- provider configuration orchestration remains out of scope

## 2. Problem Statement

The current runtime is durable and inspectable, but recovery is still mostly manual.

When a worker crashes, a callback arrives late, or a provider session record diverges from the coding job timeline, operators need a first-class answer to:

1. what is authoritative
2. what is merely stale, missing, or duplicated
3. what can be repaired automatically
4. what requires explicit operator intervention

The next-stage subsystem is therefore not a new provider runner. It is a durable reconciliation layer over existing persisted facts.

## 3. Authority Model

Authority must remain explicit.

### 3.1 Task

`task` remains the business work item owned by the team runtime.

Authority:

- owner, status, blocking graph, and task metadata are authoritative only from persisted task files
- task metadata may summarize coding activity, but it does not replace the coding job or callback record

### 3.2 Coding Job

`coding job` remains the authoritative provider-execution record.

Authority:

- queued/running/completed/failed/timeout/cancelled are provider/job facts
- coding job terminal state is not inferred from worker exit, session exit, or mailbox text
- normalized result remains authoritative only when persisted successfully

### 3.3 Provider Session

`provider session` remains the authoritative runtime-console model for reusable or ephemeral provider execution linkage.

Authority:

- session linkage may be unavailable
- if unavailable, the system must represent `ephemeral` or `unavailable`, not fabricate resumability
- session state is not allowed to override coding job truth

### 3.4 Callback Report

`callback report` remains the authoritative worker post-provider decision record.

Authority:

- callback decision is authoritative only when a callback report is durably persisted
- callback report does not rewrite job execution truth
- callback report does not by itself prove task completion

### 3.5 Runtime Fault

`runtime fault` remains the authoritative way to say the control plane observed degraded or inconsistent state.

Authority:

- faults explain degraded reads, linkage mismatches, partial sync failures, and reconciliation findings
- faults are not silently collapsed into missing data

## 4. Unreconciled State Model

The next-stage runtime should introduce an explicit concept of `unreconciled state`.

This is not a new job state.

It is a durable diagnosis over existing objects.

Recommended reconciler outputs:

- `healthy`
- `needs_reconcile`
- `repair_in_progress`
- `reconciled`
- `repair_blocked`

These belong to a future reconciliation object such as `runtime_reconcile_record`, not to `task` or `coding job` lifecycle state.

## 5. Failure and Recovery Semantics

### 5.1 Worker Crash During Running Job

Observed facts may be:

- task still `in_progress` or stale
- coding job `running`
- no callback report
- provider session maybe still active or maybe gone

Required semantics:

- do not infer callback completion from worker process exit
- surface a reconciliation finding like `running_job_without_worker`
- allow operator to inspect job/session artifacts before deciding whether to retry, cancel, or wait

### 5.2 Worker Crash After Job Completion but Before Callback

Observed facts may be:

- coding job terminal and result persisted
- no callback report
- task metadata not updated or stale

Required semantics:

- represent this explicitly as `callback_missing_after_terminal_job`
- do not mutate task metadata automatically unless a future repair action explicitly does so
- provide an operator repair action that can re-deliver or reconstruct the callback decision path only from durable job truth plus explicit operator intent

### 5.3 Callback Missing

Observed facts:

- terminal job exists
- no callback record

Required semantics:

- visible fault and reconcile candidate
- repair entry point must require explicit decision input if worker intent cannot be safely inferred
- if the system cannot know the worker decision, it must not fabricate one

### 5.4 Callback Duplicate

Observed facts:

- same job receives multiple callback reports

Required semantics:

- first durable callback remains authoritative unless a future control operation explicitly supersedes it
- duplicates should produce a reconciliation finding such as `duplicate_callback_report`
- duplicates must remain inspectable; they must not silently overwrite history

### 5.5 Callback Late Arrival

Observed facts:

- task may already have moved on
- provider session may already be closed
- original worker may be dead

Required semantics:

- late callback must be recorded as a separate arrival fact
- if it cannot be safely applied, mark it as `late_unapplied_callback`
- operators must see both the callback content and why it was not applied

## 6. CLI and Board Presentation

Unreconciled state must be visible in both CLI and board surfaces.

### 6.1 CLI

Future CLI additions should include:

- `clawteam reconcile list --team <team>`
- `clawteam reconcile status <scope-id> --team <team>`
- `clawteam reconcile inspect <record-id> --team <team>`
- `clawteam reconcile repair <record-id> ...`

Presentation rules:

- show authoritative facts first: task, job, session, callback, fault
- then show the reconciliation diagnosis
- then show available repair actions

### 6.2 Board

Board should expose a clear degraded-state layer:

- unreconciled-count badge
- unresolved callback/session/task mismatches
- drill-down from task -> job -> session -> callback -> reconcile record

The board remains a convenience UI. It must render the same durable reconciliation records the CLI reads.

## 7. Operator Actions

Future operator actions should be explicit durable control operations, not hidden mutations.

Recommended actions:

- `repair callback-missing`
- `retry callback delivery`
- `retry coding job`
- `cancel stale running job`
- `mark unreconciled state acknowledged`

Rules:

- every repair action should persist a control-operation record
- repair actions must cite the authority source they rely on
- if worker decision cannot be derived safely, the operator must supply it explicitly

## 8. Minimal Interface Preparation

This pass does not implement the reconciler.

Minimal preparation only:

- preserve current object separation
- keep faults explicit rather than suppressing them
- keep callback and session linkage data durable so a reconciler can compare them later
- document operator-facing semantics now so later implementation does not drift

No callback architecture redesign is introduced here.

## 9. Non-Goals

Still out of scope for this stage:

- detached async callback implementation
- provider config orchestration
- hidden auto-healing that fabricates worker intent
- turning board-only state into authority

## 10. Acceptance Criteria for the Future Implementation

The eventual reconciliation layer should be considered complete only when:

- task/job/session/callback authority remains distinct and explainable
- worker crash scenarios produce explicit reconcile records instead of ambiguous missing state
- callback missing/duplicate/late-arrival cases are durably inspectable
- CLI and board show the same reconciliation facts
- repair operations are durable, auditable, and explicit
