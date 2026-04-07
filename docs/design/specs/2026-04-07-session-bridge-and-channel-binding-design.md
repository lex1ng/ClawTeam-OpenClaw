# Session Bridge And Channel Binding Design

**Date:** 2026-04-07  
**Repository:** ClawTeam-OpenClaw  
**Status:** Proposed design  
**Audience:** System designer, implementation agent, and operator  
**Scope:** Define the future OpenClaw-native session communication bridge and optional channel/thread binding model without weakening durable callback, fault, task, or board truth

## 1. Goal

Define a session-native communication layer that improves live coordination speed while keeping all authoritative state in ClawTeam durable storage.

This design covers:

- worker -> team leader live notices
- team leader -> main leader live notices
- optional direct specialist routing
- optional Discord/channel/thread bindings on members
- failure and recovery behavior when live delivery and durable writes diverge

This design does not authorize live session traffic or external channels to become the source of truth.

## 2. Executive Summary

ClawTeam should add a **session bridge** that uses OpenClaw-native session messaging as a low-latency transport for structured notices between live sessions.

The bridge is useful for:

- fast escalation
- fast attention routing
- faster leader awareness
- optional specialist coordination

The bridge is not useful as authority.

Authoritative state must remain in durable ClawTeam records:

- callback records
- runtime fault records
- task/runtime state
- timeline events
- operator board and CLI data models derived from those records

Optional Discord/channel/thread bindings should be modeled as durable member metadata and routing preferences only. They may receive mirrored notices or host a bound specialist session, but they must never be required for correctness.

## 3. Design Principles

### 3.1 Durable Authority First

Any event that changes business truth must be represented durably even if a live message is also sent.

### 3.2 Session Bridge Is Acceleration Only

Live notices are advisory transport for speed. They are not callback closure, task completion, or fault truth by themselves.

### 3.3 Channel Binding Is Optional

Discord or any future channel identity is an optional routing attachment. The system must continue to function if no channel is bound or if the channel is unavailable.

### 3.4 Human Identity And Machine Identity Must Stay Separate

Nicknames and display names improve operator experience. They must not be used for routing authority, callback linkage, or fault provenance.

### 3.5 Evidence Must Be Preserved

Live sends, hook observations, watchdog observations, and delivery outcomes are evidence. They should inform diagnosis and retries, but authority still comes from durable records.

## 4. Core Model

### 4.1 Session Bridge Role

The session bridge is a system component that:

- resolves a target live session from durable routing metadata
- emits a small structured notice
- records delivery outcome as evidence
- supports retry or fallback behavior when delivery fails

The session bridge is **for**:

- low-latency worker -> leader structured notice
- low-latency leader -> main leader structured notice
- optional direct specialist routing for bounded coordination
- advisory live delivery of already-classified runtime events

The session bridge is **not for**:

- replacing callback records
- replacing runtime fault records
- storing durable task status
- becoming the only copy of operational state
- routing by nickname alone
- carrying large artifacts as the only copy of results

### 4.2 Notice Types

The bridge should send only bounded, structured notice classes.

Recommended initial notice families:

- `callback_attention_needed`
- `callback_report_ready`
- `runtime_fault_notice`
- `startup_stalled_notice`
- `escalation_notice`
- `specialist_help_request`
- `specialist_response_ready`

These notices should contain references to durable records, not become substitutes for them.

### 4.3 Notice Envelope

Recommended logical envelope:

```text
bridgeNotice {
  schemaVersion
  noticeId
  noticeType
  teamId
  sourceMemberId
  sourceSessionId
  targetMemberId
  targetRoutingKey
  durableRef {
    callbackId?
    faultId?
    taskId?
    timelineEventId?
  }
  evidenceRef {
    hookEventId?
    watchdogEventId?
  }
  createdAt
  expiresAt
  deliveryPolicy
  payloadSummary
}
```

Rules:

- payloads stay small and structured
- durable ids are preferred over free text
- artifacts such as `RESULT.md` remain durable file references, not embedded content
- every notice must be safe to ignore without losing authoritative truth

## 5. Durable Companion Writes

### 5.1 Required Rule

If a business event matters, a durable write must exist independently of live delivery.

### 5.2 Recommended Ordering

The safe ordering is:

```text
classify event
  -> write durable authority record
  -> append timeline/evidence record
  -> attempt live bridge send
  -> record delivery result as evidence
```

This is effectively a durable-first or outbox-like pattern. It minimizes the chance that live transport outruns authority.

### 5.3 What Must Be Durable

Typical companion records:

- callback status transitions
- runtime fault records
- task blockage/escalation state
- timeline events for sequencing
- bridge delivery attempt evidence

The bridge may reference these writes, but it must not replace them.

## 6. When A Live Session Message Should Be Sent

A live bridge notice should be sent only when all of the following are true:

1. a human or upstream agent benefits from lower latency than polling durable state
2. the event has already been classified enough to produce a stable structured notice
3. the event has a durable reference or is about to get one in the same workflow
4. the target has an active routable session or a delivery attempt is worth making

Recommended send cases:

- worker reports callback ready and leader should react immediately
- worker hits a fault or stall condition requiring leader attention
- team leader must rapidly notify main leader of degraded team state
- a specialist needs direct involvement for a bounded issue

Do not send live bridge traffic for:

- ordinary progress chatter already visible on board/CLI
- large result payloads
- state transitions that do not yet have stable durable meaning
- anything that would be harmful if the live notice were dropped

## 7. Failure Matrix For Live And Durable Paths

### 7.1 Live Message Fails But Durable Write Succeeds

Durable truth wins.

Required behavior:

- keep the authoritative durable record
- append bridge delivery failure evidence
- surface the issue on board/CLI as a delivery failure or missing live reachability
- allow retry if session routing remains valid
- fall back to other derived operator surfaces if appropriate

No callback, fault, or task state should be rolled back because live delivery failed.

### 7.2 Live Message Succeeds But Durable Write Fails

This is the dangerous case and the system must be designed to make it rare.

Required rule:

- receiver must treat the live notice as advisory only until durable truth exists

Required behavior:

- do not let receipt of the live notice mutate authoritative callback or task state by itself
- mark the notice as `unbacked` or equivalent transient evidence if no durable reference can be resolved
- attempt durable reconciliation immediately
- if reconciliation fails, surface an authority-gap warning

Implementation target:

- design the sender path so durable write happens first or is staged before send
- do not normalize a bridge-first flow into the steady-state architecture

## 8. Channel And Thread Binding Model

### 8.1 Purpose

Channel/thread binding allows a team member to declare an optional external communication attachment such as:

- Discord channel
- Discord thread
- future Slack room, Telegram chat, or other channel identity

Bindings support:

- operator visibility
- stable specialist placement
- mirrored notice delivery
- optional human-aware routing context

Bindings do not define authority and do not replace durable state.

### 8.2 Durable Binding Fields

Recommended durable binding record:

```text
memberChannelBinding {
  bindingId
  memberId
  teamId
  teamProfileId?
  bindingKind            // discord_channel | discord_thread | future value
  provider               // discord | slack | telegram | future value
  externalWorkspaceId?   // e.g. guild/server/workspace
  externalChannelId
  externalThreadId?
  externalIdentityKey    // stable provider-specific identity string
  displayLabel
  routePolicy            // mirror_only | preferred_notice_sink | bound_specialist_home
  preferredNoticeTypes[] // optional subset
  state                  // proposed | verified | active | suspended | revoked
  verificationStatus
  createdAt
  updatedAt
  createdBy
  lastVerifiedAt?
  lastDeliveryAt?
  lastDeliveryResult?
}
```

### 8.3 Binding Semantics

Rules:

- a member may have zero, one, or multiple bindings
- bindings are optional
- one binding may be marked preferred for a specific notice class
- bindings are attachments to a member identity, not replacements for member identity
- bindings may be inherited from a reusable team profile and then materialized on a live team

### 8.4 Lifecycle

Recommended lifecycle:

1. `proposed`
2. `verified`
3. `active`
4. `suspended`
5. `revoked`

Behavior:

- `proposed` means configured but not trusted
- `verified` means syntax and reachability were confirmed
- `active` means routable for optional mirrored notices or specialist placement
- `suspended` means temporarily disabled without deleting history
- `revoked` means no longer usable but preserved historically

Bindings should be historical records, not mutable magic pointers with no audit trail.

### 8.5 Routing Rules

Primary routing order should be:

1. durable member identity and effective session routing key
2. active live session resolution
3. optional bound channel/thread mirror or specialist-home route according to policy
4. operator-visible fallback if no live or external route succeeds

Important constraints:

- callback authority still comes from durable callback records
- a channel-bound specialist is still represented as a normal ClawTeam member with durable ids
- external channel delivery is optional side transport
- routing decisions must use member ids and routing keys, not nickname text

### 8.6 Bound Specialist Model

If a specialist is intentionally associated with a Discord thread or channel, the member should still have:

- `memberId`
- `memberRole`
- `preferredSessionKey` or routing slot
- optional binding records

The thread or channel is where the specialist is expected to communicate, not what the specialist fundamentally is.

## 9. Identity Split

### 9.1 Human-Facing Identity

Human-facing fields:

- `memberNickname`
- `memberDisplayName`
- `memberRole`

These exist for operator comprehension and team continuity.

### 9.2 Machine-Facing Identity

Machine-facing fields:

- `teamId`
- `teamProfileId`
- `memberId`
- `agentId`
- `preferredSessionKey`
- effective session routing key
- `taskId`
- `callbackId`
- `faultId`

### 9.3 Identity Rule

Nickname must never become routing authority.

That means:

- no callback linkage by nickname
- no session targeting by nickname
- no durable reconciliation keyed only by display name

Board and CLI should show human-facing names prominently, but machine ids must remain available for diagnosis.

## 10. Stable Session Routing Keys And Reusable Team Profiles

Reusable team profiles should define **stable routing slots**, not raw session ids.

Recommended split:

- `teamProfileId` defines the reusable team template
- each stable member slot in that profile gets a `preferredSessionKey` or routing slot
- a live team instance resolves that slot to an effective active session

Conceptually:

```text
team profile member slot
  -> preferredSessionKey = profile.research.backend
  -> live team memberId = tm_member_017
  -> current sessionId = sess_abc123
```

The stable routing key should relate to reusable profiles like this:

- profile owns the stable routing slot
- live team member owns the durable member identity
- current session id is ephemeral attachment to that member and slot

If concurrent live instances of the same profile are ever supported, the implementation must scope effective routing by live `teamId` so profile-level slots do not collide.

## 11. Authority Vs Acceleration Vs Evidence

### 11.1 Durable Authority

Authoritative records:

- callback records and states
- runtime fault records
- task/runtime state
- team/member durable metadata
- timeline entries designated as business truth

Only these records should drive official board/CLI state transitions.

### 11.2 Session Acceleration

Acceleration mechanisms:

- OpenClaw native session notices
- direct specialist routing
- optional mirrored external channel delivery

These improve reaction time only.

### 11.3 Evidence

Evidence records:

- hook observations
- watchdog observations
- bridge delivery attempts
- bridge delivery success/failure outcomes
- receiver acknowledgements
- missing-route and expired-route diagnostics

Evidence helps explain what happened. Evidence does not replace authority.

## 12. Failure And Recovery Interaction

### 12.1 Hook Faults

Hook faults should be classified into durable runtime fault or timeline truth first.

Then:

- bridge may send a live notice upward if a target session exists
- delivery result should be recorded as evidence

### 12.2 Watchdog Faults

Watchdog signals such as startup stall or no-progress should follow the same rule:

- durable classification first
- live notice second

### 12.3 Callback Reporting

Bridge delivery does not satisfy callback reporting requirements.

Examples:

- a worker may send `callback_report_ready`, but callback closure still requires the durable callback record
- a leader may send `escalation_notice`, but main-leader truth still depends on the durable aggregate callback/fault state

### 12.4 Missing Or Failed Session Delivery

When session delivery cannot be completed:

- preserve durable authority record
- record delivery failure evidence
- optionally retry if routing is still valid
- surface degraded reachability on board/CLI
- allow operator or watchdog reconciliation

### 12.5 Receiver Recovery

Receivers should treat bridge messages as hints that help them look up durable truth.

If the referenced durable record is missing:

- keep the message as transient evidence only
- do not finalize business state from it
- request or await reconciliation

## 13. Operator Surface Requirements

### 13.1 Board And CLI Representation

Channel/thread-bound specialists should appear as normal members with extra routing metadata.

Recommended display fields:

- nickname and role
- durable member id
- preferred session key
- current session reachability state
- bound channel/thread label if active
- binding state
- last bridge delivery result if relevant

Example:

```text
Hypatia (reviewer)
memberId=tm_member_017
sessionKey=profile.research.reviewer
session=active
binding=discord_thread:#api-review / thread 128734...
bindingState=active
```

### 13.2 Visual Semantics

Board/CLI should make the split obvious:

- callback/fault/task state shown as authoritative
- session reachability and bridge delivery shown as transport status
- channel/thread binding shown as optional attachment

This prevents operators from mistaking a green channel route for callback closure.

## 14. Required Question Answers

### 14.1 When Should A Live Session Message Be Sent?

Send when rapid awareness materially helps and the event already has durable meaning or an immediately-following durable write.

### 14.2 What Durable Write Must Accompany Or Follow It?

At minimum, the relevant callback record, runtime fault record, task/escalation state, or timeline event must exist. Delivery attempt/result should also be written as evidence.

### 14.3 What Happens If The Live Message Fails But Durable Write Succeeds?

Durable truth remains valid. Record delivery failure, surface degraded reachability, and retry or fall back without changing authoritative state.

### 14.4 What Happens If The Live Message Succeeds But Durable Write Fails?

Receiver must treat the live message as advisory only. Do not let it finalize authoritative state. Trigger reconciliation and surface an authority-gap warning.

### 14.5 How Should Channel/Thread-Bound Specialists Be Represented On Board/CLI?

As ordinary durable members with normal ids, roles, and routing keys plus optional binding metadata, binding state, and transport health.

### 14.6 How Should Stable Session Routing Keys Relate To Reusable Team Profiles?

Reusable profiles should own stable routing slots. Live teams should resolve those slots to active sessions through durable member identity. Session ids stay ephemeral.

## 15. Recommended Implementation Warning

The most important warning is this:

**Do not let bridge receipt or channel activity flip callback, task, or fault state by itself.**

If implementation allows a live message, Discord thread post, or specialist acknowledgement to count as authoritative completion, the system will regress from durable runtime truth into transport-dependent orchestration.

## 16. Final Design Judgment

The correct architecture is:

```text
durable classification and authority
  -> optional live session acceleration
  -> optional channel/thread mirroring
  -> operator-visible evidence and recovery
```

Not:

```text
live session or Discord activity
  -> implied business truth
```

That separation is the key condition for adding session-native speed without losing operator-grade correctness.
