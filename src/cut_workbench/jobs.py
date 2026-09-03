from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .errors import ProjectNotFound, ValidationError


class CapabilityJobStore:
    """Durable hand-off queue between the workbench and any agent host."""

    def __init__(self, root: Path) -> None:
        self.jobs_dir = Path(root) / "capability-jobs"

    def create(self, *, request: dict[str, Any], provider_id: str, status: str) -> dict[str, Any]:
        job = {
            "job_id": uuid.uuid4().hex,
            "status": status,
            "provider_id": provider_id,
            "request": request,
            "result": None,
            "created_at": _now(),
            "completed_at": None,
        }
        self._write(job)
        return job

    def read(self, job_id: str) -> dict[str, Any]:
        _validate_job_id(job_id)
        path = self.jobs_dir / f"{job_id}.json"
        if not path.exists():
            raise ProjectNotFound(f"capability job not found: {job_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def complete(
        self,
        *,
        job_id: str,
        provider_id: str,
        payload: dict[str, Any],
        evidence: list[str],
    ) -> dict[str, Any]:
        job = self.read(job_id)
        if job["status"] == "completed":
            raise ValidationError(f"capability job already completed: {job_id}")
        job.update(
            status="completed",
            provider_id=provider_id,
            result={"payload": payload, "evidence": evidence},
            completed_at=_now(),
        )
        self._write(job)
        return job

    def pending(self) -> list[dict[str, Any]]:
        return self._by_status("pending_agent")

    def pending_provider(self, provider_id: str | None = None) -> list[dict[str, Any]]:
        jobs = self._by_status("pending_provider")
        if provider_id is None:
            return jobs
        return [job for job in jobs if job["provider_id"] == provider_id]

    def claim_provider(
        self, *, job_id: str, provider_id: str, executor_id: str, lease_seconds: float = 3600
    ) -> dict[str, Any]:
        _validate_job_id(job_id)
        with self._lock(job_id):
            job = self.read(job_id)
            if job["status"] != "pending_provider" or job["provider_id"] != provider_id:
                raise ValidationError(f"provider job is not available to claim: {job_id}")
            if not isinstance(executor_id, str) or not executor_id:
                raise ValidationError("executor_id is required")
            if not isinstance(lease_seconds, (int, float)) or lease_seconds <= 0:
                raise ValidationError("lease_seconds must be positive")
            now = datetime.now(timezone.utc)
            job.update(
                status="running_provider", claimed_by=executor_id, claimed_at=now.isoformat(),
                claim_expires_at=(now + timedelta(seconds=float(lease_seconds))).isoformat(),
            )
            self._write(job)
            return job

    def heartbeat_provider(
        self, *, job_id: str, provider_id: str, executor_id: str, lease_seconds: float = 3600
    ) -> dict[str, Any]:
        with self._lock(job_id):
            job = self.read(job_id)
            if (
                job["status"] != "running_provider"
                or job["provider_id"] != provider_id
                or job.get("claimed_by") != executor_id
            ):
                raise ValidationError(f"provider job is not claimed by this executor: {job_id}")
            if not isinstance(lease_seconds, (int, float)) or lease_seconds <= 0:
                raise ValidationError("lease_seconds must be positive")
            job["claim_expires_at"] = (
                datetime.now(timezone.utc) + timedelta(seconds=float(lease_seconds))
            ).isoformat()
            self._write(job)
            return job

    def recover_expired_provider(self, provider_id: str) -> dict[str, list[str]]:
        recovered: list[str] = []
        reconciliation_required: list[str] = []
        for job in self._by_status("running_provider"):
            if job["provider_id"] != provider_id:
                continue
            expires_at = job.get("claim_expires_at")
            if not isinstance(expires_at, str) or datetime.fromisoformat(expires_at) > datetime.now(timezone.utc):
                continue
            try:
                with self._lock(job["job_id"]):
                    current = self.read(job["job_id"])
                    current_expiry = current.get("claim_expires_at")
                    if (
                        current["status"] != "running_provider"
                        or not isinstance(current_expiry, str)
                        or datetime.fromisoformat(current_expiry) > datetime.now(timezone.utc)
                    ):
                        continue
                    if current.get("authorization") is not None:
                        current.update(
                            status="reconciliation_required",
                            reconciliation_reason=(
                                "executor lease expired after generation was authorized; "
                                "verify provider state before retrying"
                            ),
                        )
                        reconciliation_required.append(current["job_id"])
                    else:
                        current.update(status="pending_provider")
                        recovered.append(current["job_id"])
                    for key in ("claimed_by", "claimed_at", "claim_expires_at"):
                        current.pop(key, None)
                    self._write(current)
            except ValidationError:
                continue
        return {
            "recovered": recovered,
            "reconciliation_required": reconciliation_required,
        }

    def approve_provider_job(
        self, *, job_id: str, provider_id: str, approval: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock(job_id):
            job = self.read(job_id)
            if (
                job["status"] != "completed"
                or job["provider_id"] != provider_id
                or job.get("result", {}).get("payload", {}).get("status") != "prepared"
                or job.get("request", {}).get("operation", {}).get("execution", {}).get("boundary") != "preview"
            ):
                raise ValidationError(f"only a completed preview job can be approved: {job_id}")
            if job.get("approval") is not None:
                raise ValidationError(f"provider job is already approved: {job_id}")
            job["approval"] = approval
            self._write(job)
            return job

    def consume_provider_approval(
        self, *, job_id: str, provider_id: str, operation_id: str
    ) -> dict[str, Any]:
        with self._lock(job_id):
            job = self.read(job_id)
            approval = job.get("approval")
            if job["provider_id"] != provider_id or not isinstance(approval, dict):
                raise ValidationError(f"provider approval is unavailable: {job_id}")
            if approval.get("consumed_by_operation_id") is not None:
                raise ValidationError(f"provider approval is already consumed: {job_id}")
            approval["consumed_by_operation_id"] = operation_id
            job["approval"] = approval
            self._write(job)
            return job

    def authorize_provider_execution(
        self, *, job_id: str, provider_id: str, executor_id: str, authorization: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock(job_id):
            job = self.read(job_id)
            if (
                job["status"] != "running_provider"
                or job["provider_id"] != provider_id
                or job.get("claimed_by") != executor_id
            ):
                raise ValidationError(f"provider job is not claimed by this executor: {job_id}")
            if job.get("authorization") is not None:
                raise ValidationError(f"provider execution is already authorized: {job_id}")
            job["authorization"] = authorization
            self._write(job)
            return job

    def require_provider_reconciliation(
        self, *, job_id: str, provider_id: str, executor_id: str, reason: str
    ) -> dict[str, Any]:
        with self._lock(job_id):
            job = self.read(job_id)
            if (
                job["status"] != "running_provider"
                or job["provider_id"] != provider_id
                or job.get("claimed_by") != executor_id
                or job.get("authorization") is None
            ):
                raise ValidationError(f"authorized provider job cannot be reconciled: {job_id}")
            job.update(
                status="reconciliation_required",
                reconciliation_reason=reason,
                completed_at=_now(),
            )
            for key in ("claimed_by", "claimed_at", "claim_expires_at"):
                job.pop(key, None)
            self._write(job)
            return job

    @contextmanager
    def _lock(self, job_id: str):
        lock_path = self.jobs_dir / f"{job_id}.lock"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise ValidationError(f"job state transition is already in progress: {job_id}") from error
        try:
            yield
        finally:
            os.close(descriptor)
            lock_path.unlink(missing_ok=True)

    def failed(self) -> list[dict[str, Any]]:
        return self._by_status("failed")

    def reconciliation_required(self, provider_id: str | None = None) -> list[dict[str, Any]]:
        jobs = self._by_status("reconciliation_required")
        if provider_id is None:
            return jobs
        return [job for job in jobs if job["provider_id"] == provider_id]

    def _by_status(self, status: str) -> list[dict[str, Any]]:
        if not self.jobs_dir.exists():
            return []
        jobs = [json.loads(path.read_text(encoding="utf-8")) for path in self.jobs_dir.glob("*.json")]
        return sorted((job for job in jobs if job["status"] == status), key=lambda item: item["created_at"])

    def fail(self, *, job_id: str, provider_id: str, message: str) -> dict[str, Any]:
        job = self.read(job_id)
        job.update(
            status="failed", provider_id=provider_id,
            result={"error": message}, completed_at=_now(),
        )
        self._write(job)
        return job

    def _write(self, job: dict[str, Any]) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        path = self.jobs_dir / f"{job['job_id']}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_job_id(job_id: str) -> None:
    if not isinstance(job_id, str) or re.fullmatch(r"[0-9a-f]{32}", job_id) is None:
        raise ValidationError("job_id must be a 32-character hexadecimal identifier")
