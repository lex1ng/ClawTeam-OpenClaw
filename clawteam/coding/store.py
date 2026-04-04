"""Durable storage for coding runtime jobs, events, results, and artifacts."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from clawteam.coding.models import (
    PERSISTED_CODING_SCHEMA_VERSION,
    CodingExecResult,
    CodingJobEvent,
    CodingJobRecord,
)
from clawteam.team.models import get_data_dir


def _coding_root() -> Path:
    root = get_data_dir() / "coding"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _jobs_root(team_name: str) -> Path:
    root = _coding_root() / "jobs" / team_name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _events_root(team_name: str, job_id: str) -> Path:
    root = _coding_root() / "events" / team_name / job_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _results_root(team_name: str) -> Path:
    root = _coding_root() / "results" / team_name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _artifacts_root(team_name: str, job_id: str) -> Path:
    root = _coding_root() / "artifacts" / team_name / job_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _team_lock_path(team_name: str) -> Path:
    return _jobs_root(team_name) / ".coding.lock"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(text)
        Path(tmp_name).replace(path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


class CodingStoreReadError(ValueError):
    """Base class for explicit durable-store read faults."""

    fault_type = "store_read_error"

    def __init__(
        self,
        *,
        record_kind: str,
        path: Path,
        detail: str,
        team_name: str,
        job_id: str | None = None,
    ):
        self.record_kind = record_kind
        self.path = str(path)
        self.detail = detail
        self.team_name = team_name
        self.job_id = job_id
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        target = f"{self.record_kind} record"
        if self.job_id:
            target += f" for job '{self.job_id}'"
        return f"{target} at '{self.path}' {self.detail}"

    def to_dict(self) -> dict[str, Any]:
        data = {
            "faultType": self.fault_type,
            "recordKind": self.record_kind,
            "path": self.path,
            "teamName": self.team_name,
            "message": str(self),
        }
        if self.job_id:
            data["jobId"] = self.job_id
        return data


class CodingStoreCorruptionError(CodingStoreReadError):
    """Raised when persisted JSON is malformed or invalid for the current schema."""

    fault_type = "corrupt_record"


class CodingStoreSchemaError(CodingStoreReadError):
    """Raised when persisted data declares an incompatible schema version."""

    fault_type = "schema_incompatible"


class CodingStoreAggregateReadError(CodingStoreReadError):
    """Raised when a collection scan finds one or more explicit read faults."""

    fault_type = "aggregate_read_error"

    def __init__(
        self,
        *,
        record_kind: str,
        team_name: str,
        errors: list[CodingStoreReadError],
        records: list[Any],
        job_id: str | None = None,
    ):
        self.errors = errors
        self.records = records
        detail = (
            f"found {len(errors)} invalid persisted {record_kind} record(s); "
            "inspect `errors` for details"
        )
        path = _coding_root() / record_kind
        super().__init__(
            record_kind=record_kind,
            path=path,
            detail=detail,
            team_name=team_name,
            job_id=job_id,
        )

    def to_faults(self) -> list[dict[str, Any]]:
        return [error.to_dict() for error in self.errors]


class CodingJobStore:
    """File-backed store for coding runtime observability and recovery."""

    @contextmanager
    def _write_lock(self, team_name: str):
        lock_path = _team_lock_path(team_name)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def job_path(self, team_name: str, job_id: str) -> Path:
        return _jobs_root(team_name) / f"{job_id}.json"

    def result_path(self, team_name: str, job_id: str) -> Path:
        return _results_root(team_name) / f"{job_id}.json"

    def artifact_path(self, team_name: str, job_id: str, artifact_name: str) -> Path:
        return _artifacts_root(team_name, job_id) / artifact_name

    def create_job(self, record: CodingJobRecord) -> CodingJobRecord:
        with self._write_lock(record.team_name):
            self._save_job_unlocked(record)
        return record

    def create_job_atomically(
        self,
        record: CodingJobRecord,
        *,
        created_event: CodingJobEvent | None = None,
        ensure_capacity: Callable[[list[CodingJobRecord]], None] | None = None,
    ) -> CodingJobRecord:
        with self._write_lock(record.team_name):
            jobs, errors = self._list_models_unlocked(
                _jobs_root(record.team_name).glob("*.json"),
                model_type=CodingJobRecord,
                record_kind="job",
                team_name=record.team_name,
            )
            if errors:
                raise CodingStoreAggregateReadError(
                    record_kind="job",
                    team_name=record.team_name,
                    errors=errors,
                    records=jobs,
                )
            if ensure_capacity is not None:
                ensure_capacity(jobs)
            self._before_atomic_create_persist(record=record, existing_jobs=jobs)
            self._save_job_unlocked(record)
            if created_event is not None:
                self._append_event_unlocked(created_event)
        return record

    def _before_atomic_create_persist(
        self,
        *,
        record: CodingJobRecord,
        existing_jobs: list[CodingJobRecord],
    ) -> None:
        """Test hook for deterministic coordination inside the atomic create critical section."""

    def save_job(self, record: CodingJobRecord) -> CodingJobRecord:
        with self._write_lock(record.team_name):
            self._save_job_unlocked(record)
        return record

    def _save_job_unlocked(self, record: CodingJobRecord) -> None:
        path = self.job_path(record.team_name, record.job_id)
        _atomic_write_text(path, record.model_dump_json(indent=2, by_alias=True, exclude_none=True))

    def get_job(self, team_name: str, job_id: str) -> CodingJobRecord | None:
        path = self.job_path(team_name, job_id)
        if not path.exists():
            return None
        return self._load_model(
            path,
            model_type=CodingJobRecord,
            record_kind="job",
            team_name=team_name,
            job_id=job_id,
        )

    def list_jobs(self, team_name: str) -> list[CodingJobRecord]:
        jobs, errors = self._list_models_unlocked(
            sorted(_jobs_root(team_name).glob("*.json")),
            model_type=CodingJobRecord,
            record_kind="job",
            team_name=team_name,
        )
        if errors:
            raise CodingStoreAggregateReadError(
                record_kind="job",
                team_name=team_name,
                errors=errors,
                records=jobs,
            )
        return jobs

    def inspect_jobs(self, team_name: str) -> tuple[list[CodingJobRecord], list[dict[str, Any]]]:
        jobs, errors = self._list_models_unlocked(
            sorted(_jobs_root(team_name).glob("*.json")),
            model_type=CodingJobRecord,
            record_kind="job",
            team_name=team_name,
        )
        return jobs, [error.to_dict() for error in errors]

    def append_event(self, event: CodingJobEvent) -> CodingJobEvent:
        path = _events_root(event.team_name, event.job_id) / f"{event.created_at}-{event.event_id}.json"
        with self._write_lock(event.team_name):
            self._append_event_unlocked(event)
        return event

    def _append_event_unlocked(self, event: CodingJobEvent) -> None:
        path = _events_root(event.team_name, event.job_id) / f"{event.created_at}-{event.event_id}.json"
        _atomic_write_text(path, event.model_dump_json(indent=2, by_alias=True, exclude_none=True))

    def list_events(self, team_name: str, job_id: str) -> list[CodingJobEvent]:
        events, errors = self._list_models_unlocked(
            sorted(_events_root(team_name, job_id).glob("*.json")),
            model_type=CodingJobEvent,
            record_kind="event",
            team_name=team_name,
            job_id=job_id,
        )
        if errors:
            raise CodingStoreAggregateReadError(
                record_kind="event",
                team_name=team_name,
                errors=errors,
                records=events,
                job_id=job_id,
            )
        return events

    def save_result(self, team_name: str, job_id: str, result: CodingExecResult) -> str:
        path = self.result_path(team_name, job_id)
        with self._write_lock(team_name):
            _atomic_write_text(path, result.model_dump_json(indent=2, by_alias=True, exclude_none=True))
        return str(path)

    def load_result(self, team_name: str, job_id: str) -> CodingExecResult | None:
        path = self.result_path(team_name, job_id)
        if not path.exists():
            return None
        return self._load_model(
            path,
            model_type=CodingExecResult,
            record_kind="result",
            team_name=team_name,
            job_id=job_id,
        )

    def save_text_artifact(
        self,
        team_name: str,
        job_id: str,
        artifact_name: str,
        content: str,
    ) -> str:
        path = self.artifact_path(team_name, job_id, artifact_name)
        with self._write_lock(team_name):
            _atomic_write_text(path, content)
        return str(path)

    def save_json_artifact(
        self,
        team_name: str,
        job_id: str,
        artifact_name: str,
        payload: dict[str, Any],
    ) -> str:
        path = self.artifact_path(team_name, job_id, artifact_name)
        with self._write_lock(team_name):
            _atomic_write_text(path, _dump_json(payload))
        return str(path)

    def _load_model(
        self,
        path: Path,
        *,
        model_type: type[BaseModel],
        record_kind: str,
        team_name: str,
        job_id: str | None = None,
    ) -> BaseModel:
        payload = self._read_payload(
            path,
            record_kind=record_kind,
            team_name=team_name,
            job_id=job_id,
        )
        try:
            return model_type.model_validate(payload)
        except ValidationError as exc:
            raise CodingStoreCorruptionError(
                record_kind=record_kind,
                path=path,
                detail=f"is corrupt for schemaVersion={PERSISTED_CODING_SCHEMA_VERSION}: {exc.errors()[0]['msg']}",
                team_name=team_name,
                job_id=job_id,
            ) from exc

    def _read_payload(
        self,
        path: Path,
        *,
        record_kind: str,
        team_name: str,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CodingStoreCorruptionError(
                record_kind=record_kind,
                path=path,
                detail=f"is unreadable: {exc}",
                team_name=team_name,
                job_id=job_id,
            ) from exc
        try:
            payload = json.loads(raw)
        except JSONDecodeError as exc:
            raise CodingStoreCorruptionError(
                record_kind=record_kind,
                path=path,
                detail=f"is corrupt JSON: {exc.msg}",
                team_name=team_name,
                job_id=job_id,
            ) from exc
        if not isinstance(payload, dict):
            raise CodingStoreCorruptionError(
                record_kind=record_kind,
                path=path,
                detail="is corrupt: top-level JSON value must be an object",
                team_name=team_name,
                job_id=job_id,
            )
        schema_version = payload.get("schemaVersion", PERSISTED_CODING_SCHEMA_VERSION)
        if schema_version != PERSISTED_CODING_SCHEMA_VERSION:
            raise CodingStoreSchemaError(
                record_kind=record_kind,
                path=path,
                detail=(
                    f"uses schemaVersion={schema_version}, "
                    f"expected {PERSISTED_CODING_SCHEMA_VERSION}"
                ),
                team_name=team_name,
                job_id=job_id,
            )
        return payload

    def _list_models_unlocked(
        self,
        paths,
        *,
        model_type: type[BaseModel],
        record_kind: str,
        team_name: str,
        job_id: str | None = None,
    ) -> tuple[list[Any], list[CodingStoreReadError]]:
        records: list[Any] = []
        errors: list[CodingStoreReadError] = []
        for path in paths:
            record_job_id = path.stem if record_kind == "job" else job_id
            try:
                records.append(
                    self._load_model(
                        path,
                        model_type=model_type,
                        record_kind=record_kind,
                        team_name=team_name,
                        job_id=record_job_id,
                    )
                )
            except CodingStoreReadError as exc:
                errors.append(exc)
        return records, errors
