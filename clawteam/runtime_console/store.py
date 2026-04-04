"""Durable file-backed store for runtime console objects."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from clawteam.runtime_console.models import (
    CallbackReportRecord,
    ProviderSessionRecord,
    RUNTIME_CONSOLE_SCHEMA_VERSION,
    RuntimeFaultRecord,
    RuntimeTimelineEvent,
)
from clawteam.team.models import get_data_dir


class RuntimeConsoleStoreReadError(ValueError):
    """Base class for explicit runtime-console durable read faults."""

    def __init__(self, message: str):
        super().__init__(message)


class RuntimeConsoleStoreCorruptionError(RuntimeConsoleStoreReadError):
    """Raised when a runtime-console record is malformed."""


class RuntimeConsoleStoreSchemaError(RuntimeConsoleStoreReadError):
    """Raised when a runtime-console record has an incompatible schema version."""


def _runtime_root() -> Path:
    root = get_data_dir() / "runtime-console"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _provider_sessions_root(team_name: str) -> Path:
    root = _runtime_root() / "provider-sessions" / team_name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _callbacks_root(team_name: str) -> Path:
    root = _runtime_root() / "callbacks" / team_name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _faults_root(team_name: str) -> Path:
    root = _runtime_root() / "faults" / team_name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _timeline_root(team_name: str) -> Path:
    root = _runtime_root() / "timeline" / team_name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _lock_path(team_name: str) -> Path:
    return _runtime_root() / "locks" / f"{team_name}.lock"


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


class RuntimeConsoleStore:
    """Durable persistence for provider sessions, callback reports, faults, and timeline."""

    @contextmanager
    def _write_lock(self, team_name: str):
        path = _lock_path(team_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def provider_session_path(self, team_name: str, session_id: str) -> Path:
        return _provider_sessions_root(team_name) / f"{session_id}.json"

    def callback_path(self, team_name: str, job_id: str) -> Path:
        return _callbacks_root(team_name) / f"{job_id}.json"

    def fault_path(self, team_name: str, fault_id: str) -> Path:
        return _faults_root(team_name) / f"{fault_id}.json"

    def save_provider_session(self, record: ProviderSessionRecord) -> ProviderSessionRecord:
        with self._write_lock(record.team_name):
            _atomic_write_text(
                self.provider_session_path(record.team_name, record.session_id),
                record.model_dump_json(indent=2, by_alias=True, exclude_none=True),
            )
        return record

    def get_provider_session(self, team_name: str, session_id: str) -> ProviderSessionRecord | None:
        path = self.provider_session_path(team_name, session_id)
        if not path.exists():
            return None
        return self._load_model(path, ProviderSessionRecord)

    def list_provider_sessions(self, team_name: str) -> list[ProviderSessionRecord]:
        return self._list_models(_provider_sessions_root(team_name).glob("*.json"), ProviderSessionRecord)

    def save_callback_report(self, record: CallbackReportRecord) -> CallbackReportRecord:
        with self._write_lock(record.team_name):
            _atomic_write_text(
                self.callback_path(record.team_name, record.job_id),
                record.model_dump_json(indent=2, by_alias=True, exclude_none=True),
            )
        return record

    def load_callback_report(self, team_name: str, job_id: str) -> CallbackReportRecord | None:
        path = self.callback_path(team_name, job_id)
        if not path.exists():
            return None
        return self._load_model(path, CallbackReportRecord)

    def list_callback_reports(self, team_name: str) -> list[CallbackReportRecord]:
        return self._list_models(_callbacks_root(team_name).glob("*.json"), CallbackReportRecord)

    def save_fault(self, record: RuntimeFaultRecord) -> RuntimeFaultRecord:
        with self._write_lock(record.team_name):
            _atomic_write_text(
                self.fault_path(record.team_name, record.fault_id),
                record.model_dump_json(indent=2, by_alias=True, exclude_none=True),
            )
        return record

    def get_fault(self, team_name: str, fault_id: str) -> RuntimeFaultRecord | None:
        path = self.fault_path(team_name, fault_id)
        if not path.exists():
            return None
        return self._load_model(path, RuntimeFaultRecord)

    def list_faults(self, team_name: str) -> list[RuntimeFaultRecord]:
        return self._list_models(_faults_root(team_name).glob("*.json"), RuntimeFaultRecord)

    def append_timeline_event(self, team_name: str, event: RuntimeTimelineEvent) -> RuntimeTimelineEvent:
        path = _timeline_root(team_name) / f"{event.timestamp}-{event.event_id}.json"
        with self._write_lock(team_name):
            _atomic_write_text(path, event.model_dump_json(indent=2, by_alias=True, exclude_none=True))
        return event

    def list_timeline(self, team_name: str) -> list[RuntimeTimelineEvent]:
        return self._list_models(sorted(_timeline_root(team_name).glob("*.json")), RuntimeTimelineEvent)

    def storage_roots(self, team_name: str) -> dict[str, str]:
        root = _runtime_root()
        return {
            "providerSessionsRoot": str(root / "provider-sessions" / team_name),
            "callbacksRoot": str(root / "callbacks" / team_name),
            "faultsRoot": str(root / "faults" / team_name),
            "timelineRoot": str(root / "timeline" / team_name),
        }

    def _list_models(self, paths, model_type: type[BaseModel]) -> list[Any]:
        return [self._load_model(path, model_type) for path in sorted(paths)]

    def _load_model(self, path: Path, model_type: type[BaseModel]) -> Any:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except JSONDecodeError as exc:
            raise RuntimeConsoleStoreCorruptionError(
                f"Runtime console record at '{path}' is corrupt JSON: {exc.msg}"
            ) from exc
        schema_version = payload.get("schemaVersion", RUNTIME_CONSOLE_SCHEMA_VERSION)
        if schema_version != RUNTIME_CONSOLE_SCHEMA_VERSION:
            raise RuntimeConsoleStoreSchemaError(
                f"Runtime console record at '{path}' uses schemaVersion={schema_version}, "
                f"expected {RUNTIME_CONSOLE_SCHEMA_VERSION}"
            )
        try:
            return model_type.model_validate(payload)
        except ValidationError as exc:
            raise RuntimeConsoleStoreCorruptionError(
                f"Runtime console record at '{path}' failed validation: {exc.errors()[0]['msg']}"
            ) from exc
