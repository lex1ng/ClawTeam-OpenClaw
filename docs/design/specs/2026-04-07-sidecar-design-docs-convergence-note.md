# Sidecar Design Docs Convergence Note

**Date:** 2026-04-07  
**Repository:** ClawTeam-OpenClaw  
**Status:** Active reference note  
**Purpose:** Preserve the value of the three sidecar design outputs without collapsing them into one oversized document

## 1. Decision

Do **not** merge the three sidecar design documents into a single monolithic spec.

Keep them separate, because they answer different classes of questions:

1. what the future end-to-end runtime must prove
2. what the current test and acceptance baseline really covers
3. how future session-native transport and channel binding should work without corrupting authority

Instead of merging them, this note serves as the convergence layer:

- it records why the three docs exist
- it defines how they should be used
- it defines when each one becomes implementation-driving
- it prevents future agents from treating them as abandoned side notes

## 2. Canonical Sidecar Documents

### 2.1 E2E Validation Design

Document:

- `docs/design/specs/2026-04-07-e2e-validation-design.md`

Primary purpose:

- define what counts as a true closed-loop end-to-end test in this repository

Use this document when:

- building mandatory E2E suites
- deciding whether a smoke test is sufficient
- validating upward callback closure
- validating hook/watchdog fault visibility
- validating fixed-team reuse as runtime behavior instead of only metadata behavior

What it is not:

- not a current-state coverage inventory
- not a transport design

### 2.2 Runtime Test Matrix And Acceptance Plan

Document:

- `docs/design/specs/2026-04-07-runtime-test-matrix-and-acceptance-plan.md`

Primary purpose:

- define the current protection level of the repository and the acceptance bar for release/readiness claims

Use this document when:

- reviewing test adequacy
- deciding whether a change can be called production-ready
- selecting regression suites after callback/runtime/board/spawn changes
- separating hard guarantees from soft confidence

What it is not:

- not a future-state architecture spec
- not a runtime transport design

### 2.3 Session Bridge And Channel Binding Design

Document:

- `docs/design/specs/2026-04-07-session-bridge-and-channel-binding-design.md`

Primary purpose:

- define future live session transport and optional channel/thread binding without allowing transport to become authority

Use this document when:

- implementing real session-native delivery
- adding Discord/thread/channel binding
- defining bridge notices and delivery evidence
- reviewing whether a live-transport feature violates durable-state authority

What it is not:

- not a replacement for callback/fault/task truth
- not an excuse to route by nickname

## 3. Why These Documents Must Stay Separate

These three outputs should remain separate because they sit at different control levels:

```text
acceptance / proof layer
  -> e2e-validation-design

current readiness / regression layer
  -> runtime-test-matrix-and-acceptance-plan

future transport / routing layer
  -> session-bridge-and-channel-binding-design
```

If they are merged:

- acceptance rules become mixed with implementation ideas
- current-state coverage becomes confused with future-state architecture
- transport acceleration details become harder to review against authority boundaries

That would slow later work down and make design drift more likely.

## 4. Current Value To Ongoing Development

These documents are still useful after the current main-agent implementation lands.

### 4.1 Immediate usefulness

Right now they help with:

1. preventing over-claims about readiness
2. defining what remains unproven after current smoke/integration coverage
3. keeping session bridge work from leaking into authoritative callback/task/fault semantics

### 4.2 Near-term usefulness

They directly inform the next likely milestones:

1. lifecycle hook bridge implementation and tests
2. worker -> team leader -> main leader upward callback closure
3. fixed reusable team smoke/E2E coverage
4. stronger handoff/lifecycle enforcement

### 4.3 Medium-term usefulness

They become implementation-driving again when the project starts:

1. real OpenClaw session-native bridge delivery
2. Discord channel/thread binding
3. reusable fixed product teams with durable session reuse semantics

## 5. How Future Agents Should Use Them

### 5.1 For implementation agents

Implementation agents should:

1. use the current main feature spec and review docs for the code they are actively changing
2. consult the runtime test matrix before making readiness claims
3. consult the E2E validation design before introducing a new test that claims full-chain proof
4. consult the session bridge design before implementing live session transport or channel binding

### 5.2 For review agents

Review agents should use these docs to challenge three common failure modes:

1. claiming smoke == E2E
2. claiming metadata exposure == operational reuse proof
3. allowing live session transport to mutate authority

### 5.3 For operator-facing planning

Operators and planners should read:

1. the runtime test matrix to understand what is currently trustworthy
2. the E2E design to understand what still must be proven
3. the session bridge design to understand what future live messaging may and may not do

## 6. Recommended Activation Order

These documents should influence future work in this order:

1. `runtime-test-matrix-and-acceptance-plan`
   - first, because it defines what is currently covered and what is still risky
2. `e2e-validation-design`
   - second, when turning the remaining gaps into true runtime validation
3. `session-bridge-and-channel-binding-design`
   - third, when the core callback/fault/lifecycle chain is already solid enough to support live transport acceleration

Reason:

- first stabilize truth and acceptance
- then prove the truth end to end
- only then add faster live transport around that truth

## 7. Current Recommendation

As of this note:

1. keep all three documents
2. do not merge them
3. treat them as active reference documents
4. close the three sidecar agents that produced them
5. continue active engineering on the main agent path

The current main-agent implementation still has concrete code issues to fix in identity precision and session linkage. Those fixes are higher priority than any additional work on these sidecar design tracks.

## 8. Practical Closeout

When closing the three sidecar agents, record them as:

1. completed design research
2. no further code action required in this phase
3. documents retained as active references for later phases

That is the correct stopping point for them in the current project phase.
