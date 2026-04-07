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
    RuntimeEvidenceRecord,
    RuntimeFaultRecord,
    RuntimeTimelineEvent,
)
from clawteam.team.models import get_data_dir


class RuntimeConsoleStoreReadError(ValueError):
    """Base class for explicit runtime-console durable read faults."""

    fault_type = "runtime_console_read_error"

    def __init__(
        self,
        *,
        record_kind: str,
        path: Path,
        detail: str,
        team_name: str,
        record_id: str | None = None,
    ):
        self.record_kind = record_kind
        self.path = str(path)
        self.detail = detail
        self.team_name = team_name
        self.record_id = record_id
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        target = f"{self.record_kind} record"
        if self.record_id:
            target += f" '{self.record_id}'"
        return f"{target} at '{self.path}' {self.detail}"

    def to_dict(self) -> dict[str, Any]:
        data = {
            "faultType": self.fault_type,
            "recordKind": self.record_kind,
            "path": self.path,
            "teamName": self.team_name,
            "message": str(self),
        }
        if self.record_id:
            data["recordId"] = self.record_id
        return data


class RuntimeConsoleStoreCorruptionError(RuntimeConsoleStoreReadError):
    """Raised when a runtime-console record is malformed."""

    fault_type = "corrupt_record"


class RuntimeConsoleStoreSchemaError(RuntimeConsoleStoreReadError):
    """Raised when a runtime-console record has an incompatible schema version."""

    fault_type = "schema_incompatible"


class RuntimeConsoleStoreAggregateReadError(RuntimeConsoleStoreReadError):
    """Raised when a collection scan finds one or more invalid runtime-console records."""

    fault_type = "aggregate_read_error"

    def __init__(
        self,
        *,
        record_kind: str,
        team_name: str,
        errors: list[RuntimeConsoleStoreReadError],
        records: list[Any],
    ):
        self.errors = errors
        self.records = records
        super().__init__(
            record_kind=record_kind,
            path=_runtime_root() / record_kind,
            detail=(
                f"found {len(errors)} invalid persisted {record_kind} record(s); "
                "inspect `errors` for details"
            ),
            team_name=team_name,
        )

    def to_faults(self) -> list[dict[str, Any]]:
        return [error.to_dict() for error in self.errors]


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


def _evidence_root(team_name: str) -> Path:
    root = _runtime_root() / "evidence" / team_name
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

    def evidence_path(self, team_name: str, evidence_id: str) -> Path:
        return _evidence_root(team_name) / f"{evidence_id}.json"

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
        return self._load_model(
            path,
            ProviderSessionRecord,
            record_kind="provider_session",
            team_name=team_name,
        )

    def list_provider_sessions(self, team_name: str) -> list[ProviderSessionRecord]:
        records, errors = self._inspect_models(
            _provider_sessions_root(team_name).glob("*.json"),
            ProviderSessionRecord,
            record_kind="provider_session",
            team_name=team_name,
        )
        if errors:
            raise RuntimeConsoleStoreAggregateReadError(
                record_kind="provider_session",
                team_name=team_name,
                errors=errors,
                records=records,
            )
        return records

    def inspect_provider_sessions(
        self,
        team_name: str,
    ) -> tuple[list[ProviderSessionRecord], list[dict[str, Any]]]:
        records, errors = self._inspect_models(
            _provider_sessions_root(team_name).glob("*.json"),
            ProviderSessionRecord,
            record_kind="provider_session",
            team_name=team_name,
        )
        return records, [error.to_dict() for error in errors]

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
        return self._load_model(
            path,
            CallbackReportRecord,
            record_kind="callback",
            team_name=team_name,
        )

    def list_callback_reports(self, team_name: str) -> list[CallbackReportRecord]:
        records, errors = self._inspect_models(
            _callbacks_root(team_name).glob("*.json"),
            CallbackReportRecord,
            record_kind="callback",
            team_name=team_name,
        )
        if errors:
            raise RuntimeConsoleStoreAggregateReadError(
                record_kind="callback",
                team_name=team_name,
                errors=errors,
                records=records,
            )
        return records

    def inspect_callback_reports(
        self,
        team_name: str,
    ) -> tuple[list[CallbackReportRecord], list[dict[str, Any]]]:
        records, errors = self._inspect_models(
            _callbacks_root(team_name).glob("*.json"),
            CallbackReportRecord,
            record_kind="callback",
            team_name=team_name,
        )
        return records, [error.to_dict() for error in errors]

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
        return self._load_model(
            path,
            RuntimeFaultRecord,
            record_kind="fault",
            team_name=team_name,
        )

    def list_faults(self, team_name: str) -> list[RuntimeFaultRecord]:
        records, errors = self._inspect_models(
            _faults_root(team_name).glob("*.json"),
            RuntimeFaultRecord,
            record_kind="fault",
            team_name=team_name,
        )
        if errors:
            raise RuntimeConsoleStoreAggregateReadError(
                record_kind="fault",
                team_name=team_name,
                errors=errors,
                records=records,
            )
        return records

    def inspect_faults(
        self,
        team_name: str,
    ) -> tuple[list[RuntimeFaultRecord], list[dict[str, Any]]]:
        records, errors = self._inspect_models(
            _faults_root(team_name).glob("*.json"),
            RuntimeFaultRecord,
            record_kind="fault",
            team_name=team_name,
        )
        return records, [error.to_dict() for error in errors]

    def append_timeline_event(self, team_name: str, event: RuntimeTimelineEvent) -> RuntimeTimelineEvent:
        path = _timeline_root(team_name) / f"{event.timestamp}-{event.event_id}.json"
        with self._write_lock(team_name):
            _atomic_write_text(path, event.model_dump_json(indent=2, by_alias=True, exclude_none=True))
        return event

    def list_timeline(self, team_name: str) -> list[RuntimeTimelineEvent]:
        records, errors = self._inspect_models(
            sorted(_timeline_root(team_name).glob("*.json")),
            RuntimeTimelineEvent,
            record_kind="timeline",
            team_name=team_name,
        )
        if errors:
            raise RuntimeConsoleStoreAggregateReadError(
                record_kind="timeline",
                team_name=team_name,
                errors=errors,
                records=records,
            )
        return records

    def inspect_timeline(
        self,
        team_name: str,
    ) -> tuple[list[RuntimeTimelineEvent], list[dict[str, Any]]]:
        records, errors = self._inspect_models(
            sorted(_timeline_root(team_name).glob("*.json")),
            RuntimeTimelineEvent,
            record_kind="timeline",
            team_name=team_name,
        )
        return records, [error.to_dict() for error in errors]

    def save_evidence(self, record: RuntimeEvidenceRecord) -> RuntimeEvidenceRecord:
        with self._write_lock(record.team_name):
            _atomic_write_text(
                self.evidence_path(record.team_name, record.evidence_id),
                record.model_dump_json(indent=2, by_alias=True, exclude_none=True),
            )
        return record

    def get_evidence(self, team_name: str, evidence_id: str) -> RuntimeEvidenceRecord | None:
        path = self.evidence_path(team_name, evidence_id)
        if not path.exists():
            return None
        return self._load_model(
            path,
            RuntimeEvidenceRecord,
            record_kind="evidence",
            team_name=team_name,
        )

    def list_evidence(self, team_name: str) -> list[RuntimeEvidenceRecord]:
        records, errors = self._inspect_models(
            _evidence_root(team_name).glob("*.json"),
            RuntimeEvidenceRecord,
            record_kind="evidence",
            team_name=team_name,
        )
        if errors:
            raise RuntimeConsoleStoreAggregateReadError(
                record_kind="evidence",
                team_name=team_name,
                errors=errors,
                records=records,
            )
        return records

    def inspect_evidence(
        self,
        team_name: str,
    ) -> tuple[list[RuntimeEvidenceRecord], list[dict[str, Any]]]:
        records, errors = self._inspect_models(
            _evidence_root(team_name).glob("*.json"),
            RuntimeEvidenceRecord,
            record_kind="evidence",
            team_name=team_name,
        )
        return records, [error.to_dict() for error in errors]

    def storage_roots(self, team_name: str) -> dict[str, str]:
        root = _runtime_root()
        return {
            "providerSessionsRoot": str(root / "provider-sessions" / team_name),
            "callbacksRoot": str(root / "callbacks" / team_name),
            "faultsRoot": str(root / "faults" / team_name),
            "timelineRoot": str(root / "timeline" / team_name),
            "evidenceRoot": str(root / "evidence" / team_name),
        }

    def _load_model(
        self,
        path: Path,
        model_type: type[BaseModel],
        *,
        record_kind: str,
        team_name: str,
    ) -> Any:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except JSONDecodeError as exc:
            raise RuntimeConsoleStoreCorruptionError(
                record_kind=record_kind,
                path=path,
                detail=f"is corrupt JSON: {exc.msg}",
                team_name=team_name,
                record_id=path.stem,
            ) from exc
        schema_version = payload.get("schemaVersion", RUNTIME_CONSOLE_SCHEMA_VERSION)
        if schema_version != RUNTIME_CONSOLE_SCHEMA_VERSION:
            raise RuntimeConsoleStoreSchemaError(
                record_kind=record_kind,
                path=path,
                detail=(
                    f"uses schemaVersion={schema_version}, "
                    f"expected {RUNTIME_CONSOLE_SCHEMA_VERSION}"
                ),
                team_name=team_name,
                record_id=path.stem,
            )
        try:
            return model_type.model_validate(payload)
        except ValidationError as exc:
            raise RuntimeConsoleStoreCorruptionError(
                record_kind=record_kind,
                path=path,
                detail=f"failed validation: {exc.errors()[0]['msg']}",
                team_name=team_name,
                record_id=path.stem,
            ) from exc

    def _inspect_models(
        self,
        paths,
        model_type: type[BaseModel],
        *,
        record_kind: str,
        team_name: str,
    ) -> tuple[list[Any], list[RuntimeConsoleStoreReadError]]:
        records: list[Any] = []
        errors: list[RuntimeConsoleStoreReadError] = []
        for path in sorted(paths):
            try:
                records.append(
                    self._load_model(
                        path,
                        model_type,
                        record_kind=record_kind,
                        team_name=team_name,
                    )
                )
            except RuntimeConsoleStoreReadError as exc:
                errors.append(exc)
        return records, errors
