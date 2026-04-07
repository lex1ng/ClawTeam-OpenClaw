# End-to-End Test Design Tasking

**Date:** 2026-04-07  
**Audience:** Sidecar design agent  
**Mode:** Design/documentation only unless explicitly expanded later  
**Goal:** Produce a serious end-to-end test design for the ClawTeam-OpenClaw closed-loop runtime without blocking ongoing implementation

## 1. Why This Exists

The project already has:

- unit tests
- integration tests
- smoke tests
- board/operator tests

That is good, but it is not the same as end-to-end validation of the intended multi-level runtime.

The missing layer is business-level E2E:

- fixed reusable team
- worker execution
- worker callback
- team aggregation
- team callback upward
- hook/watchdog/self-report fault propagation
- operator visibility across CLI/board/JSON

This task is to design that layer cleanly before more code is written.

## 2. Required Reading

Read these first:

1. [Multi-Level Task Callback System Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-multi-level-task-callback-system-design.md)
2. [OpenClaw Lifecycle Hook Bridge Tasking](/root/github.com/ClawTeam-OpenClaw/docs/agent/plans/2026-04-07-openclaw-lifecycle-hook-bridge-tasking.md)
3. [Callback Operator Board Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-07-callback-operator-board-design.md)
4. [External Skill Borrowing Integration Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-07-external-skill-borrowing-integration-design.md)
5. Current smoke-related docs already in `docs/agent/plans/`

## 3. Deliverable

Produce one formal design document that answers:

1. what E2E means for this project
2. which runtime layers must be covered
3. which scenarios are mandatory
4. which scenarios can be deferred
5. what the test harness strategy should be
6. what observable assertions define success/failure

Recommended output path:

- `docs/design/specs/2026-04-07-e2e-validation-design.md`

## 4. Scope

The design must cover at least these E2E categories.

### A. Healthy Full Chain

```text
main leader
  -> team leader
  -> worker
  -> coding runtime
  -> worker callback
  -> team callback
  -> main leader visibility
```

### B. Worker Failure Captured By Hook Path

```text
worker crash / abnormal end
  -> lifecycle hook bridge
  -> durable fault
  -> leader visibility
  -> upward visibility
```

### C. Worker Alive But Silent

```text
worker alive
  -> no progress
  -> watchdog
  -> durable fault
```

### D. Fixed Team Reuse

```text
product team profile
  -> team run 1
  -> team run 2
  -> same nickname/role/session metadata persists
```

### E. Strong Handoff / Lifecycle

```text
worker result
  -> structured handoff
  -> team review/aggregation
  -> callback closure
```

## 5. Design Questions You Must Answer

The document must explicitly answer:

1. What counts as a “true E2E” test in this system?
2. Which tests may use fake providers and still count as E2E?
3. Which tests require real OpenClaw path coverage?
4. Which tests require hook fault injection?
5. Which assertions must be made only from durable state?
6. Which assertions may use tmux/session evidence as supplemental evidence only?

## 6. Constraints

- do not write implementation code in this task
- do not broaden into provider config orchestration
- do not assume browser E2E is required for every scenario
- keep durable state as source of truth in test assertions
- explicitly separate:
  - authority assertions
  - evidence assertions

## 7. Reporting Format

When done, report:

1. document path
2. E2E scenario categories
3. required harness approach
4. biggest uncovered risk after this design

## 8. Direct Instruction To Agent

```text
Read:
1. docs/agent/plans/2026-04-07-e2e-test-design-tasking.md

Then produce:
- one formal E2E validation design document

Do not implement code.

Focus on:
- what must be validated end-to-end
- how to validate it without weakening source-of-truth rules
- what should be considered mandatory vs deferred

Report:
1. document path
2. E2E scenario categories
3. required harness approach
4. biggest uncovered risk after this design
```
