from __future__ import annotations

from typing import Any, Mapping

from .verification import verify_project


def render_cut_manifest(project: Mapping[str, Any], *, report: Mapping[str, Any] | None = None) -> str:
    report = report or verify_project(project)
    lines = [
        f"# Cut Manifest: {project['title']}", "",
        f"- Project: `{project['project_id']}`",
        f"- Revision: `{project['revision']}`",
        f"- Status: `{project['status']}`",
        f"- Protocol gate: `{'PASS' if report['passed'] else 'FAIL'}`", "",
        "## Source ledger", "",
    ]
    for item in project.get("sources", {}).values():
        lines.append(f"- `{item['source_id']}` — {item['locator']} (original={item['original']})")
    lines.extend(["", "## Tracks and segments", ""])
    for track in project.get("tracks", {}).values():
        lines.append(f"- `{track['track_id']}` ({track['kind']}, {track['purpose']})")
        for segment in project.get("segments", {}).values():
            if segment["track_id"] == track["track_id"]:
                lines.append(
                    f"  - `{segment['segment_id']}` ← `{segment['source_id']}` "
                    f"[{segment['source_in']:.3f}, {segment['source_out']:.3f}] @ {segment['timeline_start']:.3f}"
                )
    _append_records(lines, "Controls", project.get("controls", {}), "control_id")
    _append_records(lines, "Captions", project.get("captions", {}), "caption_id")
    _append_records(lines, "Decisions", project.get("decisions", {}), "decision_id")
    _append_records(lines, "Capability downgrades", project.get("capability_downgrades", {}), "exception_id")
    _append_records(lines, "External editor entities", project.get("external_entities", {}), "external_entity_id")
    lines.extend(["", "## Verification", ""])
    for item in project.get("verification", []):
        lines.append(f"- `{item['verification_id']}` {item['kind']}: {'PASS' if item['passed'] else 'FAIL'}")
    for issue in report.get("issues", []):
        lines.append(f"- ISSUE `{issue['code']}` [{issue['target']}]: {issue['message']}")
    return "\n".join(lines) + "\n"


def _append_records(lines: list[str], title: str, records: Mapping[str, Any], id_key: str) -> None:
    lines.extend(["", f"## {title}", ""])
    for item in records.values():
        lines.append(f"- `{item[id_key]}` — {item}")
