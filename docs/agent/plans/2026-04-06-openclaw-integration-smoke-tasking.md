# 2026-04-06 OpenClaw Integration Smoke Tasking

## Purpose

Implement the next quality gate after the standalone clawteam baseline.

The standalone full-chain smoke now proves that the durable clawteam substrate works in isolation.

That is necessary, but not sufficient.

The next required layer is a real OpenClaw integration smoke that validates the default worker runtime path actually used by this fork:

- `clawteam` creates the team and worker identity
- `clawteam` spawns the worker runtime via the OpenClaw path
- OpenClaw delivery is actually enabled
- the worker does not remain a dead tmux shell or idle TUI window
- the worker reaches observable runtime progression
- the callback chain remains visible through durable state and operator surfaces

This task is not optional if we want to move from the current `~9.2/10` baseline toward `9.5+`.

## Why This Work Is Needed

We already fixed the first-install class of failures:

- workspace preflight is now explicit and safe
- unhealthy repos no longer fail with opaque raw git errors in `workspace=auto`
- default OpenClaw launch now appends `--deliver`
- explicit fork versioning now exists
- standalone smoke now validates task -> coding -> callback -> board durable state

What is still missing is proof of the real integration path.

Right now we still do **not** have a test that proves:

- the default OpenClaw worker path does what we think it does at runtime
- tmux + OpenClaw delivery leads to actual worker activity rather than an idle shell
- OpenClaw-driven startup produces observable progress through the clawteam control plane

Until that exists, the system is strong, but not yet near-fully-trusted.

## Scope

This task implements an automated integration smoke focused on the OpenClaw runtime path.

It is intentionally narrower than a full end-to-end provider smoke.

### In Scope

- OpenClaw worker launch contract validation
- tmux/OpenClaw startup observability validation
- worker progress observability through clawteam durable state
- callback presence validation on the OpenClaw-driven path when feasible in the harness
- deterministic test cleanup
- documentation updates if operator behavior changes or becomes newly explicit

### Out Of Scope

Do not implement any of the following in this task:

- provider config orchestration
- real Claude/Codex account provisioning
- Discord channel/thread routing
- ACP redesign
- detached async callback redesign
- stronger live cancel semantics
- reconciliation/recovery subsystem redesign
- full browser E2E UI automation

## Required Reading Before Coding

Read these documents in order before changing code:

1. [Coding Agent Callback Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-04-coding-agent-callback-design.md)
2. [Runtime Console CLI + Board Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-05-runtime-console-cli-board-design.md)
3. [Runtime Quality Roadmap To 9.5+](/root/github.com/ClawTeam-OpenClaw/docs/agent/plans/2026-04-05-runtime-quality-roadmap-to-9.5.md)
4. [OpenClaw First-Install Remediation Plan](/root/github.com/ClawTeam-OpenClaw/docs/agent/plans/2026-04-06-openclaw-first-install-remediation-plan.md)
5. [ClawTeam Standalone Full-Chain Smoke Test Design](/root/github.com/ClawTeam-OpenClaw/docs/agent/plans/2026-04-06-clawteam-standalone-smoke-test-design.md)

## Design Goal

Add a second smoke layer, after the standalone baseline, that validates the real OpenClaw integration surface without depending on real external provider accounts.

The key principle is:

- use the real `clawteam spawn` OpenClaw path
- use the real tmux backend when testing that path
- use a controlled fake `openclaw` binary or controlled OpenClaw harness behavior when needed
- prove observable progression, not merely command construction

This is a runtime-contract smoke, not just a unit test.

## Non-Negotiable Constraints

- do not remove or weaken the standalone smoke suite
- do not replace integration coverage with more mocking-only unit tests
- do not mark tmux window creation as success if no runtime progress occurs
- do not hide idle-worker failure modes
- do not assume provider availability
- do not make this test depend on a human manually watching tmux
- do not introduce nondeterministic sleep-heavy assertions without bounded polling
- do not leave tmux sessions, worker processes, or board processes behind after test completion
- do not weaken durable-state truth boundaries to make the smoke easier to pass

## Core Question To Answer

After `clawteam spawn` uses the OpenClaw runtime path, can we prove that the worker actually enters an observable running state rather than merely opening a shell or TUI window?

That proof must be expressed through assertions.

## Required Deliverables

Implement all of the following.

### 1. OpenClaw integration smoke test file

Add a new test module, recommended path:

- `tests/test_smoke_openclaw_integration.py`

This file should contain an isolated, automated smoke suite that validates the OpenClaw runtime path.

### 2. OpenClaw smoke helpers

Add helper code as needed under:

- `tests/smoke/helpers.py`
- optionally `tests/smoke/bin/openclaw`
- optionally `tests/smoke/fake_openclaw_tui.py`

Prefer reusing the existing standalone smoke harness instead of building a separate test framework.

### 3. Runtime-path assertions

Add assertions that verify the OpenClaw path is not only constructed correctly but also operationally observable.

### 4. Documentation updates

If behavior, operator guidance, or test entry points become clearer after implementation, update:

- [README.md](/root/github.com/ClawTeam-OpenClaw/README.md)
- [docs/runtime-console-operator-guide.md](/root/github.com/ClawTeam-OpenClaw/docs/runtime-console-operator-guide.md)
- skill docs only if runtime/operator-facing semantics materially change

## Test Strategy

The OpenClaw integration smoke should be structured in layers.

### Layer 1: Command Contract Validation

Validate that the default OpenClaw tmux worker launch path contains the expected delivery semantics.

This layer should prove at minimum:

- default OpenClaw spawn path uses `openclaw tui`
- `--deliver` is present by default
- expected identity/session/message arguments are passed through

This is partly already covered in unit/integration tests.

Do not stop here.

### Layer 2: Runtime Startup Validation

This is the missing layer.

The smoke must prove that when the OpenClaw path is used, the worker reaches a real runtime state.

Acceptable ways to prove this include one of these:

- the fake OpenClaw binary logs that it received the expected `tui --deliver ...` invocation and then executes the worker prompt payload path in a deterministic way
- the system records durable state changes showing worker-side progress after spawn
- tmux capture shows the injected command actually executed and not just an idle shell prompt

Best implementation:

- use a fake `openclaw` binary in isolated test `PATH`
- have it emulate the small subset of behavior required by this fork's worker launch contract
- make it deterministic and self-cleaning

### Layer 3: Progress/Callback Observability Validation

The integration smoke must assert at least one downstream signal of real progress.

Examples of acceptable observable outcomes:

- a task transitions from `pending` to `in_progress` or `completed`
- inbox receives a worker-originated status message
- a coding job appears under the target team
- runtime-console callback records appear
- timeline contains a meaningful runtime event caused by the worker path

If callback is not feasible in the first OpenClaw smoke slice, the test must still prove worker runtime progression.

However, the preferred target is to carry the chain through callback as well.

## Recommended Harness Design

### Approach

Use an isolated fake `openclaw` binary rather than a real OpenClaw installation.

Reason:

- we need deterministic CI-friendly behavior
- we do not want provider/account/network coupling
- we want to validate the integration contract with the local fork, not upstream service availability

### Fake OpenClaw Responsibilities

The fake binary only needs to support the subset of the CLI that clawteam actually invokes in this path.

At minimum, support:

- `openclaw tui --deliver --session <...> --message <...>`

The fake binary should:

1. record its argv and selected env to a log file under the isolated temp root
2. verify it was invoked in the expected mode
3. execute a deterministic worker action compatible with the smoke harness
4. exit non-zero if required launch arguments are missing

### Worker Action Options

You have two viable implementation choices.

#### Option A: Fake OpenClaw delegates into the existing fake worker

Recommended if feasible.

The fake `openclaw` binary can extract the delivered message/prompt payload and then invoke:

- `tests/smoke/fake_worker.py`

or a tiny wrapper around it.

This is preferred because it reuses the existing durable-state path:

- task update
- coding exec
- coding wait
- callback report
- inbox notify

#### Option B: Fake OpenClaw performs a thinner progress-only action

If prompt extraction is too indirect for the current spawn path, the fake OpenClaw can perform a minimal deterministic action that still proves runtime progression.

For example:

- write a marker artifact
- call clawteam CLI to update task state
- send inbox notification
- optionally call `coding exec` directly

But Option A is the better target because it validates more of the real chain.

## Required Test Cases

Implement at least these test cases.

### Test A: OpenClaw default spawn produces real progress

Recommended name:

- `test_smoke_openclaw_default_spawn_makes_progress`

Flow:

1. create isolated temp environment
2. install fake `claude`
3. install fake `openclaw`
4. create team and owned task
5. spawn worker using the default OpenClaw path under test
6. bounded-poll for observable progress
7. assert that progress occurred
8. assert fake OpenClaw invocation log shows `tui --deliver`
9. assert cleanup removes team state and spawned residues

Required assertions:

- no opaque spawn failure
- fake OpenClaw was actually invoked
- `--deliver` was passed
- the worker produced at least one durable observable signal

### Test B: OpenClaw path can drive callback persistence

Recommended name:

- `test_smoke_openclaw_path_persists_callback`

This test should exist if Option A above is feasible.

Required assertions:

- coding job exists
- coding result exists
- callback record exists
- board JSON or runtime-console JSON shows the callback
- timeline includes `callback_reported`

If the first implementation cannot reasonably reach callback without overfitting the harness, note that in comments and land Test A first. But the goal remains to reach callback.

### Test C: OpenClaw launch contract fails honestly on malformed runtime invocation

Recommended name:

- `test_smoke_openclaw_launch_failure_is_explicit`

This test should prove that if the fake OpenClaw receives a malformed or missing argument set, the failure is explicit and diagnosable.

This should not present as silent success.

## Cleanup Contract

This suite must be clean.

The existing standalone smoke cleanup already handles:

- board server processes
- worker subprocess cleanup via registry
- workspace cleanup
- team cleanup
- temp root cleanup

Extend the cleanup contract for OpenClaw integration smoke to also handle:

- fake OpenClaw subprocess children if any
- tmux sessions created by the OpenClaw path
- any invocation logs or temp transport files under the isolated root

Add assertions where appropriate that cleanup actually happened.

## Implementation Notes

### Reuse Existing Harness

Prefer extending the current smoke helpers instead of building parallel infrastructure.

Likely touch points:

- `tests/smoke/helpers.py`
- `tests/smoke/fake_worker.py`
- `tests/smoke/bin/claude`
- new `tests/smoke/bin/openclaw`
- maybe a helper to capture tmux output or inspect invocation logs

### Do Not Over-Mock

This is important.

The previous quality gap existed because the earlier smoke only proved wiring, not the integrated chain.

Do not repeat that mistake here.

The new smoke should use:

- real `clawteam` CLI
- real spawn path under test
- real durable state files
- real callback persistence path where feasible

### Prefer Polling On Durable State

Do not depend on arbitrary sleeps.

Use bounded polling on real operator surfaces such as:

- `task get`
- `task wait`
- `inbox log`
- `coding list/status/result`
- `faults list`
- `audit timeline`
- `board show --json`

## Acceptance Criteria

This task is complete only if all of the following are true.

### Functional

- there is an automated OpenClaw integration smoke suite in the repo
- the suite validates the real OpenClaw worker runtime path used by this fork
- the suite proves that default OpenClaw spawn does more than create an idle shell/window
- the suite produces at least one durable observable worker-progress signal
- preferred: the suite proves callback persistence on the OpenClaw-driven path

### Reliability

- tests are deterministic
- tests are self-cleaning
- tests do not depend on real provider accounts
- failures are explicit and diagnosable

### Quality

- no existing standalone smoke coverage is regressed
- no operator-facing semantics are silently changed
- docs are updated if test entry points or operator expectations changed

## Required Validation Before Marking Done

Run and report at minimum:

```bash
python -m pytest tests/test_smoke_openclaw_integration.py -q
python -m pytest tests/test_smoke_clawteam_full_chain.py tests/test_coding_integration.py tests/test_spawn_backends.py tests/test_spawn_cli.py -q
```

If implementation touches cleanup or tmux behavior, also run the closest related tests and report them explicitly.

## What To Report Back

When finished, report in this structure:

1. files changed
2. exact OpenClaw smoke behavior now covered
3. whether callback persistence is included or only progress observability is included
4. exact commands run
5. pass/fail summary
6. residual risks

## Expected Residual Risks After This Task

Even after this is done, these may still remain by design:

- no real provider/account/network smoke
- callback delivery still uses the synchronous V1 model
- stronger live control semantics remain unimplemented
- reconciliation/recovery remain future work

That is acceptable.

What is **not** acceptable after this task is:

- still not knowing whether the default OpenClaw runtime path actually produces worker progress
- still relying on human tmux inspection to judge whether spawn worked
- still treating tmux window creation as proof of runtime success
