from __future__ import annotations

import re
from typing import Any, Mapping

from .project_store import content_fingerprint


def verify_project(project: Mapping[str, Any]) -> dict[str, Any]:
    """Run deterministic Cut Protocol gates; semantic judgment remains a capability job."""
    issues: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    audited_sources = {
        decision.get("source_id")
        for decision in project.get("decisions", {}).values()
        if decision.get("kind") == "source_audit"
        and decision.get("data", {}).get("sample_fps", 0) >= 2
        and decision.get("evidence")
    }
    for source_id in project.get("sources", {}):
        passed = source_id in audited_sources
        checks.append({"check": "source-audit", "target": source_id, "passed": passed})
        if not passed:
            issues.append({
                "code": "source-audit-missing", "target": source_id,
                "message": "Full-source audit evidence at >=2 fps is missing",
            })
        source_hash = project["sources"][source_id].get("sha256")
        if not isinstance(source_hash, str) or re.fullmatch(r"[0-9a-fA-F]{64}", source_hash) is None:
            issues.append({
                "code": "source-hash-missing", "target": source_id,
                "message": "Source provenance requires a SHA-256 content hash before delivery",
            })

    for track_id, track in project.get("tracks", {}).items():
        if track.get("kind") not in {"video", "audio"}:
            continue
        segments = sorted(
            (item for item in project.get("segments", {}).values() if item["track_id"] == track_id),
            key=lambda item: (item["timeline_start"], item["segment_id"]),
        )
        previous_end = 0.0 if track.get("purpose") == "base" else None
        for segment in segments:
            duration = (segment["source_out"] - segment["source_in"]) / segment["speed"]
            start = segment["timeline_start"]
            if previous_end is not None and start < previous_end - 1e-6:
                issues.append({
                    "code": "track-overlap", "target": track_id,
                    "message": f"Segment {segment['segment_id']} overlaps the preceding segment",
                })
            if (
                track.get("purpose") == "base"
                and previous_end is not None
                and start > previous_end + 1e-6
                and not _intentional_gap(project, track_id, previous_end, start)
            ):
                issues.append({
                    "code": "track-gap", "target": track_id,
                    "message": f"Unexplained gap from {previous_end:.3f} to {start:.3f}",
                })
            previous_end = max(previous_end or 0, start + duration)
        checks.append({
            "check": "track-non-overlap", "target": track_id,
            "passed": not any(
                i["code"] in {"track-overlap", "track-gap"} and i["target"] == track_id for i in issues
            ),
        })

    if project.get("status") in {"review", "delivered", "handed_off"}:
        fingerprint = content_fingerprint(project)
        visual_pass = any(
            item.get("kind") == "visual" and item.get("passed") and item.get("evidence")
            and item.get("content_fingerprint") == fingerprint
            for item in project.get("verification", [])
        )
        checks.append({"check": "visual-verification", "target": "project", "passed": visual_pass})
        if not visual_pass:
            issues.append({
                "code": "visual-verification-missing", "target": "project",
                "message": "Review/handoff requires passed visual verification with evidence",
            })

    return {
        "schema_version": 1,
        "project_id": project["project_id"],
        "revision": project["revision"],
        "passed": not issues,
        "checks": checks,
        "issues": issues,
    }


def _intentional_gap(project: Mapping[str, Any], track_id: str, start: float, end: float) -> bool:
    return any(
        item.get("kind") == "intentional_gap"
        and item.get("data", {}).get("track_id") == track_id
        and item.get("data", {}).get("start") == start
        and item.get("data", {}).get("end") == end
        for item in project.get("decisions", {}).values()
    )
