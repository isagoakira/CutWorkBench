from __future__ import annotations

from typing import Any, Mapping


def verify_project(project: Mapping[str, Any]) -> dict[str, Any]:
    """Run deterministic Cut Protocol gates; semantic judgment remains a capability job."""
    issues: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    audited_sources = {
        decision.get("source_id")
        for decision in project.get("decisions", {}).values()
        if decision.get("kind") == "source_audit"
        and decision.get("data", {}).get("coverage") == "full"
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

    for track_id, track in project.get("tracks", {}).items():
        if track.get("kind") not in {"video", "audio"}:
            continue
        segments = sorted(
            (item for item in project.get("segments", {}).values() if item["track_id"] == track_id),
            key=lambda item: (item["timeline_start"], item["segment_id"]),
        )
        previous_end = None
        for segment in segments:
            duration = (segment["source_out"] - segment["source_in"]) / segment["speed"]
            start = segment["timeline_start"]
            if previous_end is not None and start < previous_end - 1e-6:
                issues.append({
                    "code": "track-overlap", "target": track_id,
                    "message": f"Segment {segment['segment_id']} overlaps the preceding segment",
                })
            previous_end = max(previous_end or 0, start + duration)
        checks.append({
            "check": "track-non-overlap", "target": track_id,
            "passed": not any(i["code"] == "track-overlap" and i["target"] == track_id for i in issues),
        })

    if project.get("status") in {"review", "delivered", "handed_off"}:
        visual_pass = any(
            item.get("kind") == "visual" and item.get("passed") and item.get("evidence")
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
