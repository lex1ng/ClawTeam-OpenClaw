# Runtime Test Matrix Tasking

**Date:** 2026-04-07  
**Audience:** Sidecar design agent  
**Mode:** Design/documentation only  
**Goal:** Build a unified test matrix and acceptance plan for the current project so the team can see what is already covered and what remains missing

## 1. Why This Exists

The project now has many test layers spread across files and design rounds.

That is useful, but hard to reason about at a glance.

The team needs one authoritative test matrix that explains:

- what exists
- what each suite proves
- which scenarios are duplicated
- which critical scenarios are missing
- which tests are source-of-truth tests vs convenience/UI tests

## 2. Required Reading

Read these first:

1. existing `tests/` layout
2. smoke docs in `docs/agent/plans/`
3. callback/runtime/board related specs in `docs/design/specs/`
4. latest review docs in `docs/agent/reviews/`

## 3. Deliverable

Produce one formal matrix document.

Recommended output path:

- `docs/design/specs/2026-04-07-runtime-test-matrix-and-acceptance-plan.md`

## 4. Matrix Dimensions

The matrix must cover at least these dimensions.

### Test Level

- unit
- integration
- smoke
- operator surface
- end-to-end planned

### Functional Area

- team/task persistence
- spawn/workspace
- coding runtime
- callback runtime
- runtime-console
- board/API/CLI
- hook/watchdog fault path
- fixed reusable team identity
- handoff/lifecycle contracts
- session routing metadata

### Truth Model

- durable state authority
- evidence only
- UI rendering only

### Readiness

- covered
- partially covered
- planned
- missing

## 5. Required Questions

The matrix must explicitly answer:

1. which existing tests already protect current behavior
2. which high-risk areas are still under-tested
3. which future changes should trigger regression runs
4. what the acceptance baseline should be before claiming the runtime is “ready”

## 6. Constraints

- do not write code in this task
- do not silently infer coverage; cite actual test files
- separate hard guarantees from soft confidence
- call out where current tests rely on fake providers/harnesses

## 7. Reporting Format

When done, report:

1. document path
2. matrix structure
3. highest-risk gaps
4. recommended acceptance baseline

## 8. Direct Instruction To Agent

```text
Read:
1. docs/agent/plans/2026-04-07-runtime-test-matrix-tasking.md

Then produce:
- one formal runtime test matrix and acceptance plan document

Do not implement tests.

Your job is to map:
- current coverage
- missing coverage
- acceptance criteria
- recommended regression suites

Report:
1. document path
2. matrix structure
3. highest-risk gaps
4. recommended acceptance baseline
```
