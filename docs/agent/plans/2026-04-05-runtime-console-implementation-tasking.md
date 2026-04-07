# Runtime Console Implementation Tasking

**Date:** 2026-04-05
**Repository:** ClawTeam-OpenClaw
**Primary Spec:** [2026-04-05-runtime-console-cli-board-design.md](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-05-runtime-console-cli-board-design.md)
**Audience:** The coding agent implementing the Runtime Console design
**Purpose:** Convert the approved runtime console spec into a concrete execution plan with explicit agent instructions, phase scope, engineering constraints, testing requirements, and reporting expectations.

---

## 1. Read This First

Before writing code, the agent must read and follow these documents in order:

1. [Runtime Console Design for CLI + Web Board](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-05-runtime-console-cli-board-design.md)
2. [Coding Callback Runtime Re-Review](/root/github.com/ClawTeam-OpenClaw/docs/agent/reviews/2026-04-05-coding-callback-runtime-rereview.md)
3. [Coding Runtime Quality Hardening Guide](/root/github.com/ClawTeam-OpenClaw/docs/agent/plans/2026-04-05-coding-runtime-quality-hardening-guide.md)

The design spec is the primary source for scope and object semantics. The re-review and hardening guide define the existing runtime quality bar that must not regress.

---

## 2. Mission

Implement the next-generation ClawTeam Runtime Console across both CLI and Web board so that operators can reliably inspect and reason about:

- tasks
- coding jobs
- agent sessions
- provider sessions
- callback reports
- runtime faults
- timeline/event causality

The final result must feel like a serious operator console, not a superficial UI refresh.

---

## 3. Non-Negotiable Constraints

The agent must follow all of these constraints:

- do not weaken existing one-active-job-per-worker or one-active-job-per-task guarantees
- do not break current coding runtime tests
- do not change cancel semantics beyond current durable-state meaning
- do not invent provider session ids or resume support when the provider does not expose them
- do not hide corruption or schema faults as missing state
- do not let CLI and board use different state names or meanings
- do not expand into provider config orchestration
- do not replace durable state as the source of truth
- do not collapse `task`, `job`, `agent session`, `provider session`, and `callback` into one object
- do not do a UI-only implementation without persistence and API support

If the provider cannot safely support attached session identity, the implementation must explicitly represent `ephemeral` mode.

---

## 4. Required Delivery Strategy

The agent must implement this work in strict phases.

Do not skip ahead to Web UI before the underlying model and CLI are sound.

Implementation order is mandatory:

1. domain model and persistence
2. CLI completion
3. board data / API layer
4. Web board UI
5. polish and hardening

---

## 5. Phase Plan

### Phase 1: Domain Model and Persistence

#### Goal

Introduce the missing runtime objects and relationships so that CLI and board can be built on durable truth.

#### Required Deliverables

- add a persisted `ProviderSessionRecord` model or equivalent first-class provider session model
- add explicit job -> provider session linkage where supported
- add explicit `sessionMode` semantics (`attached` vs `ephemeral`)
- add explicit callback-state fields or equivalent callback view model support
- ensure fault model support is sufficient for session/job/runtime faults
- ensure timeline/event aggregation can represent task/job/session/callback/fault activity

#### Required Engineering Notes

- if provider session identity is unavailable from provider output, persist `sessionMode=ephemeral`
- if resume support is unknown or unsupported, persist it explicitly as unavailable/false
- schema changes must preserve backward-compatibility discipline
- any new persisted object must include schema versioning

#### Acceptance Criteria

- no new console concept depends on ephemeral in-memory state only
- job/session/callback relationships are persisted or durably derivable
- durable truth is sufficient for CLI/board rendering

---

### Phase 2: CLI Completion

#### Goal

Make CLI the complete and reliable operator control surface before the Web board depends on it.

#### Required Deliverables

Implement or complete command groups for:

- coding job inspection
- provider session inspection
- fault inspection
- runtime timeline inspection

Minimum expected commands:

```bash
clawteam coding list --team <team>
clawteam coding status <job-id> --team <team>
clawteam coding result <job-id> --team <team>
clawteam coding events <job-id> --team <team>
clawteam coding artifacts <job-id> --team <team>
clawteam coding artifact <job-id> --name <artifact> --team <team>
clawteam coding session list --team <team>
clawteam coding session show <provider-session-id> --team <team>
clawteam coding session jobs <provider-session-id> --team <team>
clawteam coding session events <provider-session-id> --team <team>
clawteam faults list --team <team>
clawteam faults show <fault-id> --team <team>
clawteam audit timeline --team <team>
```

#### Required Human Output Quality

Human-readable output must surface:

- control flags
- startup policy
- callback state/decision
- provider session identity or explicit absence
- session mode
- attempt lineage
- timestamps
- artifacts
- faults

#### Acceptance Criteria

- an operator can inspect all major runtime objects from CLI alone
- JSON output remains machine-usable and stable
- human output is audit-friendly

---

### Phase 3: Board Data and API Layer

#### Goal

Build a reliable data layer for the board from persisted truth.

#### Required Deliverables

- aggregate runtime console API payload for a team
- object detail APIs for tasks, jobs, provider sessions, faults, and timeline
- board collector logic for workers/tasks/jobs/sessions/callbacks/faults/timeline
- no hidden corruption paths

#### Minimum API Surface

```text
GET /api/board/:team
GET /api/teams/:team/workers
GET /api/teams/:team/tasks
GET /api/teams/:team/coding/jobs
GET /api/teams/:team/coding/jobs/:jobId
GET /api/teams/:team/coding/jobs/:jobId/events
GET /api/teams/:team/coding/jobs/:jobId/result
GET /api/teams/:team/coding/jobs/:jobId/artifacts
GET /api/teams/:team/coding/sessions
GET /api/teams/:team/coding/sessions/:sessionId
GET /api/teams/:team/coding/sessions/:sessionId/jobs
GET /api/teams/:team/callbacks
GET /api/teams/:team/faults
GET /api/teams/:team/timeline
```

#### Acceptance Criteria

- board JSON can fully represent the runtime console model
- faults are explicit
- unknown provider session fields remain explicit
- aggregate and detail APIs are consistent with CLI JSON

---

### Phase 4: Web Board UI

#### Goal

Implement the runtime console board as a serious operator surface.

#### Required Deliverables

- global health header
- workers panel
- tasks panel
- coding runtime panel with provider sessions and coding jobs split apart
- event timeline
- right-side detail drawer with object-aware tabs

#### UI Requirements

The board must support drill-down for:

- task
- worker
- job
- provider session
- fault

The board must explicitly show:

- fault counts
- callback-pending states
- provider session states
- session mode
- stale conditions
- unknown / unavailable fields honestly

#### Acceptance Criteria

- operator can navigate from task -> job -> provider session -> callback -> artifacts
- board does not visually collapse sessions and jobs into one concept
- board presents a coherent runtime console, not a set of disconnected cards

---

### Phase 5: Polish and Hardening

#### Goal

Close usability and resilience gaps after the main console is functionally complete.

#### Required Deliverables

- stale session highlighting
- stronger filtering/search for timeline and lists
- fault badges and detail improvements
- artifact preview polish
- consistent unknown/empty/error state rendering
- consistency between Rich board and Web board where applicable

#### Acceptance Criteria

- console remains trustworthy under degraded conditions
- Web board does not hide important runtime conditions that CLI exposes

---

## 6. Testing Requirements

The implementation is incomplete unless the following are covered.

### Domain / Model Tests

- provider session model validation
- schema versioning for new persisted models
- session mode semantics
- job/session linking rules
- callback-state semantics

### CLI Tests

- session list/show commands
- fault list/show commands
- timeline commands
- JSON contract tests
- human-readable output tests for control flags, session state, callback state

### Board Data Tests

- aggregate payload includes sessions/jobs/tasks/callbacks/faults/timeline
- fault preservation in JSON output
- unknown provider session fields remain explicit
- no corruption swallowing

### UI / Integration Tests

- board renders provider sessions
- board renders job/session distinction clearly
- board renders faults and stale states
- board detail drill-down returns correct object data
- board does not misrepresent unavailable session identity

### Regression Tests

- all current coding runtime tests remain green
- current board collector tests remain green
- current CLI coding status regression tests remain green
- atomic create guarantees remain protected

---

## 7. Implementation Guidance

### 7.1 How To Think About This Work

This is platform work.

Do not approach it as:

- a UI refactor
- a prettier dashboard
- a loose collection of helper commands

Approach it as:

- runtime object modeling
- operator surface design
- durable-state observability
- control-plane consistency

### 7.2 What To Prioritize

Prioritize in this order:

1. correctness of object semantics
2. durability and truthfulness of persisted state
3. CLI completeness and auditability
4. board data/API correctness
5. board UI clarity and drill-down
6. cosmetic polish

### 7.3 How To Handle Provider Session Uncertainty

If Claude/Codex provider session metadata is not reliably available:

- do not block the whole feature
- implement `ephemeral` session mode
- explicitly mark session id as unavailable
- keep the object model honest
- design the console to evolve later when more provider metadata becomes available

---

## 8. Required Progress Reporting

When the agent reports progress, each update must include:

- which phase is in progress
- which files were changed
- what contracts/models were introduced or modified
- which tests were added
- which tests were run
- any blocked issue or unresolved ambiguity

Do not send vague updates like "board improved" or "CLI updated".

Reports must be concrete.

---

## 9. Required Final Report Format

When the agent considers the implementation complete, the final report must contain:

### 9.1 Delivered Scope

- which phases were fully completed
- which subfeatures were deferred, if any

### 9.2 Files Changed

- list all files changed
- group by model / CLI / board / tests / docs

### 9.3 Design Compliance

- explain how the implementation matches the design spec
- explain how task/job/agent session/provider session/callback are kept distinct
- explain how unknown session cases are represented honestly

### 9.4 Testing

- list all tests added
- list all tests run
- give pass/fail summary

### 9.5 Residual Risks

- list any known limitations
- explicitly call out any design items that remain unimplemented

---

## 10. Direct Agent Instruction

The agent should be given the following direct instruction:

```text
Read and implement the Runtime Console design spec at:

docs/design/specs/2026-04-05-runtime-console-cli-board-design.md

Also read:
- docs/agent/reviews/2026-04-05-coding-callback-runtime-rereview.md
- docs/agent/plans/2026-04-05-coding-runtime-quality-hardening-guide.md

Your job is to implement the Runtime Console across CLI and Web board as a professional operator surface.

You must preserve current coding-runtime correctness and durability guarantees.

You must not expand into provider configuration orchestration or change cancel semantics.

You must treat these as distinct first-class concepts:
- task
- coding job
- agent session
- provider session
- callback report
- fault

You must not invent provider session ids or resume support.
If provider metadata is unavailable, represent the session explicitly as ephemeral/unavailable.

Implement in strict phase order:
1. domain model and persistence
2. CLI completion
3. board data/API layer
4. Web board UI
5. polish and hardening

For every phase:
- add tests first or alongside implementation
- run targeted tests
- report concrete files changed and contracts introduced

Do not optimize for visual polish before correctness and observability are complete.
```

---

## 11. Final Recommendation

The agent should start from the spec and treat this work as operator-console platform engineering.

The core success criterion is not visual attractiveness.

The core success criterion is that an operator can reliably answer:

- what is happening
- where it is happening
- who owns it
- which session/job/task is involved
- what callback decision was made
- whether the system is healthy or degraded

If the implementation does not deliver that, it is not complete.

