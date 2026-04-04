"""Base interfaces and shared logic for coding CLI harnesses."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from typing import Any, Protocol

from pydantic import BaseModel, Field

from clawteam.coding.models import (
    CodingExecRequest,
    CodingExecResult,
    CodingJobState,
    CodingProvider,
    ResolvedStartupPolicy,
)


class HarnessArtifact(BaseModel):
    """In-memory artifact payload returned by a harness before durable persistence."""

    model_config = {"populate_by_name": True}

    filename: str
    content_type: str = Field(alias="contentType")
    text: str | None = None
    data: dict[str, Any] | None = None


class HarnessExecution(BaseModel):
    """Normalized harness execution output, ready for durable persistence by the service."""

    model_config = {"populate_by_name": True}

    result: CodingExecResult
    command: list[str]
    artifact_payloads: dict[str, HarnessArtifact] = Field(
        default_factory=dict,
        alias="artifactPayloads",
    )


class NormalizedProviderPayload(BaseModel):
    """Structured provider payload required for successful normalization."""

    model_config = {"populate_by_name": True}

    summary: str
    response_text: str = Field(alias="responseText")
    next_suggestion: str = Field(default="", alias="nextSuggestion")
    signals: dict[str, bool] = Field(default_factory=dict)


class CodingHarness(Protocol):
    """Provider-agnostic harness interface."""

    provider: CodingProvider

    def exec(
        self,
        job_id: str,
        request: CodingExecRequest,
        effective_cwd: str,
        startup_policy: ResolvedStartupPolicy,
    ) -> HarnessExecution:
        ...


class BaseCliHarness(ABC):
    """Shared subprocess logic for provider CLI harnesses."""

    provider: CodingProvider
    binary_name: str

    def exec(
        self,
        job_id: str,
        request: CodingExecRequest,
        effective_cwd: str,
        startup_policy: ResolvedStartupPolicy,
    ) -> HarnessExecution:
        command = self.build_command(request, startup_policy)
        artifact_refs = {
            "stdoutLog": "stdout.log",
            "stderrLog": "stderr.log",
            "invocation": "invocation.json",
        }
        invocation_data = {
            "provider": self.provider.value,
            "command": command,
            "effectiveCwd": effective_cwd,
            "timeoutSec": request.timeout_sec,
            "jobId": job_id,
        }

        if shutil.which(self.binary_name) is None:
            result = CodingExecResult(
                jobId=job_id,
                provider=self.provider,
                effectiveCwd=effective_cwd,
                status=CodingJobState.failed,
                summary=f"{self.provider.value} CLI is unavailable.",
                error=f"Provider executable '{self.binary_name}' not found in PATH.",
                artifacts=artifact_refs,
                metrics={"failureKind": "startup"},
            )
            return HarnessExecution(
                result=result,
                command=command,
                artifactPayloads={
                    "stdoutLog": HarnessArtifact(
                        filename="stdout.log",
                        contentType="text/plain",
                        text="",
                    ),
                    "stderrLog": HarnessArtifact(
                        filename="stderr.log",
                        contentType="text/plain",
                        text=result.error,
                    ),
                    "invocation": HarnessArtifact(
                        filename="invocation.json",
                        contentType="application/json",
                        data=invocation_data,
                    ),
                },
            )

        env = os.environ.copy()
        env["CLAWTEAM_CODING_JOB_ID"] = job_id
        env["CLAWTEAM_CODING_PROVIDER"] = self.provider.value
        env["CLAWTEAM_WORKSPACE_DIR"] = effective_cwd

        started_at = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=effective_cwd,
                timeout=request.timeout_sec,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = self._coerce_text(exc.stdout)
            stderr = self._coerce_text(exc.stderr)
            duration = time.monotonic() - started_at
            result = CodingExecResult(
                jobId=job_id,
                provider=self.provider,
                effectiveCwd=effective_cwd,
                status=CodingJobState.timeout,
                exitCode=None,
                summary=f"{self.provider.value} timed out after {request.timeout_sec} seconds.",
                responseText="",
                artifacts=artifact_refs,
                metrics={"durationSec": round(duration, 3), "failureKind": "timeout"},
                error=stderr or f"{self.provider.value} execution timed out.",
            )
            return HarnessExecution(
                result=result,
                command=command,
                artifactPayloads=self._artifact_payloads(stdout, stderr, invocation_data),
            )
        except OSError as exc:
            duration = time.monotonic() - started_at
            error_text = str(exc)
            result = CodingExecResult(
                jobId=job_id,
                provider=self.provider,
                effectiveCwd=effective_cwd,
                status=CodingJobState.failed,
                summary=f"{self.provider.value} failed to start.",
                responseText="",
                artifacts=artifact_refs,
                metrics={"durationSec": round(duration, 3), "failureKind": "startup"},
                error=error_text,
            )
            return HarnessExecution(
                result=result,
                command=command,
                artifactPayloads=self._artifact_payloads("", error_text, invocation_data),
            )

        duration = time.monotonic() - started_at
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""

        if completed.returncode != 0:
            error_text = stderr.strip() or f"{self.provider.value} exited with code {completed.returncode}."
            result = CodingExecResult(
                jobId=job_id,
                provider=self.provider,
                effectiveCwd=effective_cwd,
                status=CodingJobState.failed,
                exitCode=completed.returncode,
                summary=f"{self.provider.value} exited with code {completed.returncode}.",
                responseText="",
                artifacts=artifact_refs,
                metrics={"durationSec": round(duration, 3), "failureKind": "provider_exit"},
                error=error_text,
            )
            return HarnessExecution(
                result=result,
                command=command,
                artifactPayloads=self._artifact_payloads(stdout, stderr, invocation_data),
            )

        normalized_payload, normalization_error = self._parse_normalized_payload(stdout)
        if normalized_payload is None:
            result = CodingExecResult(
                jobId=job_id,
                provider=self.provider,
                effectiveCwd=effective_cwd,
                status=CodingJobState.failed,
                exitCode=completed.returncode,
                summary=f"{self.provider.value} output could not be normalized.",
                responseText="",
                artifacts=artifact_refs,
                metrics={"durationSec": round(duration, 3), "failureKind": "normalization"},
                error=normalization_error,
            )
            return HarnessExecution(
                result=result,
                command=command,
                artifactPayloads=self._artifact_payloads(stdout, stderr, invocation_data),
            )

        result = CodingExecResult(
            jobId=job_id,
            provider=self.provider,
            effectiveCwd=effective_cwd,
            status=CodingJobState.completed,
            exitCode=completed.returncode,
            summary=normalized_payload.summary,
            responseText=normalized_payload.response_text,
            nextSuggestion=normalized_payload.next_suggestion,
            signals=normalized_payload.signals,
            artifacts=artifact_refs,
            metrics={"durationSec": round(duration, 3)},
        )
        return HarnessExecution(
            result=result,
            command=command,
            artifactPayloads=self._artifact_payloads(stdout, stderr, invocation_data),
        )

    def build_command(
        self,
        request: CodingExecRequest,
        startup_policy: ResolvedStartupPolicy,
    ) -> list[str]:
        command = [self.binary_name]
        command.extend(startup_policy.applied_flags)
        command.extend(startup_policy.extra_args)
        return self.append_prompt(command, self._build_normalized_prompt(request.prompt))

    @abstractmethod
    def append_prompt(self, command: list[str], prompt: str) -> list[str]:
        """Append provider-specific prompt arguments to the command."""

    def _artifact_payloads(
        self,
        stdout: str,
        stderr: str,
        invocation_data: dict[str, Any],
    ) -> dict[str, HarnessArtifact]:
        return {
            "stdoutLog": HarnessArtifact(
                filename="stdout.log",
                contentType="text/plain",
                text=stdout,
            ),
            "stderrLog": HarnessArtifact(
                filename="stderr.log",
                contentType="text/plain",
                text=stderr,
            ),
            "invocation": HarnessArtifact(
                filename="invocation.json",
                contentType="application/json",
                data=invocation_data,
            ),
        }

    def _coerce_text(self, value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def _build_normalized_prompt(self, prompt: str) -> str:
        return (
            f"{prompt}\n\n"
            "Return your final result as structured JSON between these exact markers:\n"
            "CLAWTEAM_RESULT_JSON_START\n"
            '{"summary":"<short summary>","responseText":"<compact worker-usable result>",'
            '"nextSuggestion":"<next suggested step>","signals":{"needsReview":false,'
            '"needsDecision":false,"blocked":false}}\n'
            "CLAWTEAM_RESULT_JSON_END\n"
            "Do not omit the markers. Do not rely on prose-only final output."
        )

    def _parse_normalized_payload(
        self,
        stdout: str,
    ) -> tuple[NormalizedProviderPayload | None, str | None]:
        start_marker = "CLAWTEAM_RESULT_JSON_START"
        end_marker = "CLAWTEAM_RESULT_JSON_END"
        start_index = stdout.find(start_marker)
        end_index = stdout.find(end_marker)
        if start_index == -1 or end_index == -1 or end_index <= start_index:
            return None, "normalization failed: missing structured result markers"
        payload_text = stdout[start_index + len(start_marker):end_index].strip()
        if not payload_text:
            return None, "normalization failed: structured result payload was empty"
        try:
            payload_data = json.loads(payload_text)
            payload = NormalizedProviderPayload.model_validate(payload_data)
        except Exception as exc:
            return None, f"normalization failed: invalid structured result payload ({exc})"
        return payload, None
