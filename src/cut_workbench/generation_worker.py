from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from .errors import ValidationError
from .jobs import CapabilityJobStore
from .tapnow import GenerativeOrchestrator


@dataclass(frozen=True)
class AgentExecutionResult:
    payload: Mapping[str, Any]
    evidence: list[str]


class GenerationExecutor(Protocol):
    def execute(self, envelope: Mapping[str, Any]) -> AgentExecutionResult: ...


class JsonCommandGenerationExecutor:
    """Invoke any local Agent framework through one JSON stdin/stdout operation."""

    def __init__(self, command: Sequence[str], *, timeout: float = 3600) -> None:
        self.command = list(command)
        self.timeout = timeout
        if not self.command:
            raise ValidationError("generation Agent command must not be empty")

    def execute(self, envelope: Mapping[str, Any]) -> AgentExecutionResult:
        completed = subprocess.run(
            self.command,
            input=json.dumps(envelope, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            raise ValidationError(
                f"generation Agent command failed ({completed.returncode}): "
                f"{completed.stderr.strip()[-2000:]}"
            )
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ValidationError("generation Agent command returned invalid JSON") from error
        payload = value.get("payload") if isinstance(value, Mapping) else None
        evidence = value.get("evidence") if isinstance(value, Mapping) else None
        if not isinstance(payload, Mapping) or not isinstance(evidence, list):
            raise ValidationError("generation Agent output requires object payload and list evidence")
        return AgentExecutionResult(payload=dict(payload), evidence=list(evidence))


class GenerationWorker:
    """Claim and execute one durable generation packet through a local Agent command."""

    def __init__(
        self,
        *,
        orchestrator: GenerativeOrchestrator,
        jobs: CapabilityJobStore,
        executor: GenerationExecutor,
        executor_id: str,
        lease_seconds: float = 7200,
    ) -> None:
        if not executor_id:
            raise ValidationError("executor_id is required")
        self.orchestrator = orchestrator
        self.jobs = jobs
        self.executor = executor
        self.executor_id = executor_id
        self.lease_seconds = lease_seconds

    def run_once(self) -> dict[str, Any]:
        pending = self.orchestrator.pending()
        if not pending:
            return {"status": "idle", "executor_id": self.executor_id}
        job = pending[0]
        self.orchestrator.claim(
            job_id=job["job_id"], executor_id=self.executor_id,
            lease_seconds=self.lease_seconds,
        )
        try:
            operation = job["request"]["operation"]
            if operation["execution"]["boundary"] == "generate":
                preflight_result = self.executor.execute({"phase": "preflight", "operation": operation})
                authorized_job = self.orchestrator.authorize(
                    job_id=job["job_id"], executor_id=self.executor_id,
                    preflight=preflight_result.payload, evidence=preflight_result.evidence,
                )
                result = self.executor.execute({
                    "phase": "execute", "operation": operation,
                    "authorization": authorized_job["authorization"],
                })
            else:
                result = self.executor.execute({"phase": "prepare", "operation": operation})
            return self.orchestrator.submit(
                job_id=job["job_id"], executor_id=self.executor_id,
                payload=result.payload, evidence=result.evidence,
            )
        except Exception as error:
            current = self.jobs.read(job["job_id"])
            if current.get("authorization") is not None:
                self.jobs.require_provider_reconciliation(
                    job_id=job["job_id"], provider_id=job["provider_id"],
                    executor_id=self.executor_id,
                    reason=f"executor failed after generation authorization: {error}",
                )
            else:
                self.jobs.fail(
                    job_id=job["job_id"], provider_id=job["provider_id"], message=str(error)
                )
            raise
