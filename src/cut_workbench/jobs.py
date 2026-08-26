from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
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
        if not self.jobs_dir.exists():
            return []
        jobs = [json.loads(path.read_text(encoding="utf-8")) for path in self.jobs_dir.glob("*.json")]
        return sorted((job for job in jobs if job["status"] == "pending_agent"), key=lambda item: item["created_at"])

    def _write(self, job: dict[str, Any]) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        path = self.jobs_dir / f"{job['job_id']}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
