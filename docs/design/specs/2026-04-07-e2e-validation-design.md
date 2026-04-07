# End-to-End Validation Design

**Date:** 2026-04-07  
**Status:** Proposed design  
**Repository:** ClawTeam-OpenClaw  
**Scope:** Define the end-to-end validation layer for the closed-loop ClawTeam-OpenClaw runtime

## 1. Executive Summary

This project already has meaningful unit, integration, smoke, and operator-surface coverage.

That is necessary, but it is not the same as business-level end-to-end validation.

For this project, a true E2E test must validate the full closed loop:

```text
user intent
  -> main leader/orchestrator
  -> team leader
  -> worker
  -> OpenClaw-backed runtime
  -> coding-runtime result
  -> worker callback
  -> team aggregation
  -> team callback upward
  -> durable operator visibility
```

The defining rule is:

- durable state is the source of truth
- tmux/session output is evidence only

This document defines:

1. what counts as E2E in this repository
2. which runtime layers must be covered
3. which scenarios are mandatory now
4. which scenarios should be deferred
5. which harness strategy should be used
6. which assertions define success and failure

## 2. What Counts As “True E2E” In This System

### 2.1 System Boundary

The E2E boundary should include all project-owned runtime behavior:

1. team/task/identity creation
2. team leader dispatch behavior
3. worker execution path
4. OpenClaw launch/delivery path used by this fork
5. coding job persistence and callback handling
6. worker -> leader callback closure
7. leader -> main leader callback closure
8. runtime fault/watchdog visibility
9. CLI/JSON/board visibility over durable state

The external LLM provider itself is outside the project boundary.

That means the system can still be tested end to end when the provider process is replaced with a deterministic fake, as long as the project-owned runtime chain remains real.

### 2.2 What Does Not Count As E2E

The following do not count as true E2E by themselves:

- unit tests of callback/fault helpers
- integration tests that bypass `clawteam` CLI entry points
- standalone smoke that stops at worker completion without team-level upward closure
- tests that fake durable callback persistence directly instead of causing the runtime to write it
- board-only tests that validate rendering but not runtime closure
- tests that treat tmux output as the pass/fail source of truth

### 2.3 What Does Count As E2E

A test counts as E2E when all of the following are true:

1. it exercises the real project-owned runtime path from orchestration down to durable callback/fault state
2. it crosses the actual layer boundaries between leader, worker, runtime, and observer surfaces
3. it verifies outcome from durable artifacts and durable APIs
4. it proves upward closure or upward fault visibility, not only local worker progress

## 3. Runtime Layers That Must Be Covered

The E2E layer must cover these runtime layers explicitly.

### 3.1 Mission / Main Leader Layer

Must validate:

- mission acceptance or equivalent top-level invocation
- team creation or team reuse decision
- waiting for team-level callback or escalation
- top-level visibility of final success/failure

### 3.2 Team Leader Layer

Must validate:

- worker dispatch
- worker callback intake
- aggregation/review behavior
- team-level result production
- upward callback to main leader

### 3.3 Worker Layer

Must validate:

- task claim and progress
- execution policy handling
- coding-runtime usage when required
- result synthesis
- structured callback to leader

### 3.4 OpenClaw Runtime Layer

Must validate:

- actual `clawteam spawn` default OpenClaw path
- session delivery semantics
- runtime startup or abnormal end behavior
- session identity binding sufficient for callback/fault attribution

### 3.5 Coding Runtime Layer

Must validate:

- job creation
- result persistence
- worker-side classification of result
- callback/handoff linkage into worker output

### 3.6 Runtime Observer Layer

Must validate:

- lifecycle-hook-derived failure capture
- watchdog-derived no-progress capture
- durable fault persistence
- fault provenance visibility

### 3.7 Operator Surface Layer

Must validate:

- CLI/JSON truth surfaces
- board/API visibility over the same durable truth
- separation between authority and evidence

## 4. Truth Model For E2E Assertions

### 4.1 Authority Assertions

These are allowed to decide test pass/fail.

Authority surfaces are:

- `STATUS.json` artifacts
- worker/team/main callback records
- runtime fault records
- timeline events written to durable state
- coding jobs/results/events/artifacts
- task and team records
- board/API JSON derived from those persisted records
- CLI `--json` output derived from those persisted records

### 4.2 Evidence Assertions

These may support diagnosis, but must not be the primary pass/fail basis.

Evidence surfaces are:

- tmux pane output
- OpenClaw session excerpts
- captured shell output
- fake-provider stdout
- fake-runtime launch logs

### 4.3 Required Separation

Every E2E scenario must state two things separately:

1. authority assertions
2. supplemental evidence assertions

A test fails as an E2E test if authority is missing and only evidence exists.

## 5. Fake Providers Versus Real Runtime Coverage

### 5.1 Tests That May Use Fake Providers And Still Count As E2E

These still count as E2E when the provider is replaced with a deterministic fake:

- healthy full-chain callback closure
- strong handoff / lifecycle closure
- fixed team reuse across repeated runs
- worker silent/no-progress watchdog detection
- many worker-fault scenarios after runtime startup

Reason:

- the external model output is not the business system under test
- the orchestration, callback, persistence, fault, and operator surfaces are the business system under test

### 5.2 Tests That Require Real OpenClaw Path Coverage

The following must cover the real project launch path used in production:

- at least one healthy full-chain success scenario
- worker runtime crash / abnormal end captured by lifecycle hooks
- worker alive but silent leading to watchdog fault
- team leader aggregation and upward callback closure
- at least one fixed-team reuse run that executes through the default worker runtime path

A test that bypasses the default OpenClaw worker launch path should be classified as integration or smoke support, not the primary E2E proof.

### 5.3 Tests That Require Hook Fault Injection

The following require explicit hook-path fault exercise:

- worker bootstrap failure
- worker runtime crash after startup
- worker session ended early
- team leader runtime crash or early session end

For these scenarios, the required proof is not merely that the process failed. The required proof is that the hook bridge produced canonical durable fault state with visible provenance.

## 6. Mandatory E2E Scenario Categories

The following scenarios are mandatory for the first serious E2E layer.

### 6.1 E2E-A: Healthy Full Chain

Purpose:

- prove the intended happy path closes end to end

Required flow:

```text
main leader
  -> team leader
  -> worker
  -> OpenClaw runtime
  -> coding runtime
  -> worker callback
  -> team aggregation
  -> team callback upward
  -> CLI/board visibility
```

Required authority assertions:

- worker durable status reaches `reported_to_leader` or equivalent completed-and-reported phase
- worker callback record exists with result references
- leader/team durable status reaches `reported_to_main_leader` or equivalent
- team callback record exists
- main leader visible summary can be derived from durable state
- board/API/CLI JSON all expose the completed chain consistently

Supplemental evidence assertions:

- tmux/session excerpt shows launch occurred
- fake provider log confirms invocation details

### 6.2 E2E-B: Worker Failure Captured By Hook Path

Purpose:

- prove that failure does not rely on self-report from the failing worker

Required flow:

```text
worker crash / abnormal end
  -> lifecycle hook bridge
  -> canonical durable fault
  -> leader-visible failure
  -> upward visibility
```

Required authority assertions:

- canonical fault type is persisted with hook provenance
- worker durable status becomes failed/faulted/degraded, not merely absent
- leader-visible summary reflects worker failure
- team/main layer can observe the failure without tmux inspection
- board/API/CLI surfaces expose the same fault state

Supplemental evidence assertions:

- tmux/session excerpt shows abnormal end text if available
- hook raw payload reference is preserved if safe

### 6.3 E2E-C: Worker Alive But Silent

Purpose:

- prove that `alive=true` is not treated as success or health

Required flow:

```text
worker alive
  -> no task progress / no callback
  -> watchdog timeout
  -> durable fault
  -> leader-visible degradation
```

Required authority assertions:

- watchdog-generated fault is persisted with watchdog provenance
- worker durable status is `no_progress`, `blocked`, or equivalent degraded state
- team state becomes blocked/degraded until resolved
- operator surfaces distinguish alive from healthy/progressing

Supplemental evidence assertions:

- session evidence shows shell/process still alive
- absence of meaningful pane output may be captured for diagnosis only

### 6.4 E2E-D: Fixed Team Reuse

Purpose:

- prove that reusable teams are durable system objects, not disposable prompt sessions

Required flow:

```text
fixed team profile
  -> run 1 completes
  -> run 2 reuses same team identity
  -> stable nickname/role/session metadata remains attributable
```

Required authority assertions:

- team identity persists across runs
- member nicknames and roles remain stable
- reusable team/session metadata remains attributable in durable state
- run 1 and run 2 results are distinguishable without losing stable identity

Supplemental evidence assertions:

- session/window naming continuity may be inspected as evidence only

### 6.5 E2E-E: Strong Handoff / Lifecycle Closure

Purpose:

- prove the runtime closes through structured artifacts rather than prose-only completion

Required flow:

```text
worker result
  -> structured handoff
  -> leader review/aggregation
  -> callback closure
  -> final operator-visible result
```

Required authority assertions:

- worker result artifact exists and is referenced by callback state
- leader/team result artifact exists and is referenced by team callback state
- completion is not accepted until upward callback closure is present
- coding job/result linkage is preserved in worker-level result references

Supplemental evidence assertions:

- human-readable inbox summary may be inspected as supporting evidence

### 6.6 E2E-F: Team Leader Failure After Worker Progress

Purpose:

- prove that the multi-level chain fails honestly when the aggregation layer dies after workers did useful work

Required flow:

```text
worker reports upward
  -> leader crashes or ends early before aggregation completes
  -> hook bridge records leader fault
  -> main leader sees team-level failure/escalation
```

Required authority assertions:

- worker success remains durable and is not erased
- leader fault is persisted with canonical type and provenance
- team does not report false completion
- main leader sees escalation/failure from durable state

Supplemental evidence assertions:

- leader session excerpt may be captured for diagnosis only

## 7. Deferred E2E Scenario Categories

These scenarios are valuable, but should be deferred until the first mandatory E2E layer is stable.

### 7.1 Real External Provider Canary

Defer because:

- provider accounts, quotas, and nondeterminism are outside the core project boundary
- this is better treated as scheduled canary coverage than blocking CI E2E

### 7.2 Browser Rendering E2E

Defer because:

- board JSON/API truth is the required authority layer
- browser automation is useful later, but not necessary for first-pass closed-loop validation

### 7.3 Discord / Channel / Thread Binding End To End

Defer because:

- external routing is orthogonal to proving callback/fault/runtime closure
- it adds transport complexity before core truth semantics are locked

### 7.4 Large-Fanout / High-Concurrency Teams

Defer because:

- first-pass E2E should focus on correctness before scale behavior
- concurrency/soak should come after mandatory single-team closure is trusted

### 7.5 Restart / Resume / Host-Reboot Recovery

Defer because:

- this is closer to resilience and reconciliation work than first E2E correctness

### 7.6 Rare Hook Payload Variants And Duplicate Delivery At E2E Level

Defer because:

- duplicate delivery and malformed optional fields are better protected primarily by integration tests
- the first E2E layer should prove business closure, not enumerate every payload permutation

## 8. Recommended Harness Strategy

### 8.1 Harness Principles

The harness should be:

- `pytest`-driven
- CLI-first
- isolated from the operator's real environment
- deterministic enough for CI
- durable-state-first in assertions
- self-cleaning on both success and failure

### 8.2 Environment Model

Each E2E run should create an isolated temp root containing at minimum:

- `home/`
- `data/`
- `artifacts/`
- optional isolated repo/workspace roots

Each subprocess should run with explicit environment overrides such as:

- `HOME=<tmp>/home`
- `CLAWTEAM_DATA_DIR=<tmp>/data`
- `PATH=<tmp>/bin:<existing PATH>`

The harness should never depend on the operator's real `~/.clawteam` state.

### 8.3 Execution Model

The E2E harness should use:

- real `clawteam` CLI entry points
- real team/task persistence
- real board/API JSON queries for operator assertions
- real default OpenClaw worker launch path for the scenarios classified above as true E2E
- fake external providers where deterministic provider substitution is acceptable

The harness should not short-circuit the system by writing callback/fault state directly.

### 8.4 Fault Drivers

Use separate deterministic drivers for each failure class:

- controlled worker crash driver for hook-path failure
- controlled silent-worker driver for watchdog failure
- controlled leader crash driver for aggregation-layer failure
- stable reusable-team fixture for run-1/run-2 reuse validation

The driver may intentionally induce failure, but the runtime must still be the component that writes the authoritative fault and callback state.

### 8.5 Operator Assertions

For each scenario, assert from at least two durable surfaces:

1. direct durable artifacts or CLI `--json`
2. board/API JSON

This is required to prove that operator visibility is a view over the same authority, not a separate interpretation.

### 8.6 Evidence Capture

When available, capture the following for failure diagnosis only:

- tmux pane excerpt
- OpenClaw session excerpt
- fake provider invocation log
- raw hook payload reference

The harness should store these as artifacts, but not treat them as authoritative pass criteria.

## 9. Observable Success And Failure Criteria

### 9.1 Global Success Criteria

A scenario is successful only when all scenario-specific authority assertions pass and the final durable state tells a coherent story across layers.

At minimum, coherent means:

- state transitions are attributable to the correct team/role/session
- callback closure or fault closure is present at the correct level
- board/API/CLI agree with persisted truth
- no layer is marked complete when the next required callback or escalation is missing

### 9.2 Global Failure Criteria

A scenario should be treated as failed when any of the following occur:

- a lower layer appears complete but no durable upward callback exists
- runtime failure is visible only in tmux/session text and not in durable state
- board/API contradict CLI/durable artifacts
- `alive=true` is presented as healthy when progress/callback evidence is missing
- a fixed-team reuse run loses stable identity/role attribution
- a fault has no provenance classification

## 10. Scenario Matrix

| ID | Category | Mandatory | Real OpenClaw Path Required | Fake Provider Allowed | Hook Fault Injection Required |
| --- | --- | --- | --- | --- | --- |
| E2E-A | Healthy full chain | Yes | Yes | Yes | No |
| E2E-B | Worker failure via hook path | Yes | Yes | Yes | Yes |
| E2E-C | Worker alive but silent | Yes | Yes | Yes | No |
| E2E-D | Fixed team reuse | Yes | At least one reused run should use it | Yes | No |
| E2E-E | Strong handoff / lifecycle closure | Yes | Yes | Yes | No |
| E2E-F | Team leader failure after worker progress | Yes | Yes | Yes | Yes |
| E2E-G | Real provider canary | Deferred | Yes | No | Optional |
| E2E-H | Browser rendering automation | Deferred | No | Yes | No |
| E2E-I | Discord/thread/channel routing | Deferred | Depends on slice | Depends on slice | Optional |
| E2E-J | High-concurrency / soak | Deferred | Yes | Yes | Optional |

## 11. Biggest Remaining Risk After This Design

The biggest risk still left after this design is not test structure. It is runtime realism at the provider boundary.

Even with a strong deterministic E2E harness, CI-grade tests will still leave one meaningful gap:

- real external provider behavior and upstream OpenClaw/runtime drift can still break the production path without immediately breaking the deterministic fake-provider suite

That risk should be handled later with scheduled non-blocking canary coverage, not by weakening this deterministic durable-state-first E2E design.

## 12. Recommended Adoption Order

1. land the first mandatory healthy full-chain E2E
2. add worker hook-failure and silent-worker watchdog E2E
3. add leader-failure E2E
4. add fixed-team reuse E2E
5. add scheduled non-blocking real-provider canary after the deterministic suite is stable
