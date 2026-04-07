# Callback Operator Board Design

**Date:** 2026-04-07  
**Repository:** ClawTeam-OpenClaw  
**Status:** Proposed design  
**Audience:** Product/design/implementation owners for the next board upgrade  
**Primary Goal:** Turn the current Web board from a generic runtime console into a professional callback/fault/evidence operator surface for persistent OpenClaw-backed teams

## 1. Executive Summary

The current board already exposes durable runtime data:

- workers
- tasks
- coding jobs
- provider sessions
- callback reports
- runtime faults
- timeline
- artifacts
- message history

That is a good base, but it is not enough for the target system.

The target system is not just:

- team creation
- worker spawning
- durable job persistence

It is a closed-loop orchestration runtime:

- user
- main leader / orchestrator
- team leader
- worker
- coding agent
- runtime observer / hook bridge

The board must evolve to make that loop visible and diagnosable.

Without that, callback remains partially opaque, failure still depends too much on tmux inspection, and operators still cannot reliably answer where the chain is blocked.

This design upgrades the board into a **Callback Operator Board** with three first-class concerns:

1. callback chain visibility
2. fault/escalation visibility
3. bounded evidence visibility for tmux/session output and history

## 2. Problem Statement

The system now needs to answer these questions quickly and honestly:

1. Is the team merely alive, or actually progressing?
2. Which worker is waiting on coding runtime, callback, or leader aggregation?
3. Has a worker reported upward formally, or only emitted prose?
4. Has team leader reported upward to main leader formally?
5. Did a failure come from self-report, OpenClaw lifecycle hooks, or watchdog synthesis?
6. Which layer is blocked right now?
7. Can the operator inspect the last useful evidence without opening tmux?
8. Can the operator inspect historical evidence after the tmux pane is already gone?

The current board does not yet answer all of these at a professional level.

## 3. Design Goal

Upgrade the board so that callback is no longer a black box and runtime failure is no longer tmux-only knowledge.

The board must:

- show callback flow across levels
- show hook-derived failures as first-class events
- distinguish `alive`, `healthy`, `progressing`, `blocked`, and `faulted`
- surface worker/team/main-leader closure state
- provide bounded evidence views for session/pane output
- keep durable state as authority

## 4. Non-Negotiable Principles

### 4.1 Durable State Remains Authority

The board must remain a view over persisted truth.

Authority comes from:

- task state
- callback records
- runtime-console fault records
- timeline events
- coding jobs/results/events/artifacts
- contract artifacts such as `MISSION.md`, `TEAM_SPEC.md`, `WORKER_SPEC.md`, `RESULT.md`, `STATUS.json`

The board must not infer completion from:

- prose in tmux panes
- raw session text
- shell output alone

### 4.2 Evidence Is Not Authority

tmux pane output, OpenClaw session output, and transcript excerpts are useful evidence.

They are not source-of-truth state.

The board must label them clearly as:

- `Live Evidence`
- `Snapshot Evidence`
- `Session Excerpt`

and never as final business truth.

### 4.3 Multi-Level Callback Must Be Visible Explicitly

The board must show separate states for:

- worker -> team leader callback
- team leader -> main leader callback

It must not collapse them into one generic `reported` label.

### 4.4 Fault Provenance Must Be Visible

The board must show where fault knowledge came from:

- self-report
- OpenClaw lifecycle hook bridge
- watchdog
- data read fault

### 4.5 `alive=true` Must Not Mislead

The board must explicitly distinguish:

- process alive
- runtime healthy
- making progress
- awaiting callback
- stalled
- faulted

## 5. Architecture View

The board sits on top of the full runtime chain:

```text
[User]
   |
   v
[Main Leader / Orchestrator]
   |
   v
[Team Leader]
   |
   +-------------------+-------------------+
   |                   |                   |
   v                   v                   v
[Worker A]         [Worker B]         [Worker C]
   |                   |                   |
   v                   v                   v
[Coding Runtime]   [Coding Runtime]   [Coding Runtime]
 Claude/Codex/      Claude/Codex/      Claude/Codex/
 OpenClaw exec      OpenClaw exec      OpenClaw exec

Parallel observer path:

[OpenClaw lifecycle/hooks] ---> [Hook Bridge / Runtime Observer]
                                      |
                                      v
                    [Durable faults / timeline / escalation visibility]
                                      |
                                      v
                                [Operator Board]
```

The board does not sit in the execution path.

It sits on the observation path.

## 6. Required Board Outcome Model

The board must present three top-level outcome layers.

### 6.1 Contract Layer

Shows what should happen.

Objects:

- mission
- team spec
- worker spec
- output contract
- execution policy

### 6.2 Execution Layer

Shows what is happening.

Objects:

- worker runtime state
- task state
- coding jobs
- provider sessions
- callback state
- aggregation state

### 6.3 Fault Layer

Shows what is broken or uncertain.

Objects:

- runtime faults
- task read faults
- coding read faults
- callback missing/pending
- hook-derived abnormal end
- watchdog no-progress

## 7. Primary Screens and Panels

### 7.1 Team Overview Header

Must show:

- team name
- team leader
- main leader/orchestrator identity if known
- created time
- active mission/spec refs
- team health summary

Example:

```text
+--------------------------------------------------------------------------------------------------+
| Team: oc-discord-research-v2   Leader: team-leader   Main: orchestrator   Team State: degraded  |
+--------------------------------------------------------------------------------------------------+
| Workers: 4   Tasks: 5   Active Jobs: 2   Callback Pending: 1   Faults: 1   Timeline Events: 27 |
+--------------------------------------------------------------------------------------------------+
```

### 7.2 Callback Flow Panel

This is the most important new panel.

It must visualize:

- worker callback status
- team callback status
- missing callback states
- callback provenance

Example:

```text
+--------------------------------------------------------------------------------------------------+
| Callback Flow                                                                                    |
+--------------------------------------------------------------------------------------------------+
| worker-docs       -> team-leader   reported            result=RESULT.md  status=STATUS.json      |
| worker-multiagent -> team-leader   blocked             source=hook_fault reason=session_end       |
| worker-backend    -> team-leader   pending             waiting=callback_report                    |
|--------------------------------------------------------------------------------------------------|
| team-leader       -> main-leader   waiting_aggregate   workers_done=2/3  workers_faulted=1       |
+--------------------------------------------------------------------------------------------------+
```

Required states:

- `not_started`
- `in_progress`
- `reported`
- `pending`
- `blocked`
- `escalated`
- `waiting_aggregate`
- `reported_upward`
- `faulted`

### 7.3 Worker Runtime Table

Must show one row per worker.

Required fields:

- worker name
- role
- process alive
- runtime health
- current task
- current coding job
- current provider session
- callback status
- latest event
- fault badge if any

Example:

```text
+--------------------------------------------------------------------------------------------------+
| Workers                                                                                          |
+--------------------------------------------------------------------------------------------------+
| worker         role        alive   health     task      job       session    callback    latest  |
| docs           researcher  yes     running    task-1    job-7     sess-44    pending     started |
| multiagent     analyst     yes     faulted    task-2    none      sess-45    blocked     error   |
| backend        coder       yes     completed  task-3    job-8     sess-46    reported    callback|
+--------------------------------------------------------------------------------------------------+
```

### 7.4 Faults and Escalations Panel

Must show:

- runtime faults
- fault provenance
- whether upward notification happened
- whether the fault is acknowledged or still active

Required grouping:

- hook faults
- watchdog faults
- self-reported faults
- read faults

### 7.5 Timeline Panel

Must remain a first-class panel.

But now it must highlight callback/fault transitions, not just generic activity.

Priority event types:

- `worker_bootstrap_failed`
- `worker_runtime_crashed`
- `worker_session_ended_early`
- `callback_reported`
- `callback_escalated`
- `team_callback_reported`
- `leader_runtime_crashed`
- `watchdog_no_progress`
- `aggregation_waiting`

### 7.6 Detail Drawer

Selecting an object should open a detail drawer with object-aware tabs.

Required detail types:

- worker
- task
- coding job
- provider session
- callback
- fault
- timeline event

Required drawer tabs:

- `Summary`
- `Links`
- `Status`
- `Artifacts`
- `Evidence`
- `Related Timeline`

## 8. Evidence Model

Evidence is a new board concern and must be explicitly bounded.

### 8.1 Evidence Types

Support these evidence types:

- `tmux_live_tail`
- `tmux_snapshot`
- `openclaw_session_excerpt`
- `coding_artifact_preview`
- `hook_payload_excerpt`

### 8.2 Live Evidence

Live evidence is for current operator observation.

Examples:

- latest 50-200 lines of tmux pane output
- latest known OpenClaw session excerpt

Rules:

- always label as live evidence
- show last updated timestamp
- show truncation indicator
- never treat as state authority

### 8.3 Snapshot Evidence

The system should persist bounded snapshots at meaningful moments.

Recommended triggers:

- worker spawned
- first task claim attempt
- coding runtime started
- callback reported
- hook error/end/session_end
- worker exit
- team leader exit

Minimum stored fields:

- team name
- worker or leader name
- session id if known
- tmux target if known
- evidence type
- captured at
- bounded text excerpt
- truncation/redaction metadata

### 8.4 History Retrieval

The board should support historical evidence retrieval through durable records.

That means operators can inspect:

- latest evidence
- evidence associated with a fault
- evidence associated with a callback
- evidence associated with a particular session

even after the original tmux pane is gone.

## 9. History Model

The board should expose history through four distinct lenses.

### 9.1 Runtime Timeline History

Derived from durable timeline events.

### 9.2 Callback History

Chronological worker/team callback records.

### 9.3 Fault History

Chronological fault emergence, acknowledgement, escalation, and recovery.

### 9.4 Evidence History

Chronological evidence snapshots linked to session/task/job/fault ids where possible.

## 10. API Additions

The existing board API is a solid base, but the callback operator board needs additional endpoints or expanded payloads.

Recommended additions:

- `GET /api/teams/:team/callback-chain`
- `GET /api/teams/:team/escalations`
- `GET /api/teams/:team/evidence`
- `GET /api/teams/:team/evidence/:evidenceId`
- `GET /api/teams/:team/workers/:worker/evidence`
- `GET /api/teams/:team/workers/:worker/callbacks`
- `GET /api/teams/:team/workers/:worker/faults`

Recommended expansions:

- team payload should include main-leader/team-leader linkage when known
- worker payload should include `health`, `progressState`, `faultState`, `callbackState`
- callback payload should include level and upward target
- fault payload should include provenance and notification state

## 11. Health Semantics

The board must compute and show health semantics explicitly.

### 11.1 Process State

- `alive`
- `ended`

### 11.2 Runtime State

- `healthy`
- `degraded`
- `faulted`
- `stalled`

### 11.3 Progress State

- `idle`
- `claiming`
- `executing`
- `waiting_callback`
- `aggregating`
- `reported`
- `blocked`

The UI must not use only one badge for all of these.

## 12. Multi-Scenario Visualization Requirements

The board must clearly support these scenarios.

### 12.1 Full Chain Healthy

```text
User -> Main Leader -> Team Leader -> Worker -> Coding Agent -> Worker Callback -> Team Callback -> Main Leader
```

Expected board view:

- worker jobs visible
- callbacks visible
- team callback visible
- no active faults
- timeline confirms normal transitions

### 12.2 Worker Fails But Self-Reports

```text
Worker -> self-report callback/inbox -> Team Leader -> Main Leader
```

Expected board view:

- failure visible as worker-level blocked/escalated callback
- provenance = self-report
- upward handling state visible

### 12.3 Worker Crashes Before Self-Report

```text
Worker X
  -> OpenClaw error/end/session_end
  -> Hook Bridge
  -> Durable Fault
  -> Team Leader Visible
  -> Main Leader Visible if escalated
```

Expected board view:

- worker row shows `alive` and `health` separately
- callback shown as absent/blocked
- fault provenance = hook bridge
- evidence tab shows last bounded pane/session excerpt if available

### 12.4 Worker Alive But Silent

```text
Worker alive
  -> no progress
  -> watchdog
  -> durable fault
```

Expected board view:

- worker `alive=yes`
- health `stalled`
- fault provenance = watchdog

### 12.5 Team Leader Fails After Worker Completion

```text
Workers done
  -> Team Leader crashes before upward callback
  -> hook bridge / watchdog
  -> main leader sees team callback missing + leader fault
```

Expected board view:

- worker callbacks present
- team callback absent
- leader fault prominent
- team shown as `aggregation_blocked`

## 13. Security and Reliability Constraints

### 13.1 No Unbounded Transcript Dumps

Do not dump entire tmux/session history into the board.

Everything must be:

- bounded
- truncatable
- optionally redactable

### 13.2 UI Must Survive Partial Corruption

If one task/session/evidence record is unreadable:

- show explicit read fault
- do not silently hide it
- do not mark the team healthy

### 13.3 History Must Not Depend on tmux Still Existing

If tmux is already closed, the board should still show:

- durable callback history
- durable fault history
- durable evidence snapshots that were persisted earlier

## 14. Suggested Visual Layout

Recommended top-to-bottom layout:

```text
+--------------------------------------------------------------------------------------------------+
| Header: Team identity / leader chain / health summary                                            |
+--------------------------------------------------------------------------------------------------+
| Callback Flow | Runtime Health | Fault Summary | Progress Summary                                |
+--------------------------------------------------------------------------------------------------+
| Worker Table                                                                                        |
+--------------------------------------------------------------------------------------------------+
| Tasks / Jobs / Sessions                                                                            |
+--------------------------------------------------------------------------------------------------+
| Timeline                                                                                            |
+--------------------------------------------------------------------------------------------------+
| Detail Drawer: Summary | Status | Artifacts | Evidence | Related Timeline                        |
+--------------------------------------------------------------------------------------------------+
```

## 15. CLI Alignment Requirements

This board upgrade must stay aligned with CLI.

CLI and board should produce the same conclusions for:

- callback status
- fault provenance
- worker health
- team aggregation status
- evidence availability

If a state exists only in UI and not in CLI JSON, the design is incomplete.

## 16. Recommended Delivery Order

Implement in this order:

1. callback chain data model and API
2. health/progress/fault semantics on worker rows
3. fault provenance and escalation visibility
4. detail drawer support for callback/fault drill-down
5. evidence snapshot model and history API
6. optional live tail panel

The live tail panel is useful, but not before callback/fault semantics are correct.

## 17. Final Design Judgment

Yes, the board must be updated.

Not because the existing board is wrong, but because the system has graduated from:

- runtime visibility

to:

- closed-loop callback orchestration

The board has to graduate with it.
