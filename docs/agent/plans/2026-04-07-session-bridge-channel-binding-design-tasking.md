# Session Bridge And Channel Binding Design Tasking

**Date:** 2026-04-07  
**Audience:** Sidecar design agent  
**Mode:** Design/documentation only  
**Goal:** Design the future session-native communication bridge and optional channel/thread binding model without blocking the current mainline implementation

## 1. Why This Exists

The project now has a strong durable runtime direction:

- callback closure
- fault provenance
- operator board
- durable truth

What remains under-designed is the live communication layer:

- OpenClaw-native session-to-session messaging
- leader/worker acceleration paths
- optional Discord/channel/thread bindings
- how these fit without becoming the source of truth

This task exists to design that layer properly before implementation.

## 2. Required Reading

Read these first:

1. [OpenClaw Native Failure Reporting Integration Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-openclaw-native-failure-reporting-integration-design.md)
2. [External Skill Borrowing Integration Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-07-external-skill-borrowing-integration-design.md)
3. any current OpenClaw/Discord-related docs already present in the repo

## 3. Deliverable

Produce one formal design document.

Recommended output path:

- `docs/design/specs/2026-04-07-session-bridge-and-channel-binding-design.md`

## 4. Core Topics To Design

The document must cover:

### A. Session Bridge Role

Define clearly:

- what the session bridge is for
- what it is not for

It should support:

- low-latency worker -> leader structured notice
- low-latency leader -> main leader structured notice
- optional direct specialist routing

It must not replace:

- durable callback truth
- durable fault truth
- durable task/runtime state

### B. Channel / Thread Binding

Design how a team member may optionally bind to:

- Discord channel
- Discord thread
- other future channel identity

Describe:

- durable metadata fields
- routing rules
- lifecycle of bindings
- how operator surfaces should display them

### C. Identity Split

Must explicitly separate:

- human-facing nickname/display name
- machine-facing member/session identity

### D. Authority vs Acceleration

The document must explicitly distinguish:

- durable authority
- session acceleration
- evidence

### E. Failure And Recovery Interaction

Describe how the session bridge should interact with:

- hook faults
- watchdog faults
- callback reporting
- missing/failed session delivery

## 5. Required Questions

The design must explicitly answer:

1. When should a live session message be sent?
2. What durable write must accompany or follow it?
3. What happens if the live message fails but durable write succeeds?
4. What happens if the live message succeeds but durable write fails?
5. How should channel/thread-bound specialists be represented on board/CLI?
6. How should stable session routing keys relate to reusable team profiles?

## 6. Constraints

- do not implement code in this task
- do not let session bridge become authority
- do not let nickname become routing authority
- do not design a system that depends on Discord or live channels for correctness

## 7. Reporting Format

When done, report:

1. document path
2. bridge role summary
3. channel/thread binding model summary
4. authority vs acceleration model
5. most important implementation warning

## 8. Direct Instruction To Agent

```text
Read:
1. docs/agent/plans/2026-04-07-session-bridge-channel-binding-design-tasking.md

Then produce:
- one formal session bridge and channel binding design document

Do not implement code.

Focus on:
- OpenClaw-native session messaging as acceleration only
- durable state as authority
- channel/thread binding metadata and routing
- failure/recovery interaction

Report:
1. document path
2. bridge role summary
3. channel/thread binding model summary
4. authority vs acceleration model
5. most important implementation warning
```
