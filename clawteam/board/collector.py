"""Aggregates team/task/inbox data into plain dicts for rendering."""

from __future__ import annotations

import json
from pathlib import Path

from clawteam.coding import ACTIVE_CODING_JOB_STATES, CodingJobStore
from clawteam.runtime_console import RuntimeConsoleStore
from clawteam.runtime_console.service import RuntimeConsoleService
from clawteam.spawn.registry import is_agent_alive
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import get_data_dir
from clawteam.team.tasks import TaskStore


class BoardCollector:
    """Aggregates team/task/inbox data into plain dicts."""

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
            (self._dump_model(callback) for callback in callbacks),
            key=lambda callback: callback["reportedAt"],
            reverse=True,
        )
        return {
            "teamName": team_name,
            "callbacks": payload,
            "faults": faults,
        }

    def collect_faults(self, team_name: str) -> dict:
        runtime_faults, read_faults = self._runtime_faults_with_faults(team_name)
        payload = [self._dump_model(fault) for fault in runtime_faults]
        payload.extend(read_faults)
        payload = sorted(
            payload,
            key=lambda fault: fault.get("detectedAt", ""),
            reverse=True,
        )
        return {
            "teamName": team_name,
            "faults": payload,
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
            "faults": faults,
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

        active_jobs_by_worker = {
            job["workerName"]: job
            for job in jobs_data["jobs"]
            if job["state"] in {"queued", "running"}
        }
        latest_session_by_worker = {}
        for session in sessions_data["sessions"]:
            latest_session_by_worker.setdefault(session["workerName"], session)

        workers = []
        for member in members:
            job = active_jobs_by_worker.get(member["name"])
            session = latest_session_by_worker.get(member["name"])
            workers.append(
                {
                    "name": member["name"],
                    "agentId": member["agentId"],
                    "agentType": member["agentType"],
                    "alive": member["alive"],
                    "currentTaskId": (
                        (session or {}).get("currentTaskId")
                        or (job or {}).get("taskId")
                    ),
                    "currentJobId": (session or {}).get("currentJobId") or (job or {}).get("jobId"),
                    "currentSessionId": (session or {}).get("sessionId"),
                    "sessionMode": (session or {}).get("sessionMode"),
                    "callbackPending": (session or {}).get("state") == "callback_pending",
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
            "reported": sum(1 for callback in callbacks_data["callbacks"] if callback["decision"] == "report_progress"),
            "escalated": sum(1 for callback in callbacks_data["callbacks"] if callback["decision"] == "escalate"),
            "blocked": sum(1 for callback in callbacks_data["callbacks"] if callback["decision"] == "blocked"),
        }

        return {
            "summary": {
                "jobs": self._collect_coding(team_name)["summary"],
                "sessions": session_summary,
                "callbacks": callback_summary,
                "faults": {"total": len(faults_data["faults"])},
                "timelineEvents": len(timeline_data["events"]),
            },
            "workers": workers,
            "tasks": task_items,
            "jobs": jobs_data["jobs"],
            "sessions": sessions_data["sessions"],
            "callbacks": callbacks_data["callbacks"],
            "faults": faults_data["faults"],
            "timeline": timeline_data["events"],
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
        store = TaskStore(team_name)

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
        all_tasks = store.list_tasks()
        task_items = []
        grouped: dict[str, list[dict]] = {
            "pending": [],
            "in_progress": [],
            "completed": [],
            "blocked": [],
        }
        for t in all_tasks:
            td = json.loads(t.model_dump_json(by_alias=True, exclude_none=True))
            task_items.append(td)
            grouped[t.status.value].append(td)

        summary = {
            s: len(grouped[s]) for s in grouped
        }
        summary["total"] = len(all_tasks)

        # Find leader name
        leader_name = ""
        for m in config.members:
            if m.agent_id == config.lead_agent_id:
                leader_name = m.name
                break

        # Collect message history from event log (persistent, never consumed)
        all_messages = []
        try:
            events = mailbox.get_event_log(limit=200)
            for msg in events:
                all_messages.append(
                    json.loads(msg.model_dump_json(by_alias=True, exclude_none=True))
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
            "messages": all_messages,
            "cost": cost_data,
            "coding": coding_data,
            "runtimeConsole": runtime_console,
        }

    def collect_overview(self) -> list[dict]:
        """Collect summary data for all teams.

        Returns a list of dicts with keys: name, description, leader,
        members, tasks, pendingMessages.
        """
        teams_meta = TeamManager.discover_teams()
        result = []
        for meta in teams_meta:
            name = meta["name"]
            try:
                data = self.collect_team(name)
                total_inbox = sum(m["inboxCount"] for m in data["members"])
                leader = data["team"].get("leaderName", "")
                result.append({
                    "name": name,
                    "description": meta.get("description", ""),
                    "leader": leader,
                    "members": len(data["members"]),
                    "tasks": data["taskSummary"]["total"],
                    "pendingMessages": total_inbox,
                    "activeCodingJobs": data.get("coding", {}).get("summary", {}).get("active", 0),
                })
            except Exception:
                result.append({
                    "name": name,
                    "description": meta.get("description", ""),
                    "leader": "",
                    "members": meta.get("memberCount", 0),
                    "tasks": 0,
                    "pendingMessages": 0,
                    "activeCodingJobs": 0,
                })
        return result
