# Coding Agent Callback Runtime Single-Agent Implementation Plan

> **For one coding agent:** This plan is intended to be executed end-to-end by a single coding agent working sequentially in the same repository. Do not parallelize internally. Do not begin later phases before the current phase is stable.

**Goal:** Build a professional, controllable, observable, and trustworthy coding-agent callback runtime on top of ClawTeam-OpenClaw, using persistent teams and worker-owned git worktrees. Claude and Codex should execute inside worker workspaces, return structured results to the same worker, and allow the worker to continue, report, escalate, complete, or block.

**Primary Spec:** `docs/superpowers/specs/2026-04-04-coding-agent-callback-design.md`

**Platform Decision:** Build on `ClawTeam-OpenClaw`, not Legion.

**Delivery Standard:** Not MVP. The target is a production-grade V1 with deterministic state, observability, test coverage, and operational control.

---

## Hard Constraints

These constraints are mandatory and take priority over later feature work.

### Provider configuration is external

Do not implement model selection logic, provider profile management, provider account handling, or provider config orchestration.

Only provider execution adapter responsibilities are in scope:

1. choose executable (`claude` / `codex`)
2. apply startup flags
3. execute in the correct `cwd`
4. capture stdout/stderr/exit code/timeout
5. normalize result and return it to the same worker

### Job state is separate from worker decision

- coding job state: `queued`, `running`, `completed`, `failed`, `timeout`, `cancelled`
- worker decision: `continue`, `report_progress`, `escalate`, `complete`, `blocked`

Do not merge these into one state machine. In V1, `blocked` belongs to worker/task judgment, not coding job lifecycle.

### V1 concurrency is fixed

- 1 worker = 1 active coding job
- 1 task = 1 active provider execution

Do not add concurrent coding jobs for the same worker or task in this implementation cycle.

### `cwd` boundary is mandatory

- default execution inherits worker workspace/worktree
- `cwd` override cannot silently escape the worker boundary
- any escape must be explicit and auditable
- `requested_cwd` and `effective_cwd` must be persisted

### Result normalization fails closed

- exit code `0` is not enough for success
- success requires verifiable structured normalization
- parse / incomplete / format failures must become explicit failed results
- raw stdout/stderr must be preserved alongside normalized result persistence

---

## Execution Rule

This project must be developed by one coding agent in strict order.

Rules:

- do not jump ahead to command UX before runtime contracts are stable
- do not write provider-specific code before request/result/state contracts are frozen
- do not add board/task integration before control-plane semantics are clear
- do not leave tests to the end
- do not treat process exit as business callback completion
- do not treat prose-only provider output as successful normalization

The critical path is:

1. runtime contract
2. state machine and persistence
3. provider harnesses
4. control plane
5. worker reporting integration
6. observability
7. hardening and tests

---

## Scope

### In scope for Professional V1

- coding runtime module
- synchronous `coding_exec`
- structured callback result to same worker
- worker decision policy and reporting path
- job store and event persistence
- deterministic `cwd` resolution
- workspace/worktree boundary enforcement by default
- worker worktree inheritance
- Claude default `--dangerously-skip-permissions`
- Codex default `--dangerously-bypass-approvals-and-sandbox`
- timeout / retry baseline
- status / wait / cancel / retry / replay baseline control plane
- tests for happy path and failure path
- operational docs

### Out of scope for this implementation cycle

- detached async callback runtime
- ACP as the primary execution backend
- rich UI beyond data hooks needed for board visibility

---

## Architecture Summary

The implementation must preserve these boundaries:

- `ClawTeam-OpenClaw` owns team topology, worktree/workspace, tmux/subprocess, mailbox, tasks, and lifecycle.
- `coding runtime` owns external coding harness invocation, result normalization, persistence, and control APIs.
- `worker` owns decision-making after coding completion.
- `leader` only receives curated reports from the worker, never raw provider output by default.

---

## File Map

### New files expected

- `clawteam/coding/__init__.py`
- `clawteam/coding/models.py`
- `clawteam/coding/store.py`
- `clawteam/coding/service.py`
- `clawteam/coding/registry.py`
- `clawteam/coding/harness/__init__.py`
- `clawteam/coding/harness/base.py`
- `clawteam/coding/harness/claude_cli.py`
- `clawteam/coding/harness/codex_cli.py`
- `tests/test_coding_models.py`
- `tests/test_coding_store.py`
- `tests/test_coding_service.py`
- `tests/test_coding_harness_claude.py`
- `tests/test_coding_harness_codex.py`
- `tests/test_coding_integration.py`

### Existing files likely to change

- `clawteam/cli/commands.py`
- `clawteam/board/collector.py`
- `clawteam/team/tasks.py`
- `clawteam/team/models.py`
- `clawteam/spawn/prompt.py`
- `README.md`

---

## Phase 0: Contract Freeze

**Goal:** Freeze the runtime contract before any substantial implementation begins.

### Tasks

- [x] define `CodingExecRequest`
- [x] define `CodingExecResult`
- [x] define `CodingJobRecord`
- [x] define event schema
- [x] define required job states
- [x] define valid state transitions
- [x] define retry vs replay semantics
- [x] define `cwd` precedence:
  1. request `cwd`
  2. worker workspace/worktree `cwd`
  3. worker runtime `cwd`
  4. fail fast
- [x] define provider startup flag policy:
  - Claude default `--dangerously-skip-permissions`
  - Codex default `--dangerously-bypass-approvals-and-sandbox`
- [x] define control-plane surface:
  - `coding exec`
  - `coding status`
  - `coding wait`
  - `coding cancel`
  - `coding retry`
  - `coding replay`

### Output

A stable implementation contract reflected in code comments, type definitions, and tests.

### Acceptance

- [x] schema names are stable
- [x] state names are stable
- [x] `cwd` behavior is deterministic
- [x] retry/replay are not conflated

---

## Phase 1: Runtime Core

**Goal:** Build the durable runtime foundation before touching CLI integration.

### Primary files

- `clawteam/coding/models.py`
- `clawteam/coding/store.py`
- `clawteam/coding/service.py`
- `clawteam/coding/registry.py`
- `tests/test_coding_models.py`
- `tests/test_coding_store.py`
- `tests/test_coding_service.py`

### Tasks

- [x] create coding module structure
- [x] implement request/result/job/event schemas
- [x] implement state machine validation
- [x] implement durable job store
- [x] implement event append model
- [x] implement result/artifact persistence
- [x] implement `effective_cwd` resolution
- [x] persist `requested_cwd` and `effective_cwd`
- [x] implement infrastructure-level retry metadata
- [x] expose a stable service API for harness invocation

### Rules

- terminal results must be durable
- invalid transitions must fail explicitly
- file writes must be atomic where practical
- no provider-specific parsing here

### Acceptance

- [x] runtime core tests pass
- [x] state transitions are enforced
- [x] `effective_cwd` is covered by tests
- [x] service can create, update, and complete job records safely

---

## Phase 2: Provider Harness Layer

**Goal:** Add Claude and Codex execution behind a shared harness interface.

### Primary files

- `clawteam/coding/harness/__init__.py`
- `clawteam/coding/harness/base.py`
- `clawteam/coding/harness/claude_cli.py`
- `clawteam/coding/harness/codex_cli.py`
- `tests/test_coding_harness_claude.py`
- `tests/test_coding_harness_codex.py`

### Tasks

- [x] define provider-agnostic harness interface
- [x] implement Claude CLI harness
- [x] implement Codex CLI harness
- [x] apply startup flag defaults correctly
- [x] support per-call override of startup flag policy
- [x] run provider in `effective_cwd`
- [x] capture stdout/stderr/exit code
- [x] normalize timeout into structured timeout result
- [x] normalize non-zero exit into structured failed result
- [x] attach log/result artifact references

### Rules

- harnesses must not message leader directly
- harnesses must not make worker decisions
- malformed provider output must not be silently fabricated into success
- provider result normalization must fail closed

### Acceptance

- [x] Claude harness tests pass
- [x] Codex harness tests pass
- [x] startup flags are correct
- [x] timeout/failure behavior is normalized consistently

---

## Phase 3: Service-to-Harness Integration

**Goal:** Connect runtime core and provider harnesses into one stable execution path.

### Primary files

- `clawteam/coding/service.py`
- `clawteam/coding/registry.py`
- relevant harness files
- `tests/test_coding_service.py`

### Tasks

- [x] service selects harness by provider
- [x] service invokes harness with resolved `effective_cwd`
- [x] service persists start/finish/failure events
- [x] service persists final result and artifacts
- [x] service emits structured terminal result even on provider failure
- [x] service supports retry/replay metadata correctly

### Acceptance

- [x] one service entrypoint can run Claude/Codex through the same contract
- [x] persisted job state matches actual runtime outcome
- [x] no ambiguity between service failure and provider failure

---

## Phase 4: Control Plane Commands

**Goal:** Expose the runtime through durable commands, not ad hoc internal calls.

### Primary files

- `clawteam/cli/commands.py`
- `tests/test_coding_integration.py`

### Tasks

- [x] add `coding exec`
- [x] add `coding status`
- [x] add `coding wait`
- [x] add `coding cancel`
- [x] add `coding retry`
- [x] add `coding replay`
- [x] ensure commands operate on persisted job state
- [x] make command output stable and inspectable

### Rules

- `exec` returns structured result to the invoking worker context
- `status/wait/cancel/retry/replay` must work without relying only on transient process handles
- `retry` and `replay` must behave differently and clearly

### Acceptance

- [x] command surface exists and is testable
- [x] commands work against stored jobs
- [x] outputs are stable enough for future automation

---

## Phase 5: Worker Reporting Integration

**Goal:** Ensure callback completion returns control to the worker, and the worker reports upward correctly.

### Primary files

- `clawteam/team/tasks.py`
- `clawteam/team/models.py`
- `clawteam/spawn/prompt.py`
- `tests/test_coding_integration.py`

### Tasks

- [x] define worker post-callback decision policy:
  - `continue`
  - `report_progress`
  - `escalate`
  - `complete`
  - `blocked`
- [x] update worker guidance/prompting to reflect callback loop
- [x] ensure worker reports are summarized
- [x] include job IDs / coding status references in task/report path as appropriate
- [x] ensure mailbox is not used as a raw provider dump sink

### Rules

- worker is the only decision authority after coding completion
- leader receives summaries, not raw provider transcript by default
- callback loop must be explainable from logs and state

### Acceptance

- [x] end-to-end worker callback loop is explicit
- [x] reporting path is stable and not noisy
- [x] integration tests cover worker -> coding_exec -> result -> summarized report

---

## Phase 6: Observability Integration

**Goal:** Make coding jobs inspectable from the broader system.

### Primary files

- `clawteam/board/collector.py`
- optionally `README.md`
- `tests/test_coding_integration.py`

### Tasks

- [x] expose coding job metadata to board/task views where appropriate
- [x] surface latest job ID, provider, state, summary, timestamps, cwd metadata as needed
- [x] document where logs/results are stored

### Rules

- do not break existing board outputs
- enrich existing views rather than replacing them
- observability must come from persisted state, not tmux-only visibility

### Acceptance

- [x] board/task integration remains backward compatible
- [x] job visibility is sufficient for operational debugging

---

## Phase 7: Hardening and Reliability

**Goal:** Make the system worthy of trust under failure, not just in the happy path.

### Tasks

- [x] verify provider binary missing path
- [x] verify provider startup failure path
- [x] verify timeout path
- [x] verify malformed provider output path
- [x] verify persistence write failure handling where practical
- [x] verify retry behavior for infrastructure failures only
- [x] verify replay behavior from persisted request data
- [x] verify no hidden coupling to process-exit hook semantics

### Acceptance

- [x] critical failure paths are covered by tests
- [x] runtime leaves inspectable state after failures
- [x] trustworthiness comes from persisted evidence, not assumptions

---

## Phase 8: Final Verification and Documentation

**Goal:** Finish the project as a maintainable system, not just a passing patch set.

### Primary files

- `README.md`
- design and plan docs as needed
- all tests

### Tasks

- [x] run targeted tests per module
- [x] run integration tests
- [x] verify naming consistency
- [x] verify artifact path consistency
- [x] verify command help text and docs
- [x] update README usage/examples if needed
- [x] summarize remaining risks honestly

### Final acceptance checklist

- [x] worker-owned worktree inheritance works end-to-end
- [x] per-call `cwd` override works and is persisted
- [x] Claude default permission-skip flag works
- [x] Codex default approval-bypass flag works
- [x] result returns to same worker as structured callback
- [x] worker decision loop is explicit and documented
- [x] leader receives summarized report, not raw provider dump
- [x] control-plane commands operate on durable state
- [x] failures and timeouts are observable and recoverable at baseline
- [x] tests cover happy path and critical failure paths
- [x] docs are sufficient for future maintenance

---

## Required State Machine

The runtime must implement at least these states:

- `queued`
- `running`
- `completed`
- `failed`
- `timeout`
- `cancelled`

Required transitions:

- `queued -> running`
- `running -> completed`
- `running -> failed`
- `running -> timeout`
- `queued -> cancelled`
- `running -> cancelled`
- terminal -> new attempt only through explicit `retry` or `replay`

No implicit transitions are allowed.

---

## Required Observability Fields

Every job should persist at least:

- team name
- worker name
- worker ID
- task ID
- provider
- requested `cwd`
- effective `cwd`
- startup flag policy used
- state
- exit code
- summary
- error
- created timestamp
- updated timestamp
- artifact paths
- retry/replay lineage
- single-active-job invariant for the worker/task in V1

---

## Required Development Order

The single coding agent must follow this order exactly:

1. Phase 0 contract freeze
2. Phase 1 runtime core
3. Phase 2 provider harnesses
4. Phase 3 service integration
5. Phase 4 control plane commands
6. Phase 5 worker reporting integration
7. Phase 6 observability integration
8. Phase 7 hardening
9. Phase 8 final verification and docs

Do not reorder these phases.

---

## Final Instruction to the Coding Agent

Implement this as a platform feature, not as a shortcut patch.

Your priorities are:

1. correctness
2. determinism
3. observability
4. control
5. maintainability

If any later-phase work exposes a flaw in an earlier contract, stop and fix the contract instead of layering exceptions on top.
