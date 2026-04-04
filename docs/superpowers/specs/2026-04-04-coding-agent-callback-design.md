# Coding Agent Callback Loop for Persistent OpenClaw Teams

**Date:** 2026-04-04
**Status:** Draft
**Issue:** N/A

## Problem

ClawTeam-OpenClaw already provides persistent teams, fixed roles, tmux/subprocess runtime, workspace isolation, task store, mailbox messaging, and leader/worker lifecycle handling. That solves team topology and process management.

It does **not** yet provide the callback loop required for external coding agents such as Claude Code or Codex CLI:

1. A worker receives work from its leader.
2. The worker delegates implementation or review to an external coding agent.
3. When the coding agent finishes, the result must return to the **same worker**.
4. The worker must reason over that result and decide whether to:
   - continue with another coding step,
   - report progress upward,
   - escalate for a human/leader decision,
   - or mark the task blocked/done.

Without this callback loop, the system is not closed-loop, not self-reporting, and not reliably controllable.

## Goal

Add a professional callback design that keeps the existing strengths of ClawTeam-OpenClaw:

- persistent reusable teams
- fixed nicknames and role ownership
- tmux visibility
- leader/worker team structure
- worktree/workspace separation

while adding:

- coding-agent completion callbacks
- structured result reuse
- observable job state
- controllable retry/continue/escalate decisions
- explicit working-directory control
- future support for both Claude and Codex

## Decision

**Selected path: V1 synchronous callback loop first.**

Why:

- It directly solves the user's most important requirement: the worker must regain control immediately after Claude/Codex finishes.
- It is much simpler to make correct and observable.
- It avoids introducing async job recovery, duplicate callbacks, wake-up semantics, and distributed state before the core loop is proven.
- It fits OpenClaw's tool-call and agent-loop model cleanly.

**V2 asynchronous callback loop** is intentionally deferred until V1 is stable.

## Non-Goals

These are explicitly out of scope for V1:

- full background job scheduler
- distributed callback bus across hosts
- event streaming UI beyond persisted logs and board state
- preemptive cancellation of arbitrary external processes across all backends
- generic support for every coding harness on day one

## Hard Constraints

These are mandatory V1 constraints.

### Provider configuration is external

This project does not manage Claude Code / Codex models, profiles, accounts, or provider-side configuration orchestration.

V1 only owns the provider execution adapter:

1. choose the executable (`claude` or `codex`)
2. apply startup flags
3. execute in the correct `cwd`
4. capture stdout/stderr/exit code/timeout
5. normalize the result and return it to the same worker

### Coding job state is separate from worker decision

Do not merge provider execution lifecycle with worker callback decisions.

- coding job state: `queued`, `running`, `completed`, `failed`, `timeout`, `cancelled`
- worker decision: `continue`, `report_progress`, `escalate`, `complete`, `blocked`

`blocked` is a worker/task-level judgment in V1, not a coding job lifecycle state.

### V1 concurrency is fixed

V1 supports:

- 1 worker = 1 active coding job
- 1 task = 1 active provider execution

Concurrent coding jobs for the same worker or task are out of scope.

### `cwd` / worktree boundary must be enforced

Default execution inherits the worker workspace/worktree boundary.

- per-call `cwd` override is supported
- silent escape outside the worker workspace/worktree is forbidden
- any escape must be explicit and auditable
- `requested_cwd` and `effective_cwd` must be persisted

### Result normalization must fail closed

Success requires a verifiable structured normalized result.

- parse / incomplete / format failures must not fabricate success
- raw stdout/stderr must be preserved
- normalized result persistence is separate from raw artifact persistence

## Architectural Boundary

### ClawTeam-OpenClaw remains responsible for

- persistent team definition
- team member roles and nicknames
- workspace/worktree management
- tmux/subprocess spawning
- mailbox transport and task store
- leader/worker runtime topology

### OpenClaw remains responsible for

- agent loop
- session/run context
- tool invocation and tool result return
- streaming and retry semantics internal to the agent runtime

### New callback layer becomes responsible for

- invoking Claude/Codex as controlled coding harnesses
- persisting job state and artifacts
- normalizing completion results into a stable schema
- returning completion results back into the worker's decision loop
- supporting later async callback delivery

This separation prevents the team framework from becoming bloated while preserving a clear execution boundary.

## Core Design

### Key principle

The coding agent does **not** callback directly to the leader.

Instead:

1. `worker` calls a coding harness tool.
2. The harness runs Claude/Codex.
3. The harness captures completion and writes artifacts.
4. The harness returns a structured result to the **same worker**.
5. The worker decides the next step.
6. Only then does the worker send a mailbox/status report to the leader.

That keeps the worker as the control point.

### V1 callback model

V1 uses a synchronous tool call named conceptually as `coding_exec`.

Flow:

1. Leader assigns work to worker.
2. Worker analyzes and decides external coding help is needed.
3. Worker calls `coding_exec(provider="claude", task=...)`.
4. `coding_exec` launches Claude Code or Codex CLI.
5. The harness waits for completion.
6. The harness writes job metadata, logs, transcript summary, and result payload.
7. The harness returns a normalized result object to the worker.
8. The worker reasons over the result and chooses:
   - `continue`
   - `report_progress`
   - `escalate`
   - `complete`
   - `blocked`
9. Worker sends mailbox/task update to its leader.

This is the required callback loop for V1.

## Why V1 is preferred over V2

### V1 advantages

- single control path
- easier failure handling
- no detached callback delivery problem
- easier tmux/subprocess parity
- easier testability
- clearer observability

### V2 difficulties

V2 would require all of the following:

- background job registry
- wake-up / follow-up delivery into sleeping workers
- duplicate callback protection
- idempotent retry and replay
- crash recovery for worker and harness separately
- timeout ownership split between worker and job runner
- stronger state machine correctness

V2 is useful, but only after the callback contract and state model are stable.

## Worktree and Working Directory Model

This is a required part of the design, not an implementation detail.

### Control split

The correct execution split is:

1. `worker` owns coordination and task judgment.
2. `worker` receives or creates its isolated git worktree.
3. `coding_exec` runs Claude/Codex **inside that worker workspace**.
4. Claude/Codex performs coding work in that directory.
5. The result returns to the same `worker`.
6. `worker` decides whether to continue or report upward.

So yes: the worker prepares the execution context, and the coding agent performs the actual coding inside that context.

### Relationship to existing ClawTeam-OpenClaw behavior

Current code already establishes the right direction:

- worktree creation happens before agent launch
- worktree path is converted to `cwd`
- spawned agents run in that `cwd`
- workspace information is also included in the prompt and environment

The new callback layer should preserve this model rather than bypass it.

### V1 working-directory rule

`coding_exec` must resolve its working directory in this order:

1. explicit per-call `cwd` override
2. worker's active workspace/worktree directory
3. worker runtime `cwd`
4. fail fast if none is resolvable

This must be deterministic.

### Team and agent level defaults

V1 should support these directory control levels:

- team default repo root
- worker workspace/worktree root
- agent-level `working_dir` default
- per-call `cwd` override

That gives enough control without making directory resolution ambiguous.

### Recommended policy

- default: inherit the worker's workspace `cwd`
- allow per-call `cwd` override for subdirectories
- do not allow a coding job to silently escape outside the worker's assigned repo/worktree unless explicitly configured

That keeps the model safe and predictable.

## Provider Startup Policy

Provider startup flags are part of the design contract.

### Claude default

Claude Code should launch with:

- `--dangerously-skip-permissions`

as the default V1 behavior for coding jobs.

Reason:

- your system is already acting as the higher-level controller
- blocking on interactive permission prompts breaks the worker callback loop
- the worker/worktree boundary is already the intended safety boundary

### Codex default

Codex should launch with:

- `--dangerously-bypass-approvals-and-sandbox`

when the same trusted execution policy is enabled.

### Configurability

V1 limits configurability to execution-adapter concerns such as startup flags and per-call overrides.

It does not include model selection logic, provider profile management, or provider config orchestration.

### Important boundary

`skip permissions` is a harness startup policy. It is **not** the callback mechanism.

It prevents provider-side permission stalls, but the actual callback still comes from the structured result of `coding_exec` returning to the worker.

## Detailed Runtime Design

### 1. New modules

Proposed module layout:

- `clawteam/coding/__init__.py`
- `clawteam/coding/models.py`
- `clawteam/coding/registry.py`
- `clawteam/coding/harness/base.py`
- `clawteam/coding/harness/claude_cli.py`
- `clawteam/coding/harness/codex_cli.py`
- `clawteam/coding/service.py`
- `clawteam/coding/store.py`

Optional later:

- `clawteam/coding/harness/openclaw_acp.py`

### 2. Main abstractions

#### `CodingHarness`

A provider interface that hides Claude/Codex-specific invocation details.

```python
class CodingHarness(Protocol):
    name: str

    def exec(self, request: CodingExecRequest) -> CodingExecResult:
        ...
```

Responsibilities:

- build provider-specific command
- apply provider startup flags
- resolve and enforce working directory
- inject workspace/session env
- capture stdout/stderr/exit code
- locate or generate result artifacts
- normalize the provider output into common schema

#### `CodingService`

The orchestration entry point used by tools/plugins.

Responsibilities:

- validate request
- allocate `job_id`
- resolve effective `cwd`
- persist `started` event
- call selected harness
- persist final result and artifacts
- return normalized `CodingExecResult`

#### `CodingJobStore`

Persistent store for observability and replay.

Responsibilities:

- record job lifecycle
- save compact event log
- expose status lookup
- support later async polling/callback delivery

### 3. Data model

#### `CodingExecRequest`

```python
class CodingExecRequest(BaseModel):
    team_name: str
    worker_name: str
    worker_id: str
    leader_name: str | None = None
    task_id: str | None = None
    provider: Literal["claude", "codex"]
    mode: Literal["implement", "review", "analyze", "test", "general"] = "implement"
    prompt: str
    cwd: str | None = None
    worker_workspace_cwd: str | None = None
    worker_runtime_cwd: str | None = None
    allow_cwd_escape: bool = False
    timeout_sec: int = 1800
    allow_write: bool = True
    skip_provider_permissions: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
```

#### `CodingExecResult`

```python
class CodingExecResult(BaseModel):
    job_id: str
    provider: Literal["claude", "codex"]
    effective_cwd: str
    status: Literal["completed", "failed", "timeout", "cancelled"]
    exit_code: int | None = None
    summary: str = ""
    response_text: str = ""
    next_suggestion: str = ""
    signals: dict[str, bool] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
```

#### `CodingJobRecord`

```python
class CodingJobRecord(BaseModel):
    job_id: str
    team_name: str
    worker_name: str
    provider: str
    task_id: str | None = None
    state: Literal["queued", "running", "completed", "failed", "timeout", "cancelled"]
    requested_cwd: str | None = None
    effective_cwd: str
    created_at: str
    updated_at: str
    request: dict
    result: dict | None = None
```

### 4. Suggested on-disk layout

Under the existing ClawTeam data root:

- `~/.clawteam/coding/jobs/{team}/{job_id}.json`
- `~/.clawteam/coding/logs/{team}/{job_id}.log`
- `~/.clawteam/coding/results/{team}/{job_id}.json`

This gives durable observability without coupling callback state to transient tmux panes.

## Tool Surface

### V1 primary tool: `coding_exec`

This is the recommended first tool.

Input:

```json
{
  "provider": "claude",
  "mode": "implement",
  "taskId": "task_123",
  "prompt": "Implement the retry policy and add tests",
  "cwd": "/workspace/team-a/backend",
  "timeoutSec": 1800,
  "skipProviderPermissions": true
}
```

Return value:

```json
{
  "jobId": "job_01H...",
  "provider": "claude",
  "effectiveCwd": "/workspace/team-a/backend",
  "status": "completed",
  "summary": "Implemented retry policy and added tests for timeout handling.",
  "responseText": "...compact final response...",
  "nextSuggestion": "Run unit tests and request reviewer confirmation.",
  "signals": {
    "needsReview": true,
    "needsDecision": false,
    "blocked": false
  },
  "artifacts": {
    "jobRecord": "...",
    "resultJson": "...",
    "logFile": "..."
  },
  "metrics": {
    "durationSec": 94.2
  }
}
```

### V2 secondary tools

These are deferred:

- `coding_spawn`
- `coding_status`
- `coding_wait`
- `coding_cancel`
- `coding_deliver_callback`

They should not be added until V1 is stable.

## Worker Decision Loop

The worker remains the only component allowed to decide how to react to coding completion.

### Worker policy after `coding_exec`

After each result, the worker must classify the outcome into one of five decisions:

1. `continue`
2. `report_progress`
3. `escalate`
4. `complete`
5. `blocked`

Suggested decision rules:

- `continue`
  - coding result is usable
  - worker still has enough local authority
  - next step is mechanical and bounded

- `report_progress`
  - leader should be informed but no approval is needed
  - useful checkpoint after a major implementation or review round

- `escalate`
  - requirements conflict
  - architecture tradeoff exceeds worker authority
  - repeated coding failure crosses threshold
  - human or leader decision is needed

- `complete`
  - coding result plus worker validation satisfies the task goal

- `blocked`
  - missing dependency, environment, permission, or external decision prevents further progress

This rule set keeps team behavior deterministic and reviewable.

## Leader Interaction

Leader communication should continue to use ClawTeam mailbox/task mechanisms.

The worker should send upward messages such as:

- progress report
- escalation request
- blocked notice
- completion report

The worker should **not** forward raw harness output directly without summarization.

Instead it should send:

- task context
- concise summary
- artifact references
- decision request if needed

That preserves the team hierarchy and keeps the mailbox useful.

## Observability

Observability is a first-class requirement.

### Required visibility for V1

For every coding job, persist:

- who invoked it
- which team and task it belongs to
- which provider was used
- requested `cwd`
- effective `cwd`
- start time and end time
- current state
- exit code
- concise result summary
- artifact paths
- retry count if any

### Board integration

A later board integration can surface:

- active coding jobs by team
- last result per worker
- failed jobs awaiting decision
- blocked tasks due to coding harness failures

V1 does not require board UI changes, but the data model should be compatible.

## Control Model

The callback loop must be controllable.

### Controls needed in V1

- per-job timeout
- per-provider enable/disable
- provider startup flag policy
- max retries for harness launch failures
- explicit worker choice on whether to continue or escalate
- persisted terminal result for auditability
- explicit `cwd` override support

### Controls deferred to V2

- live cancel for detached jobs
- pause/resume detached jobs
- cross-process callback replay
- remote callback delivery

## Retry Model

Retry must be narrow and explicit.

### Retry allowed in V1

Only infrastructure-level retry is allowed automatically:

- process launch failed
- provider CLI temporarily unavailable
- transient file write failure

### Retry not allowed automatically in V1

Do not automatically retry semantic coding attempts after completion.

Example:

- Claude returns a weak answer
- tests fail
- worker disagrees with implementation

In those cases, the **worker** must decide whether to re-run the coding agent with a refined prompt or escalate.

This prevents hidden loops and makes behavior explainable.

## Claude and Codex Dual Support

Dual support should be designed in now, but not forced to equal maturity on day one.

### Recommended support policy

- V1 production path: `claude` first
- V1 compatibility path: `codex` behind the same harness interface
- later: provider-specific improvements and ACP-backed adapter if needed

Why:

- the callback contract should be provider-agnostic
- the harness implementation details will differ
- Claude is already closer to the current operating model
- Codex support is valuable, but should not distort the architecture

## ACP Position

ACP should **not** be the primary implementation path for V1.

Reason:

- ACP can help with protocolized agent execution and event exchange
- it does not remove the need for your business-level callback contract
- switching the whole design to ACP early adds integration risk without solving the core worker callback requirement by itself

Recommended stance:

- keep a `HarnessAdapter` seam so ACP can be added later
- do not block V1 on ACP

## Integration Points in Current Codebase

### Existing pieces to reuse

- `clawteam/spawn/tmux_backend.py`
- `clawteam/spawn/subprocess_backend.py`
- `clawteam/team/mailbox.py`
- `clawteam/team/lifecycle.py`
- `clawteam/team/tasks.py`
- `clawteam/board/collector.py`
- `clawteam/workspace/manager.py`

### Important current limitation

Current `lifecycle on-exit` is only a process-exit cleanup path. It is not sufficient as the coding callback mechanism.

That path should remain for:

- abandoned task recovery
- session cleanup
- dead agent handling

But business callback must live in the new coding layer.

## Proposed Implementation Sequence

### Phase 1: design and schema

- add coding models
- add coding store
- define result schema
- define provider harness interface
- define effective `cwd` resolution rules

### Phase 2: Claude V1

- implement `ClaudeCliHarness`
- default to `--dangerously-skip-permissions`
- inherit worker/workspace `cwd`
- allow per-call `cwd` override
- implement `CodingService.exec()`
- expose `coding_exec`
- persist results and artifacts
- add worker-side prompt/decision examples

### Phase 3: worker policy and reporting

- add worker guidance/templates for post-callback decisions
- standardize escalation/progress mailbox payloads
- surface coding job references in task updates

### Phase 4: Codex support

- implement `CodexCliHarness`
- default to `--dangerously-bypass-approvals-and-sandbox`
- normalize result mapping to shared schema
- add parity tests

### Phase 5: V2 async callbacks

- add detached job runner
- add callback delivery channel
- add wait/status/cancel APIs
- add recovery and idempotency protections

## Testing Strategy

V1 needs the following tests before production use:

- unit tests for request/result schema
- unit tests for job store persistence
- harness command construction tests
- harness `cwd` resolution tests
- harness startup-flag tests
- harness result normalization tests
- worker decision policy tests
- integration test: worker -> coding_exec -> result -> mailbox report
- timeout test
- failed harness invocation test

## Risks

### Risk 1: treating process exit as business completion

This is incorrect. A CLI exit only tells us the process ended, not whether the worker received a reusable result.

Mitigation:

- require normalized result object
- persist terminal job state separately from process lifecycle

### Risk 2: overloading mailbox as raw callback bus

If raw Claude/Codex output is dumped into mailbox messages, the leader and team traffic will become noisy and difficult to control.

Mitigation:

- callback returns to worker first
- worker summarizes before upward reporting

### Risk 3: ambiguous working directory behavior

If the coding harness can silently run in the wrong directory, the system will become difficult to trust.

Mitigation:

- define deterministic `cwd` precedence
- persist requested and effective `cwd`
- fail fast when no valid execution directory is available
- enforce workspace/worktree boundary by default

### Risk 4: premature async design

Async callback design introduces significantly more state complexity.

Mitigation:

- ship V1 sync first
- keep provider interface compatible with later detached execution

### Risk 5: normalization guessing creates false positives

If exit code `0` is treated as success without a verifiable structured payload, the runtime becomes untrustworthy.

Mitigation:

- require structured normalization output
- fail closed when normalization fails
- preserve raw stdout/stderr as artifacts

## Final Recommendation

Build this on **ClawTeam-OpenClaw**, not Legion.

Implement **V1 synchronous coding callback loop** first.

That means:

- persistent team runtime stays in ClawTeam-OpenClaw
- worker/leader messaging stays on native team mailbox/task flow
- worker owns worktree/context preparation
- coding agent runs inside the worker's workspace
- Claude defaults to `--dangerously-skip-permissions`
- Codex defaults to `--dangerously-bypass-approvals-and-sandbox`
- coding agent completion becomes a new structured callback layer
- worker is the decision authority after each coding completion

This is the smallest design that satisfies the user's core requirements while staying professional, stable, reliable, correct, observable, and extensible.

## Future V2 Summary

V2 is valuable only after V1 proves the callback contract.

V2 should add:

- detached coding jobs
- explicit callback delivery to workers
- wait/status/cancel APIs
- stronger recovery and idempotency
- richer board visualization

But V2 should be treated as an evolution, not the starting point.
