from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from .capabilities import CapabilityRequest, CapabilityResult
from .errors import ValidationError


class JsonCommandProvider:
    """Adapter for Whisper/scene/beat tools that speak one JSON object over stdio."""

    def __init__(
        self, *, provider_id: str, capabilities: Iterable[str], command: Sequence[str], timeout: float = 3600
    ) -> None:
        self.provider_id = provider_id
        self.capabilities = frozenset(capabilities)
        self.command = list(command)
        self.timeout = timeout
        if not self.command:
            raise ValidationError("provider command must not be empty")

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def execute(self, request: CapabilityRequest) -> CapabilityResult:
        completed = subprocess.run(
            self.command,
            input=json.dumps(asdict(request), ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip()[-2000:]
            raise ValidationError(f"provider {self.provider_id} failed ({completed.returncode}): {detail}")
        try:
            output: dict[str, Any] = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ValidationError(f"provider {self.provider_id} returned invalid JSON") from error
        payload = output.get("payload")
        evidence = output.get("evidence", [])
        if not isinstance(payload, dict) or not isinstance(evidence, list):
            raise ValidationError("provider output requires object payload and list evidence")
        return CapabilityResult(request.capability, self.provider_id, payload, evidence)


class FfprobeProvider:
    provider_id = "local:ffprobe"

    def __init__(self, executable: str = "ffprobe") -> None:
        self.executable = executable

    def supports(self, capability: str) -> bool:
        return capability == "media.probe"

    def execute(self, request: CapabilityRequest) -> CapabilityResult:
        media_path = request.inputs.get("media_path")
        if not isinstance(media_path, str):
            raise ValidationError("media.probe requires inputs.media_path")
        path = Path(media_path).resolve()
        completed = subprocess.run(
            [self.executable, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            text=True, capture_output=True, check=False, shell=False,
        )
        if completed.returncode != 0:
            raise ValidationError(f"ffprobe failed: {completed.stderr.strip()[-2000:]}")
        return CapabilityResult("media.probe", self.provider_id, json.loads(completed.stdout), [str(path)])
