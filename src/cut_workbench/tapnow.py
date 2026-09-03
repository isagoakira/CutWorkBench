from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Mapping, Protocol

from .errors import ValidationError
from .jobs import CapabilityJobStore


CAPABILITIES = {
    "image.generate": "generate-image",
    "image.edit": "edit-image",
    "video.generate": "generate-video",
    "video.edit": "edit-video",
    "video.extend": "extend-video",
    "video.retake": "retake-video",
    "video.inpaint": "inpaint-video",
}
EDIT_CAPABILITIES = {"image.edit", "video.edit", "video.extend", "video.retake", "video.inpaint"}
REFERENCE_KINDS = {"canvas-node", "local-file", "remote-url", "workflow-artifact"}
EXECUTION_BOUNDARIES = {"plan", "preview", "generate"}


class GenerativeAdapter(Protocol):
    provider_id: str

    def contract(self) -> dict[str, Any]: ...

    def compile(self, request: Mapping[str, Any]) -> dict[str, Any]: ...

    def validate_result(
        self, *, operation: Mapping[str, Any], payload: Mapping[str, Any],
        executor_id: str, evidence: list[str],
    ) -> dict[str, Any]: ...

    def validate_preflight(
        self, *, operation: Mapping[str, Any], preflight: Mapping[str, Any]
    ) -> dict[str, Any]: ...


def generation_contract() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider_id": TapNowAgenticAdapter.provider_id,
        "capabilities": [
            {"capability": capability, "action": action}
            for capability, action in CAPABILITIES.items()
        ],
        "execution_boundaries": sorted(EXECUTION_BOUNDARIES),
        "rules": {
            "generate_requires_spend_approval": True,
            "local_file_requires_external_upload_approval": True,
            "edits_require_single_change_scope_and_preserve_list": True,
            "results_require_canvas_and_file_evidence": True,
        },
    }


class TapNowAgenticAdapter:
    """Compile stable generation requests into TapNow Agent/Canvas operation packets."""

    provider_id = "agentic:tapnow"

    def __init__(self, artifact_root: Path | None = None) -> None:
        self.artifact_root = Path(artifact_root or Path.cwd()).resolve()

    def contract(self) -> dict[str, Any]:
        return generation_contract()

    def validate_preflight(
        self, *, operation: Mapping[str, Any], preflight: Mapping[str, Any]
    ) -> dict[str, Any]:
        if operation["execution"]["boundary"] != "generate":
            raise ValidationError("only generate operations require preflight authorization")
        return _validate_preflight(preflight, operation["execution"]["spend_approval"])

    def compile(self, request: Mapping[str, Any]) -> dict[str, Any]:
        capability = _required_text(request, "capability")
        if capability not in CAPABILITIES:
            raise ValidationError(f"TapNow does not support capability: {capability}")
        prompt = _required_text(request, "prompt")
        references = _references(request.get("references", []))
        output = _output(request.get("output", {}))
        constraints = _constraints(request.get("constraints", {}), capability, references, output)
        targets = _artifact_targets(request.get("artifact_targets", []), output["count"])
        operation_id = uuid.uuid4().hex
        boundary = constraints["execution_boundary"]
        operation = {
            "schema_version": 1,
            "operation_id": operation_id,
            "provider_id": self.provider_id,
            "capability": capability,
            "action": CAPABILITIES[capability],
            "instruction": {
                "prompt": prompt,
                "references": references,
                "output": output,
                "model": constraints.get("model", "auto"),
                "change_scope": constraints.get("change_scope"),
                "preserve": constraints["preserve"],
                "avoid": constraints["avoid"],
            },
            "execution": {
                "mode": "ask",
                "boundary": boundary,
                "stop_before_spend": boundary != "generate",
                "spend_approval": constraints.get("spend_approval"),
                "external_upload_approval": constraints.get("external_upload_approval"),
            },
            "lineage": {
                "reference_ids": [item["reference_id"] for item in references],
                "artifact_targets": targets,
            },
            "acceptance_criteria": _string_list(
                request.get("acceptance_criteria", []), "acceptance_criteria"
            ),
            "agent_steps": [
                "Open the intended TapNow canvas and use Ask mode.",
                "Attach only the declared references and preserve their assigned roles.",
                "Apply the requested model and output limits, then stop at the declared execution boundary.",
                "Do not spend Tapies or start generation unless stop_before_spend is false.",
                "Immediately before generation, compare the live estimate with the stored approval and abort if it exceeds either cap.",
                "Return canvas URL, node IDs, downloaded canonical files, SHA-256 hashes, and evidence.",
            ],
        }
        operation["request_fingerprint"] = _generation_fingerprint(operation)
        return operation

    def validate_result(
        self,
        *,
        operation: Mapping[str, Any],
        payload: Mapping[str, Any],
        executor_id: str,
        evidence: list[str],
    ) -> dict[str, Any]:
        if payload.get("operation_id") != operation["operation_id"]:
            raise ValidationError("TapNow result operation_id does not match the dispatched operation")
        canvas_url = _required_text(payload, "canvas_url")
        if not executor_id:
            raise ValidationError("executor_id is required")
        if not evidence or not all(isinstance(item, str) and item for item in evidence):
            raise ValidationError("TapNow result requires evidence")
        boundary = operation["execution"]["boundary"]
        result_status = payload.get("status")
        if boundary != "generate":
            if result_status != "prepared":
                raise ValidationError("plan/preview results must stop with status prepared")
            outputs = payload.get("outputs", [])
            if outputs:
                raise ValidationError("plan/preview results must not claim generated outputs")
            usage = payload.get("usage")
            if not isinstance(usage, Mapping):
                raise ValidationError("plan/preview results require zero-usage evidence")
            if usage.get("candidates_generated") != 0 or usage.get("tapies_charged") != 0:
                raise ValidationError("plan/preview result crossed the no-spend execution boundary")
            estimate = payload.get("estimate", {})
            if boundary == "preview":
                estimate = _validate_prepared_estimate(estimate, operation["instruction"]["output"])
            elif not isinstance(estimate, Mapping):
                raise ValidationError("TapNow prepared estimate must be an object")
            return {
                "operation_id": operation["operation_id"], "status": "prepared",
                "canvas_url": canvas_url, "outputs": [], "artifact_operations": [],
                "executor_id": executor_id, "estimate": dict(estimate), "usage": dict(usage),
            }
        if result_status != "completed":
            raise ValidationError("generate results must use status completed")
        preflight = _validate_preflight(
            payload.get("preflight"), operation["execution"]["spend_approval"]
        )
        usage = _validate_usage(payload.get("usage"), operation["execution"]["spend_approval"])
        if preflight["candidate_count"] != usage["candidates_generated"]:
            raise ValidationError("TapNow preflight candidate count differs from actual usage")
        outputs = payload.get("outputs")
        if not isinstance(outputs, list) or not outputs:
            raise ValidationError("TapNow generate result requires outputs")
        if not all(isinstance(item, Mapping) for item in outputs):
            raise ValidationError("TapNow outputs must be objects")
        expected_targets = {
            item["target_id"]: item for item in operation["lineage"]["artifact_targets"]
        }
        output_target_ids = [item.get("target_id") for item in outputs]
        if expected_targets and (
            len(output_target_ids) != len(set(output_target_ids))
            or set(output_target_ids) != set(expected_targets)
        ):
            raise ValidationError("TapNow result must contain every declared artifact target exactly once")
        if len(outputs) > operation["instruction"]["output"]["count"]:
            raise ValidationError("TapNow returned more outputs than authorized")
        if usage["candidates_generated"] != len(outputs):
            raise ValidationError("TapNow candidate usage does not match returned outputs")

        normalized_outputs = []
        artifact_operations = []
        for item in outputs:
            content_profile = item.get("content_profile", {})
            if not isinstance(content_profile, Mapping):
                raise ValidationError("TapNow output content_profile must be an object")
            normalized = {
                "target_id": item.get("target_id"),
                "node_id": _required_text(item, "node_id"),
                "locator": _required_text(item, "locator"),
                "media_type": _required_text(item, "media_type"),
                "model": _required_text(item, "model"),
                "sha256": _sha256(item.get("sha256")),
                "hash_verified": False,
            }
            expected_media_type = "image" if operation["capability"].startswith("image.") else "video"
            if normalized["media_type"] != expected_media_type:
                raise ValidationError(
                    f"TapNow output media_type must be {expected_media_type} for {operation['capability']}"
                )
            normalized_outputs.append(normalized)
            target = expected_targets.get(normalized["target_id"])
            if target:
                if normalized["locator"] != target["locator"]:
                    raise ValidationError(f"TapNow output locator does not match target {target['target_id']}")
                normalized["sha256"] = self._verify_local_artifact(
                    target["locator"], normalized["sha256"]
                )
                normalized["hash_verified"] = True
                artifact_operations.append({
                    "op": "register_workflow_artifact",
                    "artifact_id": target["artifact_id"],
                    "stage_id": target["stage_id"],
                    "kind": target["kind"],
                    "format": target["format"],
                    "version": target["version"],
                    "locator": target["locator"],
                    "sha256": normalized["sha256"],
                    "derived_from": list(target["derived_from"]),
                    "metadata": {
                        "generated_by": self.provider_id,
                        "tapnow_operation_id": operation["operation_id"],
                        "tapnow_canvas_url": canvas_url,
                        "tapnow_node_id": normalized["node_id"],
                        "model": normalized["model"],
                    },
                    "verification": {
                        "verifier": f"{self.provider_id}/{executor_id}",
                        "readable": True,
                        "hash_matched": True,
                        "evidence": list(evidence),
                        "content_profile": dict(content_profile),
                    },
                })
        acceptance = _validate_acceptance(payload.get("acceptance", []), operation["acceptance_criteria"])
        return {
            "operation_id": operation["operation_id"],
            "canvas_url": canvas_url,
            "outputs": normalized_outputs,
            "artifact_operations": artifact_operations,
            "executor_id": executor_id,
            "usage": usage,
            "preflight": preflight,
            "acceptance": acceptance,
        }

    def _verify_local_artifact(self, locator: str, claimed_sha256: str) -> str:
        path = Path(locator)
        if not path.is_absolute():
            path = self.artifact_root / path
        path = path.resolve()
        try:
            path.relative_to(self.artifact_root)
        except ValueError as error:
            raise ValidationError(
                f"TapNow artifact must remain inside the Workbench root: {locator}"
            ) from error
        if not path.is_file():
            raise ValidationError(f"TapNow artifact is not a readable local file: {locator}")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != claimed_sha256:
            raise ValidationError(f"TapNow artifact SHA-256 mismatch: {locator}")
        return actual


class GenerativeOrchestrator:
    """Durable agentic dispatch around one replaceable generative adapter."""

    def __init__(self, *, jobs: CapabilityJobStore, adapter: GenerativeAdapter) -> None:
        self.jobs = jobs
        self.adapter = adapter

    def request(self, request: Mapping[str, Any]) -> dict[str, Any]:
        request_data = copy.deepcopy(dict(request))
        constraints = request_data.get("constraints", {})
        if not isinstance(constraints, dict):
            raise ValidationError("constraints must be an object")
        if constraints.get("execution_boundary", "preview") == "generate":
            prepared_job_id = constraints.get("prepared_job_id")
            if not isinstance(prepared_job_id, str) or not prepared_job_id:
                raise ValidationError("generate requires constraints.prepared_job_id")
            prepared = self.jobs.read(prepared_job_id)
            if (
                prepared["status"] != "completed"
                or prepared["provider_id"] != self.adapter.provider_id
                or prepared.get("result", {}).get("payload", {}).get("status") != "prepared"
                or not isinstance(prepared.get("approval"), dict)
            ):
                raise ValidationError("generate requires an approved prepared job")
            constraints["spend_approval"] = copy.deepcopy(prepared["approval"])
            request_data["constraints"] = constraints
            operation = self.adapter.compile(request_data)
            prepared_operation = prepared["request"]["operation"]
            if operation["request_fingerprint"] != prepared_operation["request_fingerprint"]:
                raise ValidationError("generate request differs from the approved prepared operation")
            operation["lineage"]["prepared_job_id"] = prepared_job_id
            operation["lineage"]["prepared_operation_id"] = prepared_operation["operation_id"]
            self.jobs.consume_provider_approval(
                job_id=prepared_job_id, provider_id=self.adapter.provider_id,
                operation_id=operation["operation_id"],
            )
        else:
            operation = self.adapter.compile(request_data)
        return self.jobs.create(
            request={"generation_request": request_data, "operation": operation},
            provider_id=self.adapter.provider_id,
            status="pending_provider",
        )

    def contract(self) -> dict[str, Any]:
        return self.adapter.contract()

    def pending(self) -> list[dict[str, Any]]:
        self.jobs.recover_expired_provider(self.adapter.provider_id)
        return self.jobs.pending_provider(self.adapter.provider_id)

    def reconciliation(self) -> list[dict[str, Any]]:
        self.jobs.recover_expired_provider(self.adapter.provider_id)
        return self.jobs.reconciliation_required(self.adapter.provider_id)

    def claim(
        self, *, job_id: str, executor_id: str, lease_seconds: float = 3600
    ) -> dict[str, Any]:
        return self.jobs.claim_provider(
            job_id=job_id, provider_id=self.adapter.provider_id, executor_id=executor_id,
            lease_seconds=lease_seconds,
        )

    def heartbeat(
        self, *, job_id: str, executor_id: str, lease_seconds: float = 3600
    ) -> dict[str, Any]:
        return self.jobs.heartbeat_provider(
            job_id=job_id, provider_id=self.adapter.provider_id,
            executor_id=executor_id, lease_seconds=lease_seconds,
        )

    def approve(
        self,
        *,
        prepared_job_id: str,
        approved_by: str,
        billing_mode: str,
        max_candidates: int,
        evidence: list[str],
        max_tapies: float | None = None,
    ) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "approved_by": approved_by, "billing_mode": billing_mode,
            "max_candidates": max_candidates, "evidence": evidence,
        }
        if max_tapies is not None:
            raw["max_tapies"] = max_tapies
        approval = _approval(raw, "spend_approval", require_budget=True)
        prepared = self.jobs.read(prepared_job_id)
        estimate = prepared.get("result", {}).get("payload", {}).get("estimate", {})
        if not isinstance(estimate, Mapping) or approval["billing_mode"] != estimate.get("billing_mode"):
            raise ValidationError("approval billing mode differs from the prepared live estimate")
        if approval["max_candidates"] < estimate.get("estimated_candidates", 0):
            raise ValidationError("approval candidate cap is below the prepared live estimate")
        if approval["billing_mode"] == "tapies" and estimate["estimated_tapies"] > approval["max_tapies"]:
            raise ValidationError("approval Tapies cap is below the prepared live estimate")
        approval.update(
            approval_id=uuid.uuid4().hex,
            prepared_job_id=prepared_job_id,
            prepared_operation_id=prepared.get("request", {}).get("operation", {}).get("operation_id"),
        )
        return self.jobs.approve_provider_job(
            job_id=prepared_job_id, provider_id=self.adapter.provider_id, approval=approval
        )

    def authorize(
        self,
        *,
        job_id: str,
        executor_id: str,
        preflight: Mapping[str, Any],
        evidence: list[str],
    ) -> dict[str, Any]:
        job = self.jobs.read(job_id)
        if (
            job["status"] != "running_provider"
            or job["provider_id"] != self.adapter.provider_id
            or job.get("claimed_by") != executor_id
        ):
            raise ValidationError(f"job is not claimed by this TapNow executor: {job_id}")
        combined = dict(preflight)
        combined["evidence"] = _evidence(evidence, "TapNow preflight")
        authorization = self.adapter.validate_preflight(
            operation=job["request"]["operation"], preflight=combined
        )
        authorization["executor_id"] = executor_id
        authorization["operation_id"] = job["request"]["operation"]["operation_id"]
        return self.jobs.authorize_provider_execution(
            job_id=job_id, provider_id=self.adapter.provider_id,
            executor_id=executor_id, authorization=authorization,
        )

    def submit(
        self,
        *,
        job_id: str,
        executor_id: str,
        payload: Mapping[str, Any],
        evidence: list[str],
    ) -> dict[str, Any]:
        job = self.jobs.read(job_id)
        if (
            job["status"] != "running_provider"
            or job["provider_id"] != self.adapter.provider_id
            or job.get("claimed_by") != executor_id
        ):
            raise ValidationError(f"job is not claimed by this TapNow executor: {job_id}")
        payload_data = dict(payload)
        if job["request"]["operation"]["execution"]["boundary"] == "generate":
            authorization = job.get("authorization")
            if not isinstance(authorization, Mapping):
                raise ValidationError("generate job requires Workbench preflight authorization")
            payload_data["preflight"] = dict(authorization)
        result = self.adapter.validate_result(
            operation=job["request"]["operation"], payload=payload_data,
            executor_id=executor_id, evidence=evidence,
        )
        return self.jobs.complete(
            job_id=job_id, provider_id=self.adapter.provider_id,
            payload=result, evidence=list(evidence),
        )


def _references(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValidationError("references must be a list")
    references = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ValidationError("references must contain objects")
        reference_id = _required_text(item, "reference_id")
        if reference_id in seen:
            raise ValidationError(f"duplicate reference_id: {reference_id}")
        seen.add(reference_id)
        kind = _required_text(item, "kind")
        if kind not in REFERENCE_KINDS:
            raise ValidationError(f"unsupported reference kind: {kind}")
        references.append({
            "reference_id": reference_id,
            "kind": kind,
            "locator": _required_text(item, "locator"),
            "role": _required_text(item, "role"),
        })
    return references


def _output(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError("output must be an object")
    count = value.get("count", 1)
    if not isinstance(count, int) or isinstance(count, bool) or count < 1 or count > 4:
        raise ValidationError("output.count must be an integer from 1 to 4")
    output = {"count": count}
    for key in ("aspect_ratio", "resolution", "format"):
        if key in value:
            output[key] = _required_text(value, key)
    if "duration_seconds" in value:
        duration = value["duration_seconds"]
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise ValidationError("output.duration_seconds must be positive")
        output["duration_seconds"] = float(duration)
    return output


def _constraints(
    value: Any,
    capability: str,
    references: list[dict[str, str]],
    output: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError("constraints must be an object")
    boundary = value.get("execution_boundary", "preview")
    if boundary not in EXECUTION_BOUNDARIES:
        raise ValidationError(f"unsupported execution_boundary: {boundary}")
    constraints: dict[str, Any] = {
        "execution_boundary": boundary,
        "preserve": _string_list(value.get("preserve", []), "preserve"),
        "avoid": _string_list(value.get("avoid", []), "avoid"),
    }
    if "model" in value:
        constraints["model"] = _required_text(value, "model")
    if capability in EDIT_CAPABILITIES:
        if not references:
            raise ValidationError(f"{capability} requires at least one reference")
        constraints["change_scope"] = _required_text(value, "change_scope")
        if not constraints["preserve"]:
            raise ValidationError(f"{capability} requires preserve constraints")
    if any(item["kind"] in {"local-file", "workflow-artifact"} for item in references):
        constraints["external_upload_approval"] = _approval(
            value.get("external_upload_approval"), "external_upload_approval", require_budget=False
        )
    if boundary == "generate":
        constraints["spend_approval"] = _approval(
            value.get("spend_approval"), "spend_approval", require_budget=True
        )
        max_candidates = constraints["spend_approval"].get("max_candidates", output["count"])
        if output["count"] > max_candidates:
            raise ValidationError("output.count exceeds spend_approval.max_candidates")
    return constraints


def _approval(value: Any, name: str, *, require_budget: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{name} is required")
    approval = {
        "approved_by": _required_text(value, "approved_by"),
        "evidence": _evidence(value.get("evidence"), name),
    }
    if require_budget:
        billing_mode = value.get("billing_mode")
        if billing_mode not in {"tapies", "unlimited"}:
            raise ValidationError("spend_approval.billing_mode must be tapies or unlimited")
        approval["billing_mode"] = billing_mode
        if billing_mode == "tapies":
            max_tapies = value.get("max_tapies")
            if not isinstance(max_tapies, (int, float)) or isinstance(max_tapies, bool) or max_tapies < 0:
                raise ValidationError("spend_approval.max_tapies must be non-negative")
            approval["max_tapies"] = float(max_tapies)
        max_candidates = value.get("max_candidates", 1)
        if not isinstance(max_candidates, int) or isinstance(max_candidates, bool) or max_candidates < 1:
            raise ValidationError("spend_approval.max_candidates must be positive")
        approval["max_candidates"] = max_candidates
    return approval


def _artifact_targets(value: Any, output_count: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValidationError("artifact_targets must be a list")
    if len(value) > output_count:
        raise ValidationError("artifact_targets cannot exceed output.count")
    targets = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ValidationError("artifact_targets must contain objects")
        target_id = _required_text(item, "target_id")
        if target_id in seen:
            raise ValidationError(f"duplicate artifact target: {target_id}")
        seen.add(target_id)
        derived_from = item.get("derived_from", [])
        if not isinstance(derived_from, list) or not all(isinstance(entry, str) and entry for entry in derived_from):
            raise ValidationError("artifact target derived_from must be a list of stable IDs")
        targets.append({
            "target_id": target_id,
            "artifact_id": _required_text(item, "artifact_id"),
            "stage_id": _required_text(item, "stage_id"),
            "kind": _required_text(item, "kind"),
            "format": _required_text(item, "format"),
            "version": _required_text(item, "version"),
            "locator": _required_text(item, "locator"),
            "derived_from": list(derived_from),
        })
    return targets


def _required_text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValidationError(f"{key} is required")
    return item.strip()


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValidationError(f"{name} must be a list of non-empty strings")
    return list(value)


def _evidence(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValidationError(f"{name}.evidence must be a non-empty list")
    return list(value)


def _sha256(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValidationError("TapNow output requires a SHA-256 hash")
    return value.lower()


def _validate_usage(value: Any, approval: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError("TapNow generate result requires usage")
    billing_mode = value.get("billing_mode")
    if billing_mode != approval["billing_mode"]:
        raise ValidationError("TapNow usage billing_mode differs from approval")
    candidates = value.get("candidates_generated")
    if not isinstance(candidates, int) or isinstance(candidates, bool) or candidates < 1:
        raise ValidationError("TapNow usage candidates_generated must be positive")
    if candidates > approval["max_candidates"]:
        raise ValidationError("TapNow generated more candidates than approved")
    usage: dict[str, Any] = {"billing_mode": billing_mode, "candidates_generated": candidates}
    if billing_mode == "tapies":
        charged = value.get("tapies_charged")
        if not isinstance(charged, (int, float)) or isinstance(charged, bool) or charged < 0:
            raise ValidationError("TapNow usage tapies_charged must be non-negative")
        if charged > approval["max_tapies"]:
            raise ValidationError("TapNow usage exceeds the approved Tapies budget")
        usage["tapies_charged"] = float(charged)
    return usage


def _validate_preflight(value: Any, approval: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("checked_before_generation") is not True:
        raise ValidationError("TapNow generate result requires a preflight check")
    if value.get("billing_mode") != approval["billing_mode"]:
        raise ValidationError("TapNow preflight billing_mode differs from approval")
    candidates = value.get("candidate_count")
    if not isinstance(candidates, int) or isinstance(candidates, bool) or candidates < 1:
        raise ValidationError("TapNow preflight candidate_count must be positive")
    if candidates > approval["max_candidates"]:
        raise ValidationError("TapNow preflight exceeds the approved candidate cap")
    evidence = _evidence(value.get("evidence"), "TapNow preflight")
    preflight: dict[str, Any] = {
        "checked_before_generation": True, "billing_mode": value["billing_mode"],
        "candidate_count": candidates, "evidence": evidence,
    }
    if value["billing_mode"] == "tapies":
        estimate = value.get("estimated_tapies")
        if not isinstance(estimate, (int, float)) or isinstance(estimate, bool) or estimate < 0:
            raise ValidationError("TapNow preflight estimated_tapies must be non-negative")
        if estimate > approval["max_tapies"]:
            raise ValidationError("TapNow live estimate exceeds the approved Tapies budget")
        preflight["estimated_tapies"] = float(estimate)
    return preflight


def _validate_prepared_estimate(value: Any, output: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError("TapNow preview requires a live estimate")
    billing_mode = value.get("billing_mode")
    if billing_mode not in {"tapies", "unlimited"}:
        raise ValidationError("TapNow preview estimate requires a valid billing_mode")
    candidates = value.get("estimated_candidates")
    if not isinstance(candidates, int) or isinstance(candidates, bool) or candidates < 1:
        raise ValidationError("TapNow preview estimate requires estimated_candidates")
    if candidates != output["count"]:
        raise ValidationError("TapNow preview estimate candidate count differs from the request")
    estimate: dict[str, Any] = {"billing_mode": billing_mode, "estimated_candidates": candidates}
    if billing_mode == "tapies":
        tapies = value.get("estimated_tapies")
        if not isinstance(tapies, (int, float)) or isinstance(tapies, bool) or tapies < 0:
            raise ValidationError("TapNow preview estimate requires non-negative estimated_tapies")
        estimate["estimated_tapies"] = float(tapies)
    return estimate


def _generation_fingerprint(operation: Mapping[str, Any]) -> str:
    content = {
        "capability": operation["capability"],
        "instruction": operation["instruction"],
        "artifact_targets": operation["lineage"]["artifact_targets"],
        "external_upload_approval": operation["execution"]["external_upload_approval"],
        "acceptance_criteria": operation["acceptance_criteria"],
    }
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_acceptance(value: Any, criteria: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(criteria):
        raise ValidationError("TapNow result acceptance must cover every declared criterion")
    normalized = []
    for index, criterion in enumerate(criteria):
        item = value[index]
        if not isinstance(item, Mapping) or item.get("criterion") != criterion or item.get("passed") is not True:
            raise ValidationError(f"TapNow acceptance criterion {index + 1} must match and pass")
        evidence = _evidence(item.get("evidence"), f"acceptance criterion {index + 1}")
        normalized.append({"criterion": criterion, "passed": True, "evidence": evidence})
    return normalized
