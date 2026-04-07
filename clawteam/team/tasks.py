"""Task store for shared team task management."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clawteam.team.models import (
    CallbackLifecyclePhase,
    ReviewLifecyclePhase,
    TaskHandoffContract,
    TaskItem,
    TaskLifecyclePhase,
    TaskStatus,
    WorkerCodingCallbackReport,
    get_data_dir,
)


class TaskLockError(Exception):
    """Raised when a task is locked by another agent."""


class TaskStoreReadError(ValueError):
    """Base class for explicit task-store read faults."""

    fault_type = "task_store_read_error"

    def __init__(
        self,
        *,
        record_kind: str,
        path: Path,
        detail: str,
        team_name: str,
        task_id: str | None = None,
    ):
        self.record_kind = record_kind
        self.path = str(path)
        self.detail = detail
        self.team_name = team_name
        self.task_id = task_id
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        target = f"{self.record_kind} record"
        if self.task_id:
            target += f" for task '{self.task_id}'"
        return f"{target} at '{self.path}' {self.detail}"

    def to_dict(self) -> dict[str, Any]:
        data = {
            "faultType": self.fault_type,
            "recordKind": self.record_kind,
            "path": self.path,
            "teamName": self.team_name,
            "message": str(self),
        }
        if self.task_id:
            data["taskId"] = self.task_id
        return data


class TaskStoreCorruptionError(TaskStoreReadError):
    """Raised when persisted task data is malformed or invalid."""

    fault_type = "corrupt_record"


def _tasks_root(team_name: str) -> Path:
    d = get_data_dir() / "tasks" / team_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _task_path(team_name: str, task_id: str) -> Path:
    return _tasks_root(team_name) / f"task-{task_id}.json"


def _tasks_lock_path(team_name: str) -> Path:
    return _tasks_root(team_name) / ".tasks.lock"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    """File-based task store with dependency tracking.

    Each task is stored as a separate JSON file:
    ``{data_dir}/tasks/{team}/task-{id}.json``
    """

    def __init__(self, team_name: str):
        self.team_name = team_name

    @contextmanager
    def _write_lock(self):
        lock_path = _tasks_lock_path(self.team_name)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def create(
        self,
        subject: str,
        description: str = "",
        owner: str = "",
        blocks: list[str] | None = None,
        blocked_by: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskItem:
        task = TaskItem(
            subject=subject,
            description=description,
            owner=owner,
            blocks=blocks or [],
            blocked_by=blocked_by or [],
            metadata=metadata or {},
        )
        if task.blocked_by:
            task.status = TaskStatus.blocked
            task.task_lifecycle_phase = TaskLifecyclePhase.blocked
        else:
            task.task_lifecycle_phase = TaskLifecyclePhase.planned
        with self._write_lock():
            self._save_unlocked(task)
        return task

    def get(self, task_id: str) -> TaskItem | None:
        return self._get_unlocked(task_id)

    def _get_unlocked(self, task_id: str) -> TaskItem | None:
        path = _task_path(self.team_name, task_id)
        if not path.exists():
            return None
        return self._load_task_from_path(path, task_id=task_id)

    def _load_task_from_path(self, path: Path, *, task_id: str | None = None) -> TaskItem:
        resolved_task_id = task_id or path.stem.removeprefix("task-")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return TaskItem.model_validate(data)
        except Exception as exc:
            raise TaskStoreCorruptionError(
                record_kind="task",
                path=path,
                detail=f"is unreadable or invalid: {exc}",
                team_name=self.team_name,
                task_id=resolved_task_id,
            ) from exc

    def update(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        owner: str | None = None,
        subject: str | None = None,
        description: str | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        caller: str = "",
        force: bool = False,
    ) -> TaskItem | None:
        with self._write_lock():
            task = self._get_unlocked(task_id)
            if not task:
                return None

            # Lock logic when transitioning to in_progress
            if status == TaskStatus.in_progress:
                self._acquire_lock(task, caller, force)
                # Record when work actually started
                if not task.started_at:
                    task.started_at = _now_iso()

            # Clear lock when transitioning to completed or pending
            if status in (TaskStatus.completed, TaskStatus.pending):
                task.locked_by = ""
                task.locked_at = ""

            # Compute duration when completing a task that has a start time
            if status == TaskStatus.completed and task.started_at:
                try:
                    start = datetime.fromisoformat(task.started_at)
                    duration_secs = (datetime.now(timezone.utc) - start).total_seconds()
                    task.metadata["duration_seconds"] = round(duration_secs, 2)
                except (ValueError, TypeError):
                    pass  # malformed timestamp, skip

            if status is not None:
                task.status = status
                task.task_lifecycle_phase = self._task_phase_for_status(status)
            if owner is not None:
                task.owner = owner
            if subject is not None:
                task.subject = subject
            if description is not None:
                task.description = description
            if add_blocks:
                for b in add_blocks:
                    if b not in task.blocks:
                        task.blocks.append(b)
            if add_blocked_by:
                for b in add_blocked_by:
                    if b not in task.blocked_by:
                        task.blocked_by.append(b)
            if metadata:
                task.metadata.update(metadata)
            task.updated_at = _now_iso()

            if task.status == TaskStatus.completed:
                self._resolve_dependents_unlocked(task_id)

            self._save_unlocked(task)
            return task

    def _acquire_lock(self, task: TaskItem, caller: str, force: bool) -> None:
        """Acquire lock on a task for the caller agent."""
        if task.locked_by and task.locked_by != caller and not force:
            # Check if lock holder is still alive via spawn registry
            from clawteam.spawn.registry import is_agent_alive
            alive = is_agent_alive(self.team_name, task.locked_by)
            if alive is not False:
                # Lock holder is alive or unknown — refuse
                raise TaskLockError(
                    f"Task '{task.id}' is locked by '{task.locked_by}' "
                    f"(since {task.locked_at}). Use --force to override."
                )
            # Lock holder is dead — release and continue

        task.locked_by = caller or ""
        task.locked_at = _now_iso() if caller else ""

    def release_stale_locks(self) -> list[str]:
        """Scan all tasks and release locks held by dead agents.

        Returns list of task IDs whose locks were released.
        """
        from clawteam.spawn.registry import is_agent_alive

        released = []
        with self._write_lock():
            for task in self._list_tasks_unlocked():
                if not task.locked_by:
                    continue
                alive = is_agent_alive(self.team_name, task.locked_by)
                if alive is False:
                    task.locked_by = ""
                    task.locked_at = ""
                    task.updated_at = _now_iso()
                    self._save_unlocked(task)
                    released.append(task.id)
        return released

    def list_tasks(
        self, status: TaskStatus | None = None, owner: str | None = None
    ) -> list[TaskItem]:
        return self._list_tasks_unlocked(status=status, owner=owner)

    def inspect_tasks(
        self,
        status: TaskStatus | None = None,
        owner: str | None = None,
    ) -> tuple[list[TaskItem], list[dict[str, Any]]]:
        root = _tasks_root(self.team_name)
        tasks: list[TaskItem] = []
        faults: list[dict[str, Any]] = []
        for path in sorted(root.glob("task-*.json")):
            try:
                task = self._load_task_from_path(path)
            except TaskStoreReadError as exc:
                faults.append(exc.to_dict())
                continue
            if status and task.status != status:
                continue
            if owner and task.owner != owner:
                continue
            tasks.append(task)
        return tasks, faults

    def _list_tasks_unlocked(
        self, status: TaskStatus | None = None, owner: str | None = None
    ) -> list[TaskItem]:
        root = _tasks_root(self.team_name)
        tasks: list[TaskItem] = []
        for path in sorted(root.glob("task-*.json")):
            task = self._load_task_from_path(path)
            if status and task.status != status:
                continue
            if owner and task.owner != owner:
                continue
            tasks.append(task)
        return tasks

    def get_stats(self) -> dict[str, Any]:
        """Aggregate task timing stats for this team.

        Returns dict with total tasks, completed count, and avg duration
        (only counting tasks that have duration_seconds in metadata).
        """
        tasks, read_faults = self.inspect_tasks()
        completed = [t for t in tasks if t.status == TaskStatus.completed]
        durations = [
            t.metadata["duration_seconds"]
            for t in completed
            if "duration_seconds" in t.metadata
        ]
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        return {
            "total": len(tasks),
            "completed": len(completed),
            "in_progress": sum(1 for t in tasks if t.status == TaskStatus.in_progress),
            "pending": sum(1 for t in tasks if t.status == TaskStatus.pending),
            "blocked": sum(1 for t in tasks if t.status == TaskStatus.blocked),
            "timed_completed": len(durations),
            "avg_duration_seconds": round(avg_duration, 2),
            "readFaults": read_faults,
        }

    def record_coding_callback(
        self,
        task_id: str,
        report: WorkerCodingCallbackReport,
    ) -> TaskItem | None:
        """Persist the latest coding callback summary onto task metadata."""
        with self._write_lock():
            task = self._get_unlocked(task_id)
            if not task:
                return None
        from clawteam.coding.service import CodingService

        updated_job = CodingService().record_callback_report(self.team_name, report)

        with self._write_lock():
            task = self._get_unlocked(task_id)
            if not task:
                raise ValueError(f"Task '{task_id}' disappeared before callback metadata could be persisted.")
            callback_summary = json.loads(report.model_dump_json(by_alias=True, exclude_none=True))
            handoff_contract = report.handoff_contract or TaskHandoffContract(
                taskIdentity=report.task_id or report.job_id,
                objective=report.summary,
                inputs=[],
                outputs=sorted((report.artifact_paths or {}).keys()),
                validation="",
                blockers=[],
                risks=[],
                recommendedNextStep=report.next_step,
                callbackExpectation=report.callback_expectation or "team_leader_ack",
            )
            handoff_summary = json.loads(handoff_contract.model_dump_json(by_alias=True, exclude_none=True))
            handoff_missing_fields = handoff_contract.missing_fields()
            handoff_complete = len(handoff_missing_fields) == 0
            callback_phase = self._callback_phase_for_decision(
                report.decision.value,
                handoff_complete=handoff_complete,
            )
            review_phase = self._review_phase_for_callback(callback_phase)
            coding_meta = {
                "latestJobId": report.job_id,
                "provider": report.provider,
                "status": report.status,
                "decision": report.decision.value,
                "summary": report.summary,
                "artifactPaths": dict(report.artifact_paths),
                "reportedAt": report.reported_at,
                "callbackExpectation": report.callback_expectation,
                "handoffContract": handoff_summary,
                "handoffComplete": handoff_complete,
                "handoffMissingFields": handoff_missing_fields,
            }
            history = list(task.metadata.get("codingHistory", []))
            history.append(callback_summary)
            task.metadata["coding"] = coding_meta
            task.metadata["codingHistory"] = history
            task.metadata["handoff"] = handoff_summary
            task.metadata["lifecycle"] = {
                "taskLifecyclePhase": (
                    TaskLifecyclePhase.review.value
                    if callback_phase in {CallbackLifecyclePhase.reported, CallbackLifecyclePhase.closed}
                    else TaskLifecyclePhase.handoff.value
                ),
                "callbackLifecyclePhase": callback_phase.value,
                "reviewLifecyclePhase": review_phase.value,
                "handoffComplete": handoff_complete,
                "handoffMissingFields": handoff_missing_fields,
            }
            task.callback_lifecycle_phase = callback_phase
            task.review_lifecycle_phase = review_phase
            task.handoff_complete = handoff_complete
            task.handoff_missing_fields = handoff_missing_fields
            if callback_phase in {CallbackLifecyclePhase.reported, CallbackLifecyclePhase.closed}:
                task.task_lifecycle_phase = TaskLifecyclePhase.review
            else:
                task.task_lifecycle_phase = TaskLifecyclePhase.handoff
            try:
                from clawteam.team.manager import TeamManager
                from clawteam.team.session_bridge import SessionBridge

                config = TeamManager.get_team(self.team_name)
                if config:
                    worker_member = TeamManager.get_member_by_identity(
                        self.team_name,
                        agent_id=updated_job.worker_id,
                        member_name=updated_job.worker_name,
                    )
                    leader_member = next(
                        (member for member in config.members if member.agent_id == config.lead_agent_id),
                        None,
                    )
                    if worker_member and leader_member:
                        notice = SessionBridge().notify_worker_to_leader(
                            team_name=self.team_name,
                            worker_member=worker_member,
                            leader_member=leader_member,
                            task_id=report.task_id,
                            job_id=report.job_id,
                            payload={
                                "summary": report.summary,
                                "decision": report.decision.value,
                                "callbackExpectation": report.callback_expectation,
                            },
                        )
                        task.metadata["sessionBridgeNoticeId"] = notice.notice_id
            except Exception:
                # Session bridge notice is optional acceleration prep only.
                pass
            task.updated_at = _now_iso()
            self._save_unlocked(task)
            return task

    def _save_unlocked(self, task: TaskItem) -> None:
        path = _task_path(self.team_name, task.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f"{path.stem}-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(task.model_dump_json(indent=2, by_alias=True))
            Path(tmp_name).replace(path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def _resolve_dependents_unlocked(self, completed_task_id: str) -> None:
        root = _tasks_root(self.team_name)
        for f in root.glob("task-*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                task = TaskItem.model_validate(data)
                if completed_task_id in task.blocked_by:
                    task.blocked_by.remove(completed_task_id)
                    if not task.blocked_by and task.status == TaskStatus.blocked:
                        task.status = TaskStatus.pending
                    task.updated_at = _now_iso()
                    self._save_unlocked(task)
            except Exception:
                continue

    def _task_phase_for_status(self, status: TaskStatus) -> TaskLifecyclePhase:
        if status == TaskStatus.in_progress:
            return TaskLifecyclePhase.execution
        if status == TaskStatus.completed:
            return TaskLifecyclePhase.completed
        if status == TaskStatus.blocked:
            return TaskLifecyclePhase.blocked
        return TaskLifecyclePhase.planned

    def _callback_phase_for_decision(
        self,
        decision: str,
        *,
        handoff_complete: bool,
    ) -> CallbackLifecyclePhase:
        if decision == "continue":
            return CallbackLifecyclePhase.pending
        if decision == "escalate":
            return CallbackLifecyclePhase.escalated
        if decision == "blocked":
            return CallbackLifecyclePhase.blocked
        if decision == "complete":
            return CallbackLifecyclePhase.closed
        if handoff_complete:
            return CallbackLifecyclePhase.reported
        return CallbackLifecyclePhase.incomplete

    def _review_phase_for_callback(self, callback_phase: CallbackLifecyclePhase) -> ReviewLifecyclePhase:
        if callback_phase in {
            CallbackLifecyclePhase.reported,
            CallbackLifecyclePhase.closed,
            CallbackLifecyclePhase.incomplete,
            CallbackLifecyclePhase.escalated,
            CallbackLifecyclePhase.blocked,
        }:
            return ReviewLifecyclePhase.pending
        return ReviewLifecyclePhase.not_started
