# 2026-04-06 OpenClaw First-Install Remediation Plan

## Background

During first real usage with OpenClaw driving ClawTeam-OpenClaw, two critical operator-facing problems were discovered before the intended callback workflow could be trusted:

1. `clawteam spawn` default workspace behavior tried to create a git worktree in an OpenClaw workspace repo that was not worktree-capable.
2. `clawteam spawn --no-workspace` avoided the git error, but spawned OpenClaw workers did not actually enter autonomous execution.

These are first-install blockers. They are not acceptable as "operator education" issues. The fork must be robust enough that first real use does not immediately stall on default-path assumptions.

This document records the root-cause analysis, required fixes, versioning work, and a mandatory smoke-test plan.

## Problem Attribution

These first-install failures do not all come from the current `feature/coding-agent-callback-runtime` line. They fall into three categories:

1. Pre-existing baseline behavior:
   - `spawn --workspace/--no-workspace` existed from the initial project line
   - `workspace = "auto"` was already the default behavior
   - the coarse `auto -> if repo exists, try worktree` model was not introduced by the callback runtime work

2. Earlier OpenClaw integration behavior:
   - default worker spawning changed from `claude` to `openclaw` before the callback runtime line
   - OpenClaw tmux session launch behavior was introduced in earlier OpenClaw integration commits
   - the current idle-worker problem comes from that OpenClaw tmux launch path not enabling provider delivery by default

3. Current delivery-quality gap:
   - the callback/runtime line made the system much more real and operator-visible
   - but first-install smoke coverage did not exercise the full path of install -> OpenClaw-driven spawn -> autonomous worker execution -> callback -> leader reporting
   - as a result, old spawn/OpenClaw/versioning flaws were exposed during real usage instead of being caught before release

Therefore the correct conclusion is:

- the callback runtime branch did **not** single-handedly create all of these failures
- it **did** expose baseline and OpenClaw-integration weaknesses that were already present or insufficiently validated
- the remediation must therefore fix both the old default-path issues and the missing first-install smoke coverage

## Executive Summary

The current fork is close to a strong V1 runtime, but the first-install path exposed two gaps in the worker-spawn layer:

- workspace `auto` is currently environment-driven rather than task-aware and repo-health-aware
- the default OpenClaw tmux worker path launches `openclaw tui --message ...` without `--deliver`, which leaves spawned workers visually present but functionally idle

The result is misleading behavior:

- team/task creation succeeds
- tmux worker windows appear
- but the intended "worker receives task -> acts -> uses coding runtime -> callback -> reports leader" chain never starts

This must be fixed before claiming that OpenClaw-driven ClawTeam orchestration is operationally reliable.

## Incident Findings

### Finding 1: Workspace auto behavior is too coarse

Observed failure:

- `clawteam spawn ...` attempted `git worktree add -b ... master`
- the repo under the OpenClaw workspace did not have a valid worktree-capable base ref
- spawn failed before any worker runtime behavior could be tested

What this means:

- the current `workspace=auto` behavior is not truly "smart auto"
- it attempts workspace isolation whenever a git repo is detected
- it does not first verify that the repo has a valid `HEAD`, valid current branch/base ref, and a usable worktree baseline

Current implementation facts:

- config default is `workspace = "auto"`
- `spawn` resolves `auto` to `workspace=True`
- if a repo is detected, it immediately attempts worktree creation
- there is no explicit repo-health preflight before `git worktree add`

Relevant code:

- `clawteam/config.py`
- `clawteam/cli/commands.py`
- `clawteam/workspace/manager.py`
- `clawteam/workspace/git.py`

### Finding 2: Spawned OpenClaw tmux workers are launched idle

Observed behavior after `--no-workspace`:

- tmux session and worker windows were created successfully
- durable state showed no task progress and no runtime activity
- tasks remained `pending`
- `currentTaskId/currentJobId/currentSessionId` remained `null`
- no jobs, sessions, callbacks, faults, or timeline events appeared
- inbox remained empty

This proves:

- worker process launch succeeded
- but the worker did not actually begin provider-backed autonomous execution

Root cause:

The tmux backend currently launches OpenClaw workers using:

- `openclaw tui --session <session> --message <prompt>`

But it does not pass:

- `--deliver`

OpenClaw official TUI documentation states:

- messages are sent to the Gateway
- delivery to providers is off by default
- delivery must be enabled via `/deliver on` or `openclaw tui --deliver`

That means the current ClawTeam worker path creates a visible TUI session and sends an initial message, but does not actually enable provider delivery. The worker therefore appears alive while remaining idle.

Relevant code:

- `clawteam/spawn/tmux_backend.py`

Relevant OpenClaw docs:

- https://docs.openclaw.ai/tui
- https://docs.openclaw.ai/web/tui
- https://docs.openclaw.ai/messages

### Finding 3: `spawn` does not equal autonomous task execution

This distinction must be explicit in design and docs.

Current spawn semantics:

- create team member record
- create inbox
- launch process/window
- inject prompt

Current spawn semantics do **not** guarantee:

- task claim
- task state transition to `in_progress`
- provider session creation
- automatic inbox reply
- automatic coding-runtime invocation

This is acceptable only if documented honestly and if the default OpenClaw worker path reliably performs autonomous execution when prompted.

Right now it does not reliably do so because the TUI path is launched with delivery disabled.

## Required Fixes

### P0: Fix OpenClaw tmux worker delivery

Owner: spawn/runtime integration

Required changes:

1. Update the OpenClaw tmux spawn path so spawned workers do not start in an idle non-delivering TUI state.
2. At minimum, add `--deliver` to the `openclaw tui` command path used by spawned workers.
3. Re-evaluate whether `openclaw tui` is the correct worker mode for autonomous team members.
4. Compare `openclaw tui --deliver --message ...` versus `openclaw agent ...` for reliability, callback visibility, and operator observability.
5. Choose one explicit default and document why.

Acceptance criteria:

- `clawteam spawn --no-workspace ...` with default OpenClaw path causes the worker to actually process the injected task prompt without manual operator interaction
- within a bounded time window, observable state changes occur:
  - task activity or inbox message appears
  - or provider session / runtime activity appears
- the system no longer presents "spawned but idle forever" as a successful default-path outcome

### P0: Add workspace preflight and safe auto behavior

Owner: workspace/spawn layer

Required changes:

1. Add a workspace preflight before `git worktree add`.
2. Detect and report clearly:
   - not a git repo
   - repo without valid `HEAD`
   - unborn branch
   - invalid base ref
   - worktree creation failure conditions
3. Redefine `workspace=auto`:
   - if repo is healthy and usable, create workspace
   - if repo is unhealthy/unusable, auto-disable workspace and continue, with an explicit warning
4. Keep `workspace=always` as the strict mode that fails loudly.
5. Add explicit base ref override support, for example:
   - `--workspace-base-ref <ref>`
   - and/or config `workspace_base_ref`

Acceptance criteria:

- bad repo under OpenClaw workspace no longer causes confusing raw git failure in `auto`
- operator receives an explicit explanation and recovery guidance
- `auto` is safe enough for first use
- `always` remains strict and predictable

### P0: Improve operator-facing error messages

Owner: CLI/operator experience

Required changes:

When workspace creation is skipped or fails, print a structured explanation containing:

- repo root
- requested repo/cwd
- workspace mode
- current branch
- resolved base ref
- whether `HEAD` is valid
- exact next steps:
  - use `--no-workspace`
  - use `--repo <real-project-repo>`
  - use `--workspace-base-ref <ref>`

Do not leak only the raw git stderr as the main operator message.

### P1: Add `workspace doctor`

Owner: workspace tooling

Add a diagnostic command:

```bash
clawteam workspace doctor --repo <path>
```

It should report:

- is git repo
- repo root
- current branch
- HEAD validity
- candidate base ref
- worktree capability
- recommended spawn mode

### P1: Clarify autonomous execution contract

Owner: design/docs/CLI semantics

Required changes:

1. Document precisely what `spawn` guarantees and what it does not.
2. Make clear that task ownership alone does not mutate task state.
3. State what conditions are required for a spawned OpenClaw worker to begin acting autonomously.
4. Ensure the default path actually satisfies those conditions.

If the project intent is that spawned OpenClaw workers should begin work automatically from the injected task prompt, then the implementation must support that intent directly. It should not depend on undocumented manual `/deliver on` behavior.

## Version Management Requirements

The current version story is not acceptable.

Observed inconsistency:

- `pyproject.toml` declares one package version
- `clawteam/__init__.py` declares a different CLI version
- `clawteam --version` is not enough to distinguish this fork from other installed variants

Required changes:

### P0: Unify version truth

1. Define exactly one source of truth for package/runtime version.
2. Ensure package metadata, import version, and CLI version output are consistent.

### P0: Add explicit fork version identity

Use a version that identifies this fork, for example:

- `0.3.1+openclaw.1`

or another consistent, intentional scheme.

### P0: Improve `clawteam --version`

Make CLI version output explicit, for example:

```text
clawteam v0.3.1+openclaw.1
fork: ClawTeam-OpenClaw
```

### P1: Document upgrade/version policy

Update docs to define:

- patch bump rules
- minor bump rules
- fork suffix/local version rules
- how operators confirm which installed binary they are running

## Mandatory Smoke Test Strategy

The project must not rely on OpenClaw end-to-end usage as the first place where baseline clawteam behavior is validated.

Smoke tests must be layered.

### Layer 1: ClawTeam standalone smoke tests

These must validate ClawTeam itself without requiring full OpenClaw orchestration.

Required cases:

1. team create / discover / status
2. task create / list / update / wait
3. inbox send / receive / log
4. spawn default backend with a controlled fake/fixture command
5. spawn `--no-workspace`
6. workspace `auto` on healthy repo
7. workspace `auto` on unhealthy repo
8. workspace `always` failure path
9. board collector/server surfaces on spawned agents and tasks

### Layer 2: OpenClaw worker spawn smoke tests

Required cases:

1. `clawteam spawn --no-workspace` default OpenClaw worker path
2. verify the worker does not remain idle due to missing delivery
3. verify initial injected prompt reaches an actual provider-backed run
4. verify observable follow-up state appears within a timeout window

### Layer 3: Coding callback smoke tests

Required cases:

1. spawned worker triggers `clawteam coding exec claude ...`
2. coding job record is persisted
3. session record is persisted
4. callback report is persisted
5. worker emits leader-facing summary
6. leader-side inspection surfaces show durable results

### Layer 4: Board/operator smoke tests

Required cases:

1. `board show`
2. `board live`
3. `board serve --host 0.0.0.0`
4. coding/fault/timeline visibility
5. no misleading success surfaces when workers are idle or blocked

## Required Documentation Updates

Update all of the following after implementation:

- `README.md`
- `docs/runtime-console-operator-guide.md`
- `skills/openclaw/SKILL.md`
- `skills/clawteam/SKILL.md`

Specifically document:

- workspace modes and their real semantics
- when to use `--no-workspace`
- why OpenClaw scratch workspaces are not guaranteed to be valid project repos
- what a spawned OpenClaw worker needs in order to actually begin autonomous execution
- explicit version/fork identification
- remote board usage via `--host 0.0.0.0`

## Suggested Implementation Order

1. Fix OpenClaw tmux worker delivery (`--deliver` / correct worker mode)
2. Add workspace preflight and `auto` degradation behavior
3. Improve operator-facing spawn diagnostics
4. Unify and expose fork-aware versioning
5. Add smoke tests
6. Add `workspace doctor`
7. Update docs and skills

## Acceptance Criteria

This remediation is complete only when all of the following are true:

1. First install on a clean operator environment does not immediately stall on default-path assumptions.
2. `spawn --no-workspace` with default OpenClaw path produces an actually active worker, not just a visible tmux pane.
3. `workspace=auto` is safe and understandable.
4. operators can distinguish installed fork versions reliably.
5. smoke tests cover standalone clawteam behavior before OpenClaw-driven orchestration.
6. docs describe reality rather than idealized intent.

## Reviewer Position

The current system is still fundamentally promising, but these first-install failures are real product quality defects.

The correct response is not to hand-wave them as operator education issues.

The correct response is to:

- fix the default path
- add preflight checks
- make version identity explicit
- add mandatory smoke coverage
- tighten the documentation until the real behavior matches the stated model
