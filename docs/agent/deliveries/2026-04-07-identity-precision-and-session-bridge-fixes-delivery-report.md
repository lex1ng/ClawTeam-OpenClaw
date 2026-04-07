# Identity Precision and Session Bridge Fixes Delivery Report

**Date:** 2026-04-07  
**Scope:** Post-review hardening for identity precision, nickname uniqueness safety, and session-bridge fail-safe behavior.

## Background
The previous implementation added fixed team identity metadata, lifecycle/handoff contracts, and session-bridge preparation. Review found three correctness gaps that could break machine-facing identity guarantees in same-name/different-user scenarios.

## Findings Closed
This delivery closes the following review findings:

1. `TaskStore.record_coding_callback()` session-bridge member binding could select wrong member using `name`-only matching.
2. `TeamManager.update_member_profile()` nickname uniqueness check could be bypassed for same-name members due to `ignore_member=name` logic.
3. `update_member_profile(preferred_session_key=...)` could leave `session_routing.preferredSessionKey` stale.

## Files Changed
- `clawteam/team/tasks.py`
- `clawteam/team/manager.py`
- `tests/test_external_skill_borrowing_integration.py`
- `tests/test_manager.py`
- `README.md`
- `docs/runtime-console-operator-guide.md`

## Exact Semantic Fixes
### 1) Session bridge machine-identity binding
- Callback flow now resolves worker member using machine identity first (`job.worker_id -> member.agent_id`), not `worker_name` fuzzy matching.
- Added `TeamManager.get_member_by_identity()` with explicit resolution order: `member_id` -> `agent_id` -> `preferred_session_key` -> unique name fallback.
- `SessionBridgeNotice` is created only when worker and leader can be resolved safely.

### 2) Nickname uniqueness strictness
- Nickname uniqueness ignore logic changed from `ignore_member=name` to `ignore_member_id=member_id`.
- Same-name members under different users are no longer incorrectly skipped by uniqueness checks.

### 3) preferredSessionKey / sessionRouting consistency
- When `preferred_session_key` is updated and caller does not explicitly provide `session_routing`, manager now synchronizes `session_routing["preferredSessionKey"]` automatically.
- Explicit `session_routing` still takes precedence when provided by caller.

### 4) Identity-safe ambiguity behavior (fail-safe)
- `update_member_profile()` returns `None` when target is ambiguous (same name across users and no user supplied).
- `remove_member()` now avoids destructive guessing:
  - with `user`: exact `(name,user)` removal
  - without `user`: remove only when name is unique, otherwise refuse.

## Tests Added/Updated
### Added
- `tests/test_external_skill_borrowing_integration.py::test_session_bridge_skips_notice_when_machine_identity_missing_and_name_ambiguous`
- `tests/test_manager.py::test_update_member_profile_returns_none_when_name_ambiguous_without_user`

### Updated/Existing coverage used
- `tests/test_external_skill_borrowing_integration.py::test_session_bridge_binds_member_by_machine_identity_not_ambiguous_name`
- `tests/test_manager.py::test_update_member_profile_rejects_nickname_conflict_for_same_name_different_user`
- `tests/test_manager.py::test_update_member_profile_syncs_routing_preferred_session_key`

## Commands Run
- `python -m pytest tests/test_manager.py tests/test_external_skill_borrowing_integration.py tests/test_tasks.py -q`
- `python -m pytest tests/test_coding_integration.py tests/test_board_collector.py tests/test_board_server.py tests/test_runtime_console_cli.py tests/test_team_status_cli.py -q`

## Pass/Fail Summary
- `tests/test_manager.py tests/test_external_skill_borrowing_integration.py tests/test_tasks.py`: **80 passed**
- `tests/test_coding_integration.py tests/test_board_collector.py tests/test_board_server.py tests/test_runtime_console_cli.py tests/test_team_status_cli.py`: **29 passed**
- Overall in this hardening round: **109 passed, 0 failed**

## Residual Risks
- If upstream job persistence omits machine identity fields entirely and names are ambiguous, bridge notice emission is skipped (intentional fail-safe). Operators may see fewer bridge notices in degraded metadata scenarios.
- CLI member updates still rely on `(name,user)` scoping; there is no first-class `memberId` CLI selector yet.

## Open Follow-ups
1. Add optional `--member-id` support to identity-sensitive CLI commands (`team update-member` and future remove-member command) to avoid name/user ambiguity entirely.
2. Expose “bridge notice skipped due to ambiguity” as explicit runtime telemetry to aid operator diagnostics.
3. Expand API/docs examples for multi-user same-name teams with strict machine-facing routing expectations.
