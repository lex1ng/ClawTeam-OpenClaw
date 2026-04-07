# External Skill Borrowing Integration Design

**Date:** 2026-04-07  
**Repository:** ClawTeam-OpenClaw  
**Status:** Proposed design  
**Audience:** System designer, implementation agent, and operator  
**Scope:** Define how ClawTeam-OpenClaw should selectively borrow ideas from three external multi-agent skills without weakening the current durable callback/runtime model

## 1. Executive Summary

Three external skills are especially relevant to the next phase of this project:

1. `agent-council`
2. `multi-agent-cn`
3. `agent-team-orchestration`

They are useful, but they are not substitutes for the current design direction.

The current project is building a durable multi-agent runtime with:

- explicit worker/team/main-leader callback closure
- lifecycle-hook-based failure awareness
- durable state as authority
- board/CLI/operator surfaces

The three external skills mainly contribute:

- better session-native communication patterns
- better fixed-team identity and session reuse patterns
- better handoff and task lifecycle structure

The correct strategy is:

- borrow their strong ideas
- preserve our stronger runtime authority model
- never regress into prompt-only orchestration

## 2. The Three Skills And What They Actually Offer

### 2.1 `agent-council`

Most relevant strengths:

- OpenClaw-native session communication
- direct delegation between agents
- programmatic spawning
- isolated agent workspaces
- optional Discord-bound specialist sessions
- memory/shared-knowledge patterns

What it appears to optimize for:

- flexible collaboration between live sessions
- session-native delegation
- autonomy and specialist agents

What it does **not** appear to offer as a primary design goal:

- durable callback state as authority
- explicit runtime fault provenance model
- operator-grade board/CLI truth separation

### 2.2 `multi-agent-cn`

Most relevant strengths:

- fixed persistent sub-agent set
- fixed identity and role split
- session reuse
- manager dispatch discipline
- explicit behavioral constraints for multi-agent turn-taking

What it appears to optimize for:

- persistent reusable teams
- stable specialist identities
- predictable manager -> member delegation

What it does **not** appear to offer as a primary design goal:

- hook-driven fault truth
- durable callback graph across levels
- strong operator surfaces

### 2.3 `agent-team-orchestration`

Most relevant strengths:

- stronger handoff discipline
- task lifecycle framing
- role-oriented work progression
- explicit movement from assignment to execution to review

What it appears to optimize for:

- better work transfer quality
- less ambiguous ownership handoff
- more structured lifecycle progression

What it does **not** appear to offer as a primary design goal:

- runtime-console-grade persistent observability
- durable callback/fault truth
- session-native runtime control model

## 3. Current Project Position

The current project is already stronger than these skills in one key dimension:

- durable runtime truth

That means this project must **not** borrow their weaker assumptions.

It should only borrow what is missing:

1. session-native communication acceleration
2. fixed reusable team identity model
3. stronger handoff and lifecycle contracts

## 4. Borrowing Strategy

Borrow selectively in three lanes.

### Lane A: Session-Native Communication

Borrow from:

- `agent-council`

### Lane B: Fixed Team Identity And Session Reuse

Borrow from:

- `multi-agent-cn`

### Lane C: Strong Handoff And Lifecycle Contracts

Borrow from:

- `agent-team-orchestration`

These three lanes must integrate into the current system, not replace it.

## 5. Lane A: Borrow From `agent-council`

## 5.1 What To Borrow

Borrow these ideas:

- OpenClaw-native session-to-session messaging
- direct specialist messaging paths
- session-native delegation as an acceleration path
- optional direct channel/thread-bound specialists
- per-agent workspace/memory concepts where useful

## 5.2 Why It Is Valuable

This project currently treats durable state as authority.

That is correct, but live session communication is still underpowered.

Borrowing from `agent-council` helps with:

- faster worker -> team leader live notification
- faster team leader -> main leader live notification
- richer direct specialist interaction
- better Discord/channel integration for fixed specialists

## 5.3 What Not To Borrow

Do **not** borrow these assumptions:

- session messaging as sole truth
- memory files as substitute for runtime state
- live session text as substitute for callback records

## 5.4 Correct Integration Pattern

Use OpenClaw-native session messaging as an acceleration path, not as authority.

Correct pattern:

```text
OpenClaw session/native message
    -> optional fast delivery
    -> durable callback/fault/timeline write
    -> board/CLI truth
```

Not this:

```text
OpenClaw session/native message
    -> implicit success
    -> no durable callback
```

## 5.5 Design Requirements

Introduce a session bridge layer that can:

- send worker -> team leader structured notices
- send team leader -> main leader structured notices
- optionally attach session identity and routing hints
- write the same event into durable runtime state

Session-native messages must be treated as:

- low-latency transport

not:

- final source of truth

## 5.6 Recommended Deliverables

- session bridge abstraction
- worker session routing metadata
- leader session routing metadata
- optional Discord/channel binding metadata on team members
- board-visible live-session linkage fields

## 6. Lane B: Borrow From `multi-agent-cn`

## 6.1 What To Borrow

Borrow these ideas:

- fixed reusable team
- fixed member nicknames
- fixed role split
- stable session reuse identity
- manager dispatch discipline
- “company-like” team identity

## 6.2 Why It Is Valuable

This directly matches the target operating model:

- a product gets a relatively fixed team
- members have stable names
- members have stable specialties
- teams are reused rather than re-created per task

This improves:

- operator comprehension
- team memory
- stable ownership
- repeatability
- session routing predictability

## 6.3 What Not To Borrow

Do **not** borrow these weaker assumptions:

- implicit runtime truth living only in reused sessions
- manager discipline without durable callback closure
- fixed team without explicit task/callback/fault records

## 6.4 Correct Integration Pattern

Introduce a reusable team profile model.

Example concept:

```text
product/team profile
  -> fixed team id
  -> fixed member roster
  -> fixed nickname
  -> fixed role
  -> preferred backend/provider
  -> preferred session routing key
```

This profile should be durable and inspectable.

It should not exist only in prompt text.

## 6.5 Recommended Durable Model

Add or extend durable team metadata with:

- `teamProfileId`
- `teamPurpose`
- `productKey`
- `memberNickname`
- `memberDisplayName`
- `memberRole`
- `preferredSessionKey`
- `preferredChannelBinding`
- `teamReusePolicy`

## 6.6 Human-Facing Identity Rule

`nickname` must be treated as a human-facing identity only.

This is important for operator experience:

- the user should feel like they are managing a real team
- members should have recognizable names
- the board and CLI should feel more like a company/team view than a machine id list

However:

- `nickname` must not be used as runtime authority
- `nickname` must not be used as callback linkage identity
- `nickname` must not be used as session routing authority

Correct split:

### Human-Facing Identity

- `memberNickname`
- `memberDisplayName`
- `memberRole`

### Machine-Facing Identity

- `memberId`
- `agentId`
- `preferredSessionKey`
- task/job/callback/fault ids

Recommended display pattern:

- `Hypatia (reviewer)`
- `Turing (backend)`
- `Noether (team-leader)`

Recommended allocation pattern:

- choose from a curated name pool by default
- ensure uniqueness inside a team
- persist once assigned
- allow manual override
- do not rotate names on every spawn

This should create a stronger “company/team” feeling for the operator without weakening the system model.

## 6.7 Recommended Behavior

The orchestrator/main leader should be able to:

- create a team profile once
- instantiate or attach to a reusable live team
- route new work to the same fixed members
- preserve stable team identity across missions

## 6.8 Recommended Deliverables

- reusable team profile schema
- nickname fields on members
- display-name derivation rules
- session routing key fields
- stable team template creation/update CLI
- board support for showing nicknames, roles, session bindings

## 7. Lane C: Borrow From `agent-team-orchestration`

## 7.1 What To Borrow

Borrow these ideas:

- stronger handoff contract
- stronger task lifecycle naming
- less ambiguous transfer between roles
- more explicit review stage semantics

## 7.2 Why It Is Valuable

The current project is already moving toward:

- `MISSION.md`
- `TEAM_SPEC.md`
- `WORKER_SPEC.md`
- `RESULT.md`
- `STATUS.json`

This lane strengthens that direction.

It makes the system less dependent on free-form natural language and makes team transfer more professional.

## 7.3 What Not To Borrow

Do **not** borrow these weaker assumptions:

- prompt-only handoff without durable result files
- generic lifecycle labels without callback semantics
- review as prose only rather than structured state

## 7.4 Correct Integration Pattern

Extend the current contract-file design with a formal handoff block.

Recommended handoff structure:

- task identity
- owner
- role
- objective
- inputs consumed
- outputs produced
- validation/self-test performed
- blockers/risks
- recommendation/next-step
- callback expectation

## 7.5 Recommended Lifecycle

Recommended lifecycle terms for durable state:

- `drafted`
- `assigned`
- `claimed`
- `executing`
- `awaiting_callback`
- `reported`
- `awaiting_review`
- `approved`
- `blocked`
- `failed`
- `completed`

Important:

These lifecycle terms must remain compatible with the callback model.

That means:

- worker completion is not team completion
- review completion is not main-leader reporting
- callback phases must stay explicit

## 7.6 Recommended Deliverables

- stronger handoff template embedded in spec/result docs
- richer lifecycle enum or equivalent phase model
- board/CLI rendering for lifecycle phase vs callback state
- validation rules that reject incomplete handoff artifacts

## 8. Unified Target Architecture After Borrowing

The borrowed ideas should land in this architecture:

```text
[User]
   |
   v
[Main Leader / Orchestrator]
   |
   | reusable fixed team selection
   v
[Team Leader]
   |
   | strong handoff contract
   +-----------------------+-----------------------+
   |                       |                       |
   v                       v                       v
[Worker A]             [Worker B]             [Worker C]
 nickname/role         nickname/role          nickname/role
 session key           session key            session key
   |                       |                       |
   | session-native message acceleration           |
   +-------------------+---------------------------+
                       |
                       v
             [Durable callback / fault / timeline]
                       |
                       v
               [Board / CLI / Operator View]
```

The critical rule remains:

- live session communication accelerates
- durable state authorizes

## 9. What This Project Should Explicitly Avoid

Avoid these mistakes:

### 9.1 Do Not Regress To Prompt-Only Orchestration

Do not make:

- session text
- memory files
- Discord messages
- role prompts

the primary source of truth.

### 9.2 Do Not Let Session Reuse Hide State

Session reuse is useful.

But reused sessions must still expose:

- callback truth
- task linkage
- fault truth
- lifecycle truth

### 9.3 Do Not Collapse Handoff Into Chat

Handoff should remain:

- explicit
- inspectable
- durable

### 9.4 Do Not Copy Their Surface Simplicity At The Cost Of Reliability

These skills are useful references.

They are not stronger than the current project on:

- runtime authority
- callback closure
- fault provenance
- operator surfaces

## 10. Recommended Implementation Order

Implement in this order.

### Phase 1: Fixed Team Identity

From `multi-agent-cn`

Deliver:

- reusable team profiles
- stable nicknames
- stable roles
- stable session routing metadata

### Phase 2: Handoff And Lifecycle Hardening

From `agent-team-orchestration`

Deliver:

- stronger handoff templates
- stronger lifecycle phases
- board/CLI display of lifecycle vs callback state

### Phase 3: Session Bridge

From `agent-council`

Deliver:

- OpenClaw-native session bridge
- live structured upward notices
- direct specialist routing support

### Phase 4: Channel/Thread Binding

Primarily inspired by `agent-council`

Deliver:

- optional member -> Discord channel/thread binding metadata
- optional fixed specialist-to-channel routing

## 11. Expected Benefits

After integrating these three borrowing lanes correctly, the system should gain:

- more human-comprehensible fixed teams
- better company-like team identity
- better live session communication
- better work transfer quality
- more explicit lifecycle and ownership
- no loss of durable runtime truth

## 12. Final Design Judgment

These three skills are worth borrowing from.

But they should be treated as:

- pattern libraries

not:

- replacement architectures

The current project should remain a durable orchestration runtime first.

The borrowed ideas should make it:

- more ergonomic
- more reusable
- more natural to operate

without making it less correct.

## 13. Direct Instruction To Agent

```text
Read:
1. docs/design/specs/2026-04-07-external-skill-borrowing-integration-design.md

Use this document as a design input only.

Do not immediately implement every lane at once.

The correct borrowing priorities are:
1. fixed team identity and nickname/session reuse
2. stronger handoff and lifecycle contracts
3. session-native communication bridge

Do not weaken:
- durable state authority
- callback closure
- fault provenance
- board/CLI truth model

When planning implementation, explicitly separate:
- what is authority
- what is acceleration
- what is evidence
- what is human-readable workflow guidance
```
