# External Skill Borrowing Implementation Tasking

**Date:** 2026-04-07  
**Audience:** Coding agent implementing the next feature layer  
**Primary Spec:** [External Skill Borrowing Integration Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-07-external-skill-borrowing-integration-design.md)

## 1. Goal

Implement the first practical borrowing layer from:

- `multi-agent-cn`
- `agent-team-orchestration`
- `agent-council`

without weakening the existing durable runtime/callback/fault/operator model.

This work is not a rewrite.

It is a structured extension.

## 2. Non-Negotiable Constraints

- durable state remains authority
- callback/fault/timeline truth must remain machine-facing and id-based
- nickname is human-facing only
- session-native messaging is acceleration, not source of truth
- handoff contracts must become stronger, not more free-form
- do not implement all borrowing lanes at once without staging

## 3. Required Reading

Read these before coding:

1. [External Skill Borrowing Integration Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-07-external-skill-borrowing-integration-design.md)
2. [Multi-Level Task Callback System Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-multi-level-task-callback-system-design.md)
3. [OpenClaw Native Failure Reporting Integration Design](/root/github.com/ClawTeam-OpenClaw/docs/design/specs/2026-04-06-openclaw-native-failure-reporting-integration-design.md)

## 4. Implementation Phases

Implement in this order.

### Phase 1: Fixed Team Identity Layer

Inspired by:

- `multi-agent-cn`

Required deliverables:

- reusable team profile model
- fixed team metadata
- stable member nickname field
- stable member role field
- stable preferred session key field
- machine-facing vs human-facing identity split

Required semantics:

- nickname is for human/operator display only
- member/session/task/job/callback linkage must remain id-based
- nickname must persist across team reuse
- nickname must not change on every spawn

Recommended fields:

- `teamProfileId`
- `productKey`
- `memberNickname`
- `memberDisplayName`
- `memberRole`
- `preferredSessionKey`
- `teamReusePolicy`

Acceptance:

- a product/team can be configured once and reused
- board/CLI can show nickname + role cleanly
- durable records continue to use real ids

### Phase 2: Stronger Handoff And Lifecycle Contracts

Inspired by:

- `agent-team-orchestration`

Required deliverables:

- stronger worker/team handoff template
- lifecycle phase expansion or equivalent durable phase model
- clearer distinction between:
  - task lifecycle
  - callback lifecycle
  - review lifecycle

Minimum handoff fields:

- task identity
- objective
- inputs
- outputs
- validation/self-test
- blockers
- risks
- recommended next step
- callback expectation

Acceptance:

- worker/team result artifacts are more explicit
- board/CLI can surface lifecycle phase separately from callback state
- incomplete handoff artifacts are detectable

### Phase 3: Session Bridge Preparation

Inspired by:

- `agent-council`

Required deliverables:

- design-compatible session routing metadata on members
- session bridge abstraction placeholder or first implementation slice
- optional direct worker->leader live notice support design hooks

Important:

This phase must not replace durable callback.

Acceptance:

- codebase is prepared for session-native acceleration
- durable truth model remains unchanged

## 5. Recommended File Targets

Likely implementation areas:

- `clawteam/team/`
- `clawteam/cli/commands.py`
- `clawteam/board/collector.py`
- `clawteam/board/static/index.html`
- `clawteam/runtime_console/`
- `README.md`
- `docs/runtime-console-operator-guide.md`
- `tests/`

## 6. Test Requirements

Add or update tests for:

### Team Identity

- nickname persists across team reuse
- nickname uniqueness inside a team
- nickname changes do not break machine-facing linkage
- board/CLI render nickname and role without replacing ids internally

### Handoff / Lifecycle

- worker/team handoff artifacts include required sections
- lifecycle phase distinguishes execution vs callback vs review
- incomplete handoff remains detectable

### Session Metadata

- preferred session key persists on team members
- board/CLI expose session-routing metadata honestly
- no callback linkage depends on nickname

## 7. Validation Commands

At minimum, run and report:

```bash
python -m pytest tests/test_board_collector.py tests/test_board_server.py tests/test_board_web_ui.py -q
python -m pytest tests/test_smoke_clawteam_full_chain.py tests/test_smoke_openclaw_integration.py tests/test_coding_integration.py -q
```

Add any new team-profile / lifecycle / identity tests explicitly.

## 8. Reporting Format

When done, report back in exactly this structure:

1. files changed
2. phases completed
3. new durable fields / models introduced
4. nickname/session/lifecycle semantics now supported
5. commands run
6. pass/fail summary
7. residual risks

## 9. Direct Instruction To Agent

```text
Read:
1. docs/design/specs/2026-04-07-external-skill-borrowing-integration-design.md
2. docs/agent/plans/2026-04-07-external-skill-borrowing-implementation-tasking.md

Implement in this order:
1. fixed team identity + nickname/session reuse metadata
2. stronger handoff/lifecycle contracts
3. session bridge preparation only

Important:
- nickname is human-facing only
- machine-facing linkage remains id/session-key based
- durable state remains authority
- do not turn session-native communication into the source of truth

Report back with:
1. files changed
2. phases completed
3. new durable fields / models introduced
4. nickname/session/lifecycle semantics now supported
5. commands run
6. pass/fail summary
7. residual risks
```
