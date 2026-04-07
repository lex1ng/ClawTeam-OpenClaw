"""Aggregates durable team/runtime state into board/API/CLI payloads."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from clawteam.coding import ACTIVE_CODING_JOB_STATES, CodingJobStore
from clawteam.runtime_console import RuntimeConsoleStore
from clawteam.runtime_console.service import RuntimeConsoleService
from clawteam.spawn.registry import is_agent_alive
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import get_data_dir
from clawteam.team.tasks import TaskStore


_EVIDENCE_DEFAULT_MAX_CHARS = 1800
_EVIDENCE_DEFAULT_LIMIT = 80
_EVIDENCE_DEFAULT_ARTIFACT_LIMIT = 40


class BoardCollector:
    """Aggregates team/task/runtime data into plain dict payloads."""

    def _dump_model(self, model) -> dict:
        return json.loads(model.model_dump_json(by_alias=True, exclude_none=True))

    def _jobs_with_faults(self, team_name: str) -> tuple[list, list[dict]]:
        return CodingJobStore().inspect_jobs(team_name)

    def _runtime_sessions_with_faults(self, team_name: str) -> tuple[list, list[dict]]:
        return RuntimeConsoleStore().inspect_provider_sessions(team_name)

    def _runtime_callbacks_with_faults(self, team_name: str) -> tuple[list, list[dict]]:
        return RuntimeConsoleStore().inspect_callback_reports(team_name)

    def _runtime_faults_with_faults(self, team_name: str) -> tuple[list, list[dict]]:
        return RuntimeConsoleStore().inspect_faults(team_name)

    def _runtime_timeline_with_faults(self, team_name: str) -> tuple[list, list[dict]]:
        return RuntimeConsoleStore().inspect_timeline(team_name)

    def _runtime_evidence_with_faults(self, team_name: str) -> tuple[list, list[dict]]:
        return RuntimeConsoleStore().inspect_evidence(team_name)

    def _tasks_with_faults(self, team_name: str) -> tuple[list, list[dict]]:
        return TaskStore(team_name).inspect_tasks()

    def _normalize_read_fault(self, fault: dict, *, detected_at: str = "") -> dict:
        payload = dict(fault)
        payload.setdefault("faultId", payload.get("recordId") or self._stable_id("read-fault", payload))
        payload.setdefault("severity", "warning")
        payload.setdefault("status", "open")
        payload.setdefault("scopeType", "runtime")
        payload.setdefault("scopeId", payload.get("recordKind", "durable_state"))
        payload.setdefault("detectedAt", detected_at)
        payload["provenance"] = "read-fault"
        payload.setdefault("reportedUpward", False)
        payload.setdefault("escalationStatus", "not_applicable")
        return payload

    def _fault_provenance(self, fault: dict) -> str:
        explicit = str(fault.get("provenance") or "").strip()
        if explicit and explicit != "runtime":
            return explicit
        if fault.get("recordKind"):
            return "read-fault"
        fault_type = str(fault.get("faultType") or "").lower()
        message_blob = f"{fault.get('message', '')} {fault.get('detail', '')}".lower()
        if any(token in fault_type or token in message_blob for token in ("watchdog", "no_progress", "startup_stalled", "stalled")):
            return "watchdog"
        if any(token in fault_type or token in message_blob for token in ("self_report", "self-report")):
            return "self-report"
        if any(
            token in fault_type or token in message_blob
            for token in ("hook", "session_end", "agent_end", "runtime_crashed", "bootstrap_failed", "openclaw")
        ):
            return "hook"
        return "runtime"

    def _normalize_runtime_fault(self, fault: dict) -> dict:
        payload = dict(fault)
        payload["provenance"] = self._fault_provenance(payload)
        payload.setdefault("reportedUpward", False)
        payload.setdefault("escalationStatus", "not_reported")
        payload.setdefault("escalationTarget", "")
        return payload

    def _normalize_callback(self, callback: dict) -> dict:
        payload = dict(callback)
        payload.setdefault("callbackLevel", "worker")
        payload.setdefault(
            "upwardTarget",
            "main_leader" if payload.get("callbackLevel") == "team" else "team_leader",
        )
        if payload.get("callbackLevel") == "team":
            payload.setdefault("chainStatus", "reported_upward" if payload.get("reportedUpward") else "reported")
        else:
            payload.setdefault("chainStatus", self._chain_status_for_decision(payload.get("decision", "")))
        payload.setdefault("provenance", "self-report")
        payload.setdefault("reportedUpward", payload.get("callbackLevel") == "team")
        return payload

    def _derive_process_state(self, alive_value: bool | None) -> str:
        if alive_value is True:
            return "alive"
        if alive_value is False:
            return "ended"
        return "unknown"

    def _fault_is_active(self, fault: dict) -> bool:
        return str(fault.get("status") or "open") not in {"resolved", "suppressed"}

    def _fault_is_callback_blocking(self, fault: dict) -> bool:
        if not self._fault_is_active(fault):
            return False
        severity = str(fault.get("severity") or "").lower()
        if severity == "critical":
            return True
        fault_type = str(fault.get("faultType") or "").lower()
        blocking_tokens = {
            "worker_bootstrap_failed",
            "worker_bootstrap_command_failed",
            "worker_startup_stalled",
            "worker_runtime_crashed",
            "leader_runtime_crashed",
            "worker_session_ended_early",
            "callback_timeout",
            "callback_missing",
            "result_missing",
        }
        return any(token in fault_type for token in blocking_tokens)

    def _fault_is_runtime_fatal(self, fault: dict) -> bool:
        if not self._fault_is_active(fault):
            return False
        severity = str(fault.get("severity") or "").lower()
        if severity in {"critical", "error"}:
            return True
        fault_type = str(fault.get("faultType") or "").lower()
        fatal_tokens = {
            "worker_runtime_crashed",
            "leader_runtime_crashed",
            "worker_bootstrap_failed",
            "worker_bootstrap_command_failed",
            "runtime_inconsistent",
        }
        return any(token in fault_type for token in fatal_tokens)

    def _chain_status_for_decision(self, decision: str) -> str:
        mapping = {
            "continue": "in_progress",
            "report_progress": "reported",
            "complete": "reported",
            "escalate": "escalated",
            "blocked": "blocked",
        }
        return mapping.get(str(decision or ""), "reported")

    def _worker_fault_index(
        self,
        *,
        jobs: list[dict],
        sessions: list[dict],
        callbacks: list[dict],
        faults: list[dict],
    ) -> dict[str, list[dict]]:
        by_worker: dict[str, list[dict]] = {}
        job_by_id = {job["jobId"]: job for job in jobs}
        session_by_id = {session["sessionId"]: session for session in sessions}
        callback_by_job = {cb["jobId"]: cb for cb in callbacks if cb.get("jobId")}

        for fault in faults:
            worker_name = self._fault_worker_name(
                fault,
                job_by_id=job_by_id,
                session_by_id=session_by_id,
                callback_by_job=callback_by_job,
            )
            if not worker_name:
                continue
            by_worker.setdefault(worker_name, []).append(fault)
        return by_worker

    def _fault_worker_name(
        self,
        fault: dict,
        *,
        job_by_id: dict[str, dict],
        session_by_id: dict[str, dict],
        callback_by_job: dict[str, dict],
    ) -> str:
        scope_type = fault.get("scopeType")
        scope_id = str(fault.get("scopeId") or "")
        if scope_type == "coding_job" and scope_id in job_by_id:
            return job_by_id[scope_id].get("workerName") or ""
        if scope_type == "provider_session" and scope_id in session_by_id:
            return session_by_id[scope_id].get("workerName") or ""
        if scope_type == "callback" and scope_id in callback_by_job:
            return callback_by_job[scope_id].get("workerName") or ""

        detail = str(fault.get("detail") or "")
        match = re.search(r"worker=([^\s]+)", detail)
        if match:
            return match.group(1)
        return ""

    def _stable_id(self, prefix: str, payload: Any) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        return f"{prefix}-{digest}"

    def _bounded_text_preview(
        self,
        *,
        path: Path,
        max_chars: int,
    ) -> tuple[str, bool, str]:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return "", False, "binary"
        except OSError as exc:
            return "", False, f"unreadable: {exc}"
        if len(content) > max_chars:
            return content[:max_chars], True, ""
        return content, False, ""

    def collect_coding_jobs(self, team_name: str) -> dict:
        jobs, faults = self._jobs_with_faults(team_name)
        jobs_payload = sorted(
            (self._dump_model(job) for job in jobs),
            key=lambda job: job["updatedAt"],
            reverse=True,
        )
        return {
            "teamName": team_name,
            "jobs": jobs_payload,
            "faults": faults,
        }

    def collect_coding_job(self, team_name: str, job_id: str) -> dict:
        record = CodingJobStore().get_job(team_name, job_id)
        if record is None:
            raise ValueError(f"Coding job '{job_id}' not found for team '{team_name}'")
        return self._dump_model(record)

    def collect_coding_job_events(self, team_name: str, job_id: str) -> dict:
        job = self.collect_coding_job(team_name, job_id)
        events = CodingJobStore().list_events(team_name, job_id)
        return {
            "teamName": team_name,
            "jobId": job_id,
            "events": [self._dump_model(event) for event in events],
            "job": job,
        }

    def collect_coding_job_result(self, team_name: str, job_id: str) -> dict:
        self.collect_coding_job(team_name, job_id)
        result = CodingJobStore().load_result(team_name, job_id)
        if result is None:
            raise ValueError(f"Coding job '{job_id}' has no persisted result for team '{team_name}'")
        return self._dump_model(result)

    def collect_coding_job_artifacts(self, team_name: str, job_id: str) -> dict:
        record = self.collect_coding_job(team_name, job_id)
        artifacts = []
        for name, raw_path in sorted((record.get("artifactPaths") or {}).items()):
            path = Path(raw_path)
            exists = path.exists()
            artifacts.append(
                {
                    "name": name,
                    "path": raw_path,
                    "exists": exists,
                    "sizeBytes": path.stat().st_size if exists else None,
                }
            )
        return {
            "teamName": team_name,
            "jobId": job_id,
            "artifacts": artifacts,
        }

    def collect_coding_job_artifact_preview(
        self,
        team_name: str,
        job_id: str,
        artifact_name: str,
        *,
        max_chars: int = 12000,
    ) -> dict:
        record = self.collect_coding_job(team_name, job_id)
        artifact_path = (record.get("artifactPaths") or {}).get(artifact_name)
        if artifact_path is None:
            raise ValueError(
                f"Coding job '{job_id}' has no artifact named '{artifact_name}' for team '{team_name}'"
            )
        path = Path(artifact_path)
        allowed_root = CodingJobStore().artifact_path(team_name, job_id, artifact_name).parent.resolve()
        try:
            resolved_path = path.resolve(strict=False)
            within_artifact_root = resolved_path.is_relative_to(allowed_root)
        except OSError:
            resolved_path = path
            within_artifact_root = False
        payload = {
            "teamName": team_name,
            "jobId": job_id,
            "name": artifact_name,
            "path": artifact_path,
            "exists": False,
            "isBinary": False,
            "truncated": False,
            "content": None,
            "unavailableReason": "",
            "sizeBytes": None,
        }
        if not within_artifact_root:
            payload["unavailableReason"] = "outside_artifact_root"
            return payload
        payload["exists"] = path.exists()
        payload["sizeBytes"] = path.stat().st_size if path.exists() else None
        if not path.exists():
            payload["unavailableReason"] = "missing_on_disk"
            return payload
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            payload["isBinary"] = True
            payload["unavailableReason"] = "binary"
            return payload
        except OSError as exc:
            payload["unavailableReason"] = f"unreadable: {exc}"
            return payload
        if len(content) > max_chars:
            payload["content"] = content[:max_chars]
            payload["truncated"] = True
            return payload
        payload["content"] = content
        return payload

    def collect_provider_sessions(self, team_name: str) -> dict:
        sessions, faults = self._runtime_sessions_with_faults(team_name)
        sessions_payload = sorted(
            (self._dump_model(session) for session in sessions),
            key=lambda session: session["updatedAt"],
            reverse=True,
        )
        return {
            "teamName": team_name,
            "sessions": sessions_payload,
            "faults": faults,
        }

    def collect_provider_session(self, team_name: str, session_id: str) -> dict:
        session = RuntimeConsoleStore().get_provider_session(team_name, session_id)
        if session is None:
            raise ValueError(f"Provider session '{session_id}' not found for team '{team_name}'")
        return self._dump_model(session)

    def collect_provider_session_jobs(self, team_name: str, session_id: str) -> dict:
        self.collect_provider_session(team_name, session_id)
        jobs, faults = self._jobs_with_faults(team_name)
        linked_jobs = sorted(
            (
                self._dump_model(job)
                for job in jobs
                if job.provider_session_ref == session_id
            ),
            key=lambda job: job["updatedAt"],
            reverse=True,
        )
        return {
            "teamName": team_name,
            "sessionId": session_id,
            "jobs": linked_jobs,
            "faults": faults,
        }

    def collect_provider_session_events(self, team_name: str, session_id: str) -> dict:
        self.collect_provider_session(team_name, session_id)
        events, faults = RuntimeConsoleService().inspect_session_timeline(
            team_name=team_name,
            session_id=session_id,
        )
        return {
            "teamName": team_name,
            "sessionId": session_id,
            "events": [self._dump_model(event) for event in events],
            "faults": faults,
        }

    def collect_callbacks(self, team_name: str) -> dict:
        callbacks, faults = self._runtime_callbacks_with_faults(team_name)
        payload = sorted(
            (self._normalize_callback(self._dump_model(callback)) for callback in callbacks),
            key=lambda callback: callback.get("reportedAt", ""),
            reverse=True,
        )
        return {
            "teamName": team_name,
            "callbacks": payload,
            "faults": [self._normalize_read_fault(fault) for fault in faults],
        }

    def collect_faults(self, team_name: str) -> dict:
        runtime_faults, read_faults = self._runtime_faults_with_faults(team_name)
        payload = [self._normalize_runtime_fault(self._dump_model(fault)) for fault in runtime_faults]
        payload.extend(self._normalize_read_fault(fault) for fault in read_faults)
        payload = sorted(
            payload,
            key=lambda fault: fault.get("detectedAt", ""),
            reverse=True,
        )
        provenance_counter = Counter(fault.get("provenance", "runtime") for fault in payload)
        return {
            "teamName": team_name,
            "faults": payload,
            "provenanceSummary": {
                "hook": provenance_counter.get("hook", 0),
                "watchdog": provenance_counter.get("watchdog", 0),
                "selfReport": provenance_counter.get("self-report", 0),
                "readFault": provenance_counter.get("read-fault", 0),
                "runtime": provenance_counter.get("runtime", 0),
            },
        }

    def collect_timeline(self, team_name: str) -> dict:
        timeline, faults = self._runtime_timeline_with_faults(team_name)
        payload = sorted(
            (self._dump_model(event) for event in timeline),
            key=lambda event: event["timestamp"],
            reverse=True,
        )
        return {
            "teamName": team_name,
            "events": payload,
            "faults": [self._normalize_read_fault(fault) for fault in faults],
        }

    def _collect_coding(self, team_name: str) -> dict:
        jobs, faults = self._jobs_with_faults(team_name)
        jobs = sorted(
            jobs,
            key=lambda job: job.updated_at,
            reverse=True,
        )
        summary = {
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "timeout": 0,
            "cancelled": 0,
            "active": 0,
            "total": len(jobs),
        }
        recent_jobs = []
        latest_by_worker: dict[str, dict] = {}
        for job in jobs:
            entry = {
                "jobId": job.job_id,
                "workerName": job.worker_name,
                "workerId": job.worker_id,
                "taskId": job.task_id,
                "provider": job.provider.value,
                "mode": job.mode.value,
                "state": job.state.value,
                "requestedCwd": job.requested_cwd,
                "effectiveCwd": job.effective_cwd,
                "summary": job.summary,
                "error": job.error,
                "createdAt": job.created_at,
                "updatedAt": job.updated_at,
                "startedAt": job.started_at,
                "finishedAt": job.finished_at,
                "attemptKind": job.attempt_kind.value,
                "retryCount": job.retry_count,
                "replayCount": job.replay_count,
                "callbackStatus": job.callback_status.value,
                "callbackDecision": job.callback_decision.value if job.callback_decision else None,
                "callbackReportedAt": job.callback_reported_at,
                "sessionMode": job.session_mode.value,
                "providerSessionRef": job.provider_session_ref,
                "providerSessionId": job.provider_session_id,
                "artifactPaths": job.artifact_paths,
            }
            summary[job.state.value] += 1
            if job.state in ACTIVE_CODING_JOB_STATES:
                summary["active"] += 1
            recent_jobs.append(entry)
            latest_by_worker.setdefault(job.worker_name, entry)

        data_root = get_data_dir() / "coding"
        return {
            "summary": summary,
            "recentJobs": recent_jobs[:20],
            "latestByWorker": latest_by_worker,
            "faults": faults,
            "storage": {
                "jobsRoot": str(data_root / "jobs" / team_name),
                "resultsRoot": str(data_root / "results" / team_name),
                "eventsRoot": str(data_root / "events" / team_name),
                "artifactsRoot": str(data_root / "artifacts" / team_name),
            },
        }

    def _collect_callback_chain(
        self,
        *,
        members: list[dict],
        tasks: list[dict],
        jobs: list[dict],
        sessions: list[dict],
        callbacks: list[dict],
        faults: list[dict],
    ) -> dict:
        leader_candidates = {member["name"] for member in members if member.get("agentType") == "leader"}
        workers = [member for member in members if member["name"] not in leader_candidates]

        jobs_by_worker: dict[str, list[dict]] = {}
        for job in jobs:
            jobs_by_worker.setdefault(job["workerName"], []).append(job)

        sessions_by_worker: dict[str, list[dict]] = {}
        for session in sessions:
            sessions_by_worker.setdefault(session["workerName"], []).append(session)

        callbacks_by_worker: dict[str, list[dict]] = {}
        job_by_id = {job["jobId"]: job for job in jobs}
        worker_callbacks = [cb for cb in callbacks if cb.get("callbackLevel", "worker") == "worker"]
        for callback in worker_callbacks:
            worker_name = callback.get("workerName") or (job_by_id.get(callback.get("jobId") or "", {}).get("workerName") or "")
            if not worker_name:
                continue
            callbacks_by_worker.setdefault(worker_name, []).append(callback)

        worker_faults = self._worker_fault_index(
            jobs=jobs,
            sessions=sessions,
            callbacks=callbacks,
            faults=faults,
        )

        task_by_owner: dict[str, list[dict]] = {}
        for task in tasks:
            owner = task.get("owner") or ""
            if not owner:
                continue
            task_by_owner.setdefault(owner, []).append(task)

        worker_rows = []
        for worker in workers:
            worker_name = worker["name"]
            latest_job = sorted(jobs_by_worker.get(worker_name, []), key=lambda item: item.get("updatedAt", ""), reverse=True)
            latest_session = sorted(sessions_by_worker.get(worker_name, []), key=lambda item: item.get("updatedAt", ""), reverse=True)
            latest_callback = sorted(callbacks_by_worker.get(worker_name, []), key=lambda item: item.get("reportedAt", ""), reverse=True)
            latest_job_record = latest_job[0] if latest_job else None
            latest_session_record = latest_session[0] if latest_session else None
            latest_callback_record = latest_callback[0] if latest_callback else None
            faults_for_worker = worker_faults.get(worker_name, [])
            tasks_for_worker = sorted(task_by_owner.get(worker_name, []), key=lambda item: item.get("updatedAt", ""), reverse=True)
            active_task = tasks_for_worker[0] if tasks_for_worker else None

            callback_state = self._derive_worker_callback_state(
                latest_callback=latest_callback_record,
                latest_job=latest_job_record,
                worker_faults=faults_for_worker,
                active_task=active_task,
            )
            process_state = self._derive_process_state(worker.get("alive"))
            health = self._derive_worker_health(
                process_state=process_state,
                callback_state=callback_state,
                worker_faults=faults_for_worker,
            )
            progress = self._derive_worker_progress(
                callback_state=callback_state,
                latest_job=latest_job_record,
                active_task=active_task,
            )

            latest_fault = sorted(faults_for_worker, key=lambda item: item.get("detectedAt", ""), reverse=True)
            latest_fault_record = latest_fault[0] if latest_fault else None
            row = {
                "workerName": worker_name,
                "source": "durable_state",
                "from": worker_name,
                "to": "team_leader",
                "callbackStatus": callback_state,
                "callbackState": callback_state,
                "chainStatus": callback_state,
                "reportedAt": (latest_callback_record or {}).get("reportedAt"),
                "decision": (latest_callback_record or {}).get("decision"),
                "summary": (latest_callback_record or {}).get("summary"),
                "taskId": (latest_callback_record or {}).get("taskId") or (latest_job_record or {}).get("taskId"),
                "jobId": (latest_callback_record or {}).get("jobId") or (latest_job_record or {}).get("jobId"),
                "sessionId": (latest_session_record or {}).get("sessionId"),
                "processState": process_state,
                "health": health,
                "progressState": progress,
                "faultState": "faulted" if faults_for_worker else "none",
                "faultCount": len(faults_for_worker),
                "faultProvenance": (latest_fault_record or {}).get("provenance", ""),
                "waitingFor": self._worker_waiting_for(callback_state, latest_job_record, active_task),
                "callbackRecord": latest_callback_record,
                "activeTaskStatus": (active_task or {}).get("status"),
            }
            worker_rows.append(row)

        state_counter = Counter(row["callbackState"] for row in worker_rows)
        team_callbacks = [cb for cb in callbacks if cb.get("callbackLevel") == "team"]
        latest_team_callback = sorted(team_callbacks, key=lambda item: item.get("reportedAt", ""), reverse=True)
        latest_team_callback_record = latest_team_callback[0] if latest_team_callback else None

        workers_total = len(worker_rows)
        workers_reported = state_counter.get("reported", 0)
        workers_escalated = state_counter.get("escalated", 0)
        workers_blocked = state_counter.get("blocked", 0)
        workers_faulted = state_counter.get("faulted", 0)
        workers_pending = state_counter.get("pending", 0)
        workers_in_progress = state_counter.get("in_progress", 0)
        workers_not_started = state_counter.get("not_started", 0)

        if latest_team_callback_record is not None:
            team_status = latest_team_callback_record.get("chainStatus") or (
                "reported_upward" if latest_team_callback_record.get("reportedUpward") else "reported"
            )
        elif workers_total == 0:
            team_status = "not_started"
        elif workers_pending > 0 or workers_in_progress > 0:
            team_status = "in_progress"
        elif workers_not_started == workers_total:
            team_status = "not_started"
        elif workers_faulted == workers_total:
            team_status = "faulted"
        elif (workers_blocked + workers_escalated) > 0 and workers_reported == 0:
            team_status = "blocked"
        elif (workers_reported + workers_escalated + workers_blocked + workers_faulted) > 0:
            team_status = "waiting_aggregate"
        else:
            team_status = "not_started"

        team_row = {
            "source": "durable_state" if latest_team_callback_record else "durable_inference",
            "from": "team_leader",
            "to": "main_leader",
            "callbackStatus": team_status,
            "callbackState": team_status,
            "chainStatus": team_status,
            "reportedAt": (latest_team_callback_record or {}).get("reportedAt"),
            "decision": (latest_team_callback_record or {}).get("decision"),
            "summary": (latest_team_callback_record or {}).get("summary"),
            "reportedUpward": bool((latest_team_callback_record or {}).get("reportedUpward") or team_status == "reported_upward"),
            "workersTotal": workers_total,
            "workersReported": workers_reported,
            "workersPending": workers_pending + workers_in_progress,
            "workersEscalated": workers_escalated,
            "workersBlocked": workers_blocked,
            "workersFaulted": workers_faulted,
        }

        return {
            "workers": worker_rows,
            "team": team_row,
            "summary": {
                "workerTotal": workers_total,
                "workerReported": workers_reported,
                "workerPending": workers_pending + workers_in_progress,
                "workerEscalated": workers_escalated,
                "workerBlocked": workers_blocked,
                "workerFaulted": workers_faulted,
                "inProgress": 1 if team_status == "in_progress" else 0,
                "waitingAggregate": 1 if team_status == "waiting_aggregate" else 0,
                "reportedUpward": 1 if team_row.get("reportedUpward") else 0,
            },
        }

    def _derive_worker_callback_state(
        self,
        *,
        latest_callback: dict | None,
        latest_job: dict | None,
        worker_faults: list[dict],
        active_task: dict | None,
    ) -> str:
        if latest_callback:
            decision = str(latest_callback.get("decision") or "")
            if decision == "escalate":
                return "escalated"
            if decision == "blocked":
                return "blocked"
            if decision == "continue":
                return "in_progress"
            return "reported"
        if any(self._fault_is_callback_blocking(fault) for fault in worker_faults):
            return "faulted"
        if latest_job and latest_job.get("state") in {"queued", "running"}:
            return "pending"
        if latest_job and latest_job.get("callbackStatus") in {"pending", "not_applicable"} and latest_job.get("state") in {
            "completed",
            "failed",
            "timeout",
            "cancelled",
        }:
            return "pending"
        if active_task and active_task.get("status") in {"pending", "in_progress"}:
            return "in_progress"
        return "not_started"

    def _derive_worker_health(
        self,
        *,
        process_state: str,
        callback_state: str,
        worker_faults: list[dict],
    ) -> str:
        provenances = {fault.get("provenance") for fault in worker_faults}
        if "watchdog" in provenances:
            return "stalled"
        if any(self._fault_is_runtime_fatal(fault) for fault in worker_faults) or callback_state == "faulted":
            return "faulted"
        if process_state == "unknown":
            return "degraded"
        if callback_state in {"blocked", "escalated"}:
            return "degraded"
        return "healthy"

    def _derive_worker_progress(
        self,
        *,
        callback_state: str,
        latest_job: dict | None,
        active_task: dict | None,
    ) -> str:
        if callback_state == "pending":
            return "waiting_callback"
        if latest_job and latest_job.get("state") in {"queued", "running"}:
            return "executing"
        if callback_state == "reported":
            return "reported"
        if callback_state in {"blocked", "escalated", "faulted"}:
            return "blocked"
        if active_task and active_task.get("status") == "pending":
            return "claiming"
        if active_task and active_task.get("status") == "in_progress":
            return "executing"
        return "idle"

    def _worker_waiting_for(
        self,
        callback_state: str,
        latest_job: dict | None,
        active_task: dict | None,
    ) -> str:
        if callback_state == "pending":
            return "callback_report"
        if callback_state == "in_progress":
            return "worker_execution"
        if callback_state == "reported":
            return "team_aggregate"
        if callback_state == "escalated":
            return "leader_decision"
        if callback_state == "blocked":
            return "operator_intervention"
        if callback_state == "faulted":
            return "fault_recovery"
        if latest_job and latest_job.get("state") in {"queued", "running"}:
            return "coding_runtime"
        if active_task and active_task.get("status") in {"pending", "in_progress"}:
            return "task_claim"
        return "none"

    def _collect_evidence_records(
        self,
        *,
        team_name: str,
        jobs: list[dict],
        callbacks: list[dict],
        faults: list[dict],
        limit: int,
        max_chars: int,
    ) -> tuple[list[dict], list[dict]]:
        persisted_records, persisted_read_faults = self._runtime_evidence_with_faults(team_name)
        evidence: list[dict] = []

        for record in persisted_records:
            payload = self._dump_model(record)
            payload.setdefault("authority", "non_authoritative")
            payload["nonAuthoritative"] = True
            payload["captureMode"] = "persisted"
            evidence.append(payload)

        artifact_candidates = []
        for job in sorted(jobs, key=lambda item: item.get("updatedAt", ""), reverse=True):
            artifact_paths = job.get("artifactPaths") or {}
            for name, raw_path in sorted(artifact_paths.items()):
                artifact_candidates.append((job, name, raw_path))

        for job, artifact_name, artifact_path in artifact_candidates[:_EVIDENCE_DEFAULT_ARTIFACT_LIMIT]:
            preview = self.collect_coding_job_artifact_preview(
                team_name,
                job["jobId"],
                artifact_name,
                max_chars=max_chars,
            )
            evidence_payload = {
                "schemaVersion": 1,
                "evidenceId": self._stable_id("artifact-evidence", [team_name, job["jobId"], artifact_name, artifact_path]),
                "teamName": team_name,
                "evidenceType": "coding_artifact_preview",
                "sourceType": "coding_job",
                "sourceId": job["jobId"],
                "workerName": job.get("workerName"),
                "taskId": job.get("taskId"),
                "jobId": job.get("jobId"),
                "sessionId": job.get("providerSessionRef"),
                "capturedAt": job.get("updatedAt"),
                "updatedAt": job.get("updatedAt"),
                "authority": "non_authoritative",
                "nonAuthoritative": True,
                "captureMode": "collector_derived",
                "label": f"artifact:{artifact_name}",
                "path": artifact_path,
                "excerpt": preview.get("content") or "",
                "excerptBytes": len((preview.get("content") or "").encode("utf-8")),
                "maxChars": max_chars,
                "truncated": bool(preview.get("truncated")),
                "unavailableReason": preview.get("unavailableReason") or None,
                "metadata": {
                    "artifactName": artifact_name,
                    "exists": preview.get("exists"),
                    "isBinary": preview.get("isBinary"),
                    "sizeBytes": preview.get("sizeBytes"),
                },
            }
            evidence.append(evidence_payload)

        for callback in callbacks[: max(1, limit // 4)]:
            summary = str(callback.get("summary") or "")
            if not summary:
                continue
            excerpt = summary[:max_chars]
            evidence.append(
                {
                    "schemaVersion": 1,
                    "evidenceId": self._stable_id("callback-evidence", [team_name, callback.get("jobId"), callback.get("reportedAt")]),
                    "teamName": team_name,
                    "evidenceType": "hook_payload_excerpt",
                    "sourceType": "callback",
                    "sourceId": callback.get("jobId") or "",
                    "workerName": callback.get("workerName"),
                    "taskId": callback.get("taskId"),
                    "jobId": callback.get("jobId"),
                    "sessionId": callback.get("sessionId"),
                    "callbackJobId": callback.get("jobId"),
                    "capturedAt": callback.get("reportedAt"),
                    "updatedAt": callback.get("reportedAt"),
                    "authority": "non_authoritative",
                    "nonAuthoritative": True,
                    "captureMode": "collector_derived",
                    "label": "callback summary excerpt",
                    "path": None,
                    "excerpt": excerpt,
                    "excerptBytes": len(excerpt.encode("utf-8")),
                    "maxChars": max_chars,
                    "truncated": len(summary) > max_chars,
                    "metadata": {
                        "callbackLevel": callback.get("callbackLevel", "worker"),
                        "decision": callback.get("decision", ""),
                    },
                }
            )

        for fault in faults[: max(1, limit // 4)]:
            detail = str(fault.get("detail") or fault.get("message") or "")
            if not detail:
                continue
            excerpt = detail[:max_chars]
            evidence.append(
                {
                    "schemaVersion": 1,
                    "evidenceId": self._stable_id("fault-evidence", [team_name, fault.get("faultId"), fault.get("detectedAt")]),
                    "teamName": team_name,
                    "evidenceType": "hook_payload_excerpt",
                    "sourceType": "fault",
                    "sourceId": fault.get("faultId") or fault.get("recordId") or fault.get("faultType") or "fault",
                    "workerName": self._fault_worker_name(
                        fault,
                        job_by_id={job["jobId"]: job for job in jobs},
                        session_by_id={},
                        callback_by_job={},
                    )
                    or None,
                    "faultId": fault.get("faultId"),
                    "capturedAt": fault.get("detectedAt"),
                    "updatedAt": fault.get("detectedAt"),
                    "authority": "non_authoritative",
                    "nonAuthoritative": True,
                    "captureMode": "collector_derived",
                    "label": "fault detail excerpt",
                    "path": None,
                    "excerpt": excerpt,
                    "excerptBytes": len(excerpt.encode("utf-8")),
                    "maxChars": max_chars,
                    "truncated": len(detail) > max_chars,
                    "metadata": {
                        "provenance": fault.get("provenance", "runtime"),
                        "severity": fault.get("severity", "warning"),
                    },
                }
            )

        evidence_sorted = sorted(
            evidence,
            key=lambda item: item.get("capturedAt", ""),
            reverse=True,
        )
        return evidence_sorted[:limit], [self._normalize_read_fault(fault) for fault in persisted_read_faults]

    def collect_evidence(
        self,
        team_name: str,
        *,
        worker_name: str | None = None,
        limit: int = _EVIDENCE_DEFAULT_LIMIT,
        max_chars: int = _EVIDENCE_DEFAULT_MAX_CHARS,
    ) -> dict:
        jobs_data = self.collect_coding_jobs(team_name)
        callbacks_data = self.collect_callbacks(team_name)
        faults_data = self.collect_faults(team_name)
        records, read_faults = self._collect_evidence_records(
            team_name=team_name,
            jobs=jobs_data["jobs"],
            callbacks=callbacks_data["callbacks"],
            faults=faults_data["faults"],
            limit=max(1, limit),
            max_chars=max(128, max_chars),
        )
        if worker_name:
            records = [record for record in records if record.get("workerName") == worker_name]

        by_type = Counter(record.get("evidenceType", "unknown") for record in records)
        persisted_count = sum(1 for record in records if record.get("captureMode") == "persisted")
        collector_derived_count = sum(1 for record in records if record.get("captureMode") != "persisted")
        return {
            "teamName": team_name,
            "workerName": worker_name,
            "nonAuthoritative": True,
            "viewKind": "bounded_evidence_view",
            "authorityNotice": (
                "Bounded evidence view only. Evidence is non-authoritative; durable task/runtime state remains "
                "source of truth. Records may be persisted captures or collector-derived excerpts."
            ),
            "maxChars": max(128, max_chars),
            "records": records,
            "readFaults": read_faults,
            "summary": {
                "total": len(records),
                "truncated": sum(1 for record in records if record.get("truncated")),
                "unavailable": sum(1 for record in records if record.get("unavailableReason")),
                "byType": dict(by_type),
                "persisted": persisted_count,
                "collectorDerived": collector_derived_count,
            },
        }

    def collect_evidence_detail(self, team_name: str, evidence_id: str) -> dict:
        stored = RuntimeConsoleStore().get_evidence(team_name, evidence_id)
        if stored is not None:
            payload = self._dump_model(stored)
            payload.setdefault("authority", "non_authoritative")
            payload["nonAuthoritative"] = True
            payload["authorityNotice"] = "Evidence is non-authoritative. Durable task/runtime state remains source of truth."
            return payload

        payload = self.collect_evidence(team_name, limit=max(_EVIDENCE_DEFAULT_LIMIT, 160))
        for record in payload["records"]:
            if record.get("evidenceId") == evidence_id:
                record = dict(record)
                record["authorityNotice"] = payload["authorityNotice"]
                return record
        raise ValueError(f"Evidence '{evidence_id}' not found for team '{team_name}'")

    def collect_worker_evidence(self, team_name: str, worker_name: str) -> dict:
        return self.collect_evidence(team_name, worker_name=worker_name)

    def collect_worker_callbacks(self, team_name: str, worker_name: str) -> dict:
        callbacks_data = self.collect_callbacks(team_name)
        callbacks = [
            callback
            for callback in callbacks_data["callbacks"]
            if callback.get("workerName") == worker_name and callback.get("callbackLevel", "worker") == "worker"
        ]
        return {
            "teamName": team_name,
            "workerName": worker_name,
            "callbacks": callbacks,
            "faults": callbacks_data.get("faults", []),
        }

    def collect_worker_faults(self, team_name: str, worker_name: str) -> dict:
        jobs_data = self.collect_coding_jobs(team_name)
        sessions_data = self.collect_provider_sessions(team_name)
        callbacks_data = self.collect_callbacks(team_name)
        faults_data = self.collect_faults(team_name)
        index = self._worker_fault_index(
            jobs=jobs_data["jobs"],
            sessions=sessions_data["sessions"],
            callbacks=callbacks_data["callbacks"],
            faults=faults_data["faults"],
        )
        return {
            "teamName": team_name,
            "workerName": worker_name,
            "faults": index.get(worker_name, []),
            "provenanceSummary": Counter(fault.get("provenance", "runtime") for fault in index.get(worker_name, [])),
        }

    def collect_callback_chain(self, team_name: str) -> dict:
        data = self.collect_team(team_name)
        return {
            "teamName": team_name,
            "callbackChain": data["runtimeConsole"]["callbackChain"],
        }

    def collect_escalations(self, team_name: str) -> dict:
        data = self.collect_team(team_name)
        runtime = data["runtimeConsole"]
        worker_chain = runtime["callbackChain"]["workers"]
        fault_records = runtime["faults"]
        callback_escalations = [
            row
            for row in worker_chain
            if row.get("callbackState") in {"escalated", "blocked", "faulted"}
        ]
        fault_escalations = [
            fault
            for fault in fault_records
            if fault.get("reportedUpward")
            or fault.get("escalationStatus") not in {"", "not_reported", "not_applicable"}
        ]
        return {
            "teamName": team_name,
            "callbackEscalations": callback_escalations,
            "faultEscalations": fault_escalations,
            "summary": {
                "callbackEscalations": len(callback_escalations),
                "faultEscalations": len(fault_escalations),
            },
        }

    def _collect_runtime_console(
        self,
        team_name: str,
        *,
        members: list[dict],
        task_items: list[dict],
    ) -> dict:
        jobs_data = self.collect_coding_jobs(team_name)
        sessions_data = self.collect_provider_sessions(team_name)
        callbacks_data = self.collect_callbacks(team_name)
        faults_data = self.collect_faults(team_name)
        timeline_data = self.collect_timeline(team_name)

        observed_worker_names = {
            job.get("workerName")
            for job in jobs_data["jobs"]
            if job.get("workerName")
        }
        observed_worker_names.update(
            session.get("workerName")
            for session in sessions_data["sessions"]
            if session.get("workerName")
        )
        observed_worker_names.update(
            callback.get("workerName")
            for callback in callbacks_data["callbacks"]
            if callback.get("workerName")
        )
        observed_worker_names.update(
            task.get("owner")
            for task in task_items
            if task.get("owner")
        )
        known_member_names = {member["name"] for member in members}
        enriched_members = list(members)
        for worker_name in sorted(observed_worker_names):
            if worker_name in known_member_names:
                continue
            enriched_members.append(
                {
                    "name": worker_name,
                    "agentId": f"runtime-observed:{worker_name}",
                    "agentType": "worker",
                    "joinedAt": "",
                    "inboxCount": 0,
                    "alive": is_agent_alive(team_name, worker_name),
                    "observedOnly": True,
                }
            )

        callback_chain = self._collect_callback_chain(
            members=enriched_members,
            tasks=task_items,
            jobs=jobs_data["jobs"],
            sessions=sessions_data["sessions"],
            callbacks=callbacks_data["callbacks"],
            faults=faults_data["faults"],
        )

        callback_by_worker = {row["workerName"]: row for row in callback_chain["workers"]}

        active_jobs_by_worker = {
            job["workerName"]: job
            for job in jobs_data["jobs"]
            if job["state"] in {"queued", "running"}
        }
        latest_session_by_worker = {}
        for session in sessions_data["sessions"]:
            latest_session_by_worker.setdefault(session["workerName"], session)

        workers = []
        for member in enriched_members:
            job = active_jobs_by_worker.get(member["name"])
            session = latest_session_by_worker.get(member["name"])
            callback_row = callback_by_worker.get(member["name"], {})
            process_state = callback_row.get("processState") or self._derive_process_state(member.get("alive"))
            workers.append(
                {
                    "name": member["name"],
                    "agentId": member["agentId"],
                    "agentType": member["agentType"],
                    "alive": member["alive"],
                    "processState": process_state,
                    "health": callback_row.get("health", "degraded" if process_state == "unknown" else "healthy"),
                    "progressState": callback_row.get("progressState", "idle"),
                    "callbackState": callback_row.get("callbackState", "not_started"),
                    "faultState": callback_row.get("faultState", "none"),
                    "faultCount": callback_row.get("faultCount", 0),
                    "faultProvenance": callback_row.get("faultProvenance", ""),
                    "waitingFor": callback_row.get("waitingFor", "none"),
                    "currentTaskId": (
                        (session or {}).get("currentTaskId")
                        or (job or {}).get("taskId")
                    ),
                    "currentJobId": (session or {}).get("currentJobId") or (job or {}).get("jobId"),
                    "currentSessionId": (session or {}).get("sessionId"),
                    "sessionMode": (session or {}).get("sessionMode"),
                    "callbackPending": (session or {}).get("state") == "callback_pending" or callback_row.get("callbackState") == "pending",
                }
            )

        session_summary = {
            "total": len(sessions_data["sessions"]),
            "attached": sum(1 for session in sessions_data["sessions"] if session["sessionMode"] == "attached"),
            "ephemeral": sum(1 for session in sessions_data["sessions"] if session["sessionMode"] == "ephemeral"),
            "active": sum(
                1 for session in sessions_data["sessions"] if session["state"] in {"active", "waiting_provider"}
            ),
            "callbackPending": sum(
                1 for session in sessions_data["sessions"] if session["state"] == "callback_pending"
            ),
        }

        callback_summary = {
            "total": len(callbacks_data["callbacks"]),
            "reported": sum(1 for callback in callbacks_data["callbacks"] if callback.get("decision") == "report_progress"),
            "escalated": sum(1 for callback in callbacks_data["callbacks"] if callback.get("decision") == "escalate"),
            "blocked": sum(1 for callback in callbacks_data["callbacks"] if callback.get("decision") == "blocked"),
            "workerCallbacks": sum(1 for callback in callbacks_data["callbacks"] if callback.get("callbackLevel") == "worker"),
            "teamCallbacks": sum(1 for callback in callbacks_data["callbacks"] if callback.get("callbackLevel") == "team"),
        }

        evidence_data = self.collect_evidence(team_name, limit=30)

        return {
            "summary": {
                "jobs": self._collect_coding(team_name)["summary"],
                "sessions": session_summary,
                "callbacks": callback_summary,
                "callbackChain": callback_chain["summary"],
                "faults": {
                    "total": len(faults_data["faults"]),
                    "hook": faults_data["provenanceSummary"]["hook"],
                    "watchdog": faults_data["provenanceSummary"]["watchdog"],
                    "selfReport": faults_data["provenanceSummary"]["selfReport"],
                    "readFault": faults_data["provenanceSummary"]["readFault"],
                },
                "timelineEvents": len(timeline_data["events"]),
                "evidence": evidence_data["summary"],
            },
            "workers": workers,
            "tasks": task_items,
            "jobs": jobs_data["jobs"],
            "sessions": sessions_data["sessions"],
            "callbacks": callbacks_data["callbacks"],
            "callbackChain": callback_chain,
            "faults": faults_data["faults"],
            "faultProvenanceSummary": faults_data["provenanceSummary"],
            "timeline": timeline_data["events"],
            "evidence": evidence_data,
        }

    def collect_team(self, team_name: str) -> dict:
        """Collect full board data for a single team.

        Returns a dict with keys: team, members, tasks, taskSummary.
        Raises ValueError if the team does not exist.
        """
        config = TeamManager.get_team(team_name)
        if not config:
            raise ValueError(f"Team '{team_name}' not found")

        mailbox = MailboxManager(team_name)

        # Members with inbox counts
        members = []
        for m in config.members:
            inbox_name = f"{m.user}_{m.name}" if m.user else m.name
            alive = is_agent_alive(team_name, m.name)
            entry = {
                "name": m.name,
                "agentId": m.agent_id,
                "agentType": m.agent_type,
                "joinedAt": m.joined_at,
                "inboxCount": mailbox.peek_count(inbox_name),
                "alive": alive,
            }
            if m.user:
                entry["user"] = m.user
            members.append(entry)

        # Tasks grouped by status
        all_tasks, task_read_faults = self._tasks_with_faults(team_name)
        task_items = []
        grouped: dict[str, list[dict]] = {
            "pending": [],
            "in_progress": [],
            "completed": [],
            "blocked": [],
        }
        for task in all_tasks:
            dumped = json.loads(task.model_dump_json(by_alias=True, exclude_none=True))
            task_items.append(dumped)
            grouped[task.status.value].append(dumped)

        summary = {status: len(grouped[status]) for status in grouped}
        summary["total"] = len(all_tasks)
        summary["readFaults"] = len(task_read_faults)

        # Find leader name
        leader_name = ""
        for member in config.members:
            if member.agent_id == config.lead_agent_id:
                leader_name = member.name
                break

        # Collect message history from event log (persistent, never consumed)
        all_messages = []
        try:
            events = mailbox.get_event_log(limit=200)
            for message in events:
                all_messages.append(
                    json.loads(message.model_dump_json(by_alias=True, exclude_none=True))
                )
        except Exception:
            pass

        # Cost summary
        cost_data = {}
        try:
            from clawteam.team.costs import CostStore

            cost_store = CostStore(team_name)
            cost_summary = cost_store.summary()
            cost_data = {
                "totalCostCents": cost_summary.total_cost_cents,
                "totalInputTokens": cost_summary.total_input_tokens,
                "totalOutputTokens": cost_summary.total_output_tokens,
                "eventCount": cost_summary.event_count,
                "byAgent": cost_summary.by_agent,
            }
        except Exception:
            pass

        coding_data = self._collect_coding(team_name)
        runtime_console = self._collect_runtime_console(
            team_name,
            members=members,
            task_items=task_items,
        )

        return {
            "team": {
                "name": config.name,
                "description": config.description,
                "leadAgentId": config.lead_agent_id,
                "leaderName": leader_name,
                "createdAt": config.created_at,
                "budgetCents": config.budget_cents,
            },
            "members": members,
            "tasks": grouped,
            "taskSummary": summary,
            "taskReadFaults": task_read_faults,
            "messages": all_messages,
            "cost": cost_data,
            "coding": coding_data,
            "runtimeConsole": runtime_console,
        }

    def collect_overview(self) -> list[dict]:
        """Collect summary data for all teams."""
        teams_meta = TeamManager.discover_teams()
        result = []
        for meta in teams_meta:
            name = meta["name"]
            try:
                data = self.collect_team(name)
                total_inbox = sum(member["inboxCount"] for member in data["members"])
                leader = data["team"].get("leaderName", "")
                result.append(
                    {
                        "name": name,
                        "description": meta.get("description", ""),
                        "leader": leader,
                        "members": len(data["members"]),
                        "tasks": data["taskSummary"]["total"],
                        "pendingMessages": total_inbox,
                        "activeCodingJobs": data.get("coding", {}).get("summary", {}).get("active", 0),
                        "callbackPending": data.get("runtimeConsole", {}).get("summary", {}).get("callbackChain", {}).get("workerPending", 0),
                        "faults": data.get("runtimeConsole", {}).get("summary", {}).get("faults", {}).get("total", 0),
                    }
                )
            except Exception:
                result.append(
                    {
                        "name": name,
                        "description": meta.get("description", ""),
                        "leader": "",
                        "members": meta.get("memberCount", 0),
                        "tasks": 0,
                        "pendingMessages": 0,
                        "activeCodingJobs": 0,
                        "callbackPending": 0,
                        "faults": 0,
                    }
                )
        return result
