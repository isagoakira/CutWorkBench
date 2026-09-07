from __future__ import annotations

import json
import math
import os
import platform
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib import error, request

from .errors import ValidationError


class VectCutCompiler:
    """Compiles a frozen workbench revision into an auditable VectCut call plan."""

    def compile(self, project: Mapping[str, Any], *, draft_folder: str | None = None) -> dict[str, Any]:
        if project.get("external_entities"):
            raise ValidationError(
                "full VectCut compilation cannot preserve imported external entities; use sync.publish for incremental round-trip"
            )
        logical_draft_id = f"{project['project_id']}-r{project['revision']:06d}"
        canvas = project["canvas"]
        draft_ref = {"$ref": "create_draft.result.draft_id"}
        calls: list[dict[str, Any]] = [
            {
                "call_id": "create_draft",
                "tool": "create_draft",
                "arguments": {"width": canvas["width"], "height": canvas["height"]},
            }
        ]

        controls_by_segment: dict[str, list[Mapping[str, Any]]] = {}
        for control in project["controls"].values():
            if control.get("enabled", True) and control.get("kind") not in {
                "mask", "mask_blur", "effect", "privacy_overlay",
            }:
                raise ValidationError(
                    f"VectCut compiler cannot preserve control kind {control.get('kind')!r} "
                    f"({control.get('control_id')}); add a target mapping or record an approved downgrade"
                )
            controls_by_segment.setdefault(control["target_segment_id"], []).append(control)

        unsupported_segments = [
            segment["segment_id"] for segment in project["segments"].values()
            if project["tracks"][segment["track_id"]]["kind"] not in {"video", "audio"}
        ]
        if unsupported_segments:
            raise ValidationError(
                "VectCut compiler cannot preserve non-video/audio source segments: "
                + ", ".join(sorted(unsupported_segments))
            )

        segments = sorted(
            project["segments"].values(),
            key=lambda segment: (segment["timeline_start"], segment["track_id"], segment["segment_id"]),
        )
        # Jianying stores time in integer microseconds.  A mathematically
        # contiguous plan can therefore overlap by one microsecond when a
        # speed-derived duration has a repeating decimal (for example 2.3 /
        # .75).  Quantize each emitted track monotonically so a new draft
        # never rejects an otherwise gap-free Workbench timeline.
        emitted_track_ends_us: dict[str, int] = {}
        for segment in segments:
            track = project["tracks"][segment["track_id"]]
            source = project["sources"][segment["source_id"]]
            if track["kind"] not in {"video", "audio"}:
                continue
            tool = "add_video" if track["kind"] == "video" else "add_audio"
            media_key = "video_url" if track["kind"] == "video" else "audio_url"
            requested_start_us = round(float(segment["timeline_start"]) * 1_000_000)
            duration_us = math.ceil(
                (float(segment["source_out"]) - float(segment["source_in"]))
                / float(segment["speed"])
                * 1_000_000
            )
            emitted_start_us = max(requested_start_us, emitted_track_ends_us.get(segment["track_id"], 0))
            emitted_track_ends_us[segment["track_id"]] = emitted_start_us + duration_us
            arguments: dict[str, Any] = {
                "draft_id": draft_ref,
                media_key: source["locator"],
                "start": segment["source_in"],
                "end": segment["source_out"],
                "target_start": emitted_start_us / 1_000_000,
                "track_name": segment["track_id"],
                "width": canvas["width"],
                "height": canvas["height"],
                "speed": segment["speed"],
            }
            if tool == "add_video" and source.get("media_profile", {}).get("audio_policy") == "mute":
                arguments["volume"] = 0.0
            arguments.update(_vectcut_transform(segment.get("transform", {})))
            for control in controls_by_segment.get(segment["segment_id"], []):
                if not control.get("enabled", True):
                    continue
                if control["kind"] in {"mask", "mask_blur"}:
                    _require_full_segment_control(segment, control)
                    arguments.update(control["properties"])
            calls.append(
                {
                    "call_id": f"segment:{segment['segment_id']}",
                    "stable_id": segment["segment_id"],
                    "tool": tool,
                    "arguments": arguments,
                }
            )

        for control in sorted(project["controls"].values(), key=lambda item: item["control_id"]):
            if not control.get("enabled", True) or control["kind"] != "effect":
                continue
            props = control["properties"]
            active_range = control.get("active_range", {})
            calls.append(
                {
                    "call_id": f"control:{control['control_id']}",
                    "stable_id": control["control_id"],
                    "tool": "add_effect",
                    "arguments": {
                        "draft_id": draft_ref,
                        "effect_type": props.get("effect_type"),
                        "effect_category": props.get("effect_category", "scene"),
                        "start": active_range.get("start", 0),
                        "end": active_range.get("end", 0),
                        "track_name": control["track_id"],
                        "params": props.get("params"),
                        "width": canvas["width"],
                        "height": canvas["height"],
                    },
                }
            )

        privacy_track_names = _assign_privacy_overlay_tracks(project["controls"].values())
        for control in sorted(project["controls"].values(), key=lambda item: item["control_id"]):
            if not control.get("enabled", True) or control["kind"] != "privacy_overlay":
                continue
            properties = control["properties"]
            asset_path = properties.get("asset_path")
            active_range = control.get("active_range", {})
            if not isinstance(asset_path, str) or not asset_path:
                raise ValidationError(
                    f"privacy_overlay control {control['control_id']} requires properties.asset_path"
                )
            start = active_range.get("start")
            end = active_range.get("end")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
                raise ValidationError(
                    f"privacy_overlay control {control['control_id']} requires a non-empty active_range"
                )
            calls.append(
                {
                    "call_id": f"control:{control['control_id']}",
                    "stable_id": control["control_id"],
                    "tool": "add_image",
                    "arguments": {
                        "draft_id": draft_ref,
                        "image_url": asset_path,
                        "start": start,
                        "end": end,
                        # VectCut rejects overlapping images on one physical
                        # track. Reuse the smallest possible pool of child
                        # lanes instead of allocating one lane per overlay;
                        # the logical Workbench V2 track remains unchanged.
                        "track_name": privacy_track_names[control["control_id"]],
                        "relative_index": properties.get("relative_index", 10),
                        "width": canvas["width"],
                        "height": canvas["height"],
                        **_vectcut_transform(properties.get("transform", {})),
                    },
                }
            )

        for caption in sorted(project["captions"].values(), key=lambda item: (item["start"], item["caption_id"])):
            calls.append(
                {
                    "call_id": f"caption:{caption['caption_id']}",
                    "stable_id": caption["caption_id"],
                    "tool": "add_text",
                    "arguments": {
                        "draft_id": draft_ref,
                        "track_name": caption["track_id"],
                        "text": caption["text"],
                        "start": caption["start"],
                        "end": caption["end"],
                        "width": canvas["width"],
                        "height": canvas["height"],
                        **caption.get("style", {}),
                    },
                }
            )

        save_arguments: dict[str, Any] = {"draft_id": draft_ref}
        if draft_folder:
            save_arguments["draft_folder"] = draft_folder
        calls.append({"call_id": "save_draft", "tool": "save_draft", "arguments": save_arguments})
        return {
            "schema_version": 1,
            "compiler": "vectcut",
            "project_id": project["project_id"],
            "revision": project["revision"],
            "draft_id": logical_draft_id,
            "calls": calls,
        }


class VectCutTransport(Protocol):
    def call(self, tool: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]: ...


class VectCutExecutor:
    """Executes a frozen call plan through HTTP, MCP, or an in-process VectCut transport."""

    def __init__(self, transport: VectCutTransport) -> None:
        self.transport = transport

    def execute(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        results: dict[str, Mapping[str, Any]] = {}
        receipts: list[dict[str, Any]] = []
        for call in plan.get("calls", []):
            arguments = _resolve_refs(call.get("arguments", {}), results)
            result = dict(self.transport.call(call["tool"], arguments))
            results[call["call_id"]] = result
            receipts.append({"call_id": call["call_id"], "tool": call["tool"], "result": result})
        return {"status": "completed", "calls": receipts}


class VectCutHttpTransport:
    """Local VectCutAPI HTTP adapter (defaults to its documented localhost port)."""

    def __init__(self, base_url: str = "http://127.0.0.1:9001", timeout: float = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        """Check that a local VectCutAPI HTTP service is reachable without mutating a draft."""
        try:
            with request.urlopen(f"{self.base_url}/get_mask_types", timeout=min(self.timeout, 5)) as response:
                value = json.loads(response.read().decode("utf-8"))
                valid = isinstance(value, dict) and value.get("success") is True and isinstance(value.get("output"), list)
                return {"reachable": valid, "base_url": self.base_url, "http_status": response.status}
        except (error.URLError, OSError, ValueError) as exc:
            return {"reachable": False, "base_url": self.base_url, "error": str(exc)}

    def call(self, tool: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if tool == "save_draft" and arguments.get("draft_folder"):
            draft_id = str(arguments.get("draft_id", ""))
            if not draft_id or Path(draft_id).name != draft_id or "/" in draft_id or "\\" in draft_id:
                raise ValidationError("invalid VectCut draft ID")
            if (Path(arguments["draft_folder"]) / draft_id).exists():
                raise ValidationError("refusing to overwrite an existing VectCut draft")
        body = json.dumps(dict(arguments), ensure_ascii=False).encode("utf-8")
        http_request = request.Request(
            f"{self.base_url}/{tool}", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError) as exc:
            raise ValidationError(f"VectCut HTTP call failed for {tool}: {exc}") from exc
        if not isinstance(value, Mapping):
            raise ValidationError(f"VectCut HTTP call returned a non-object for {tool}")
        if value.get("success") is False:
            raise ValidationError(f"VectCut rejected {tool}: {value.get('error') or value.get('message')}")
        result = value.get("output", value.get("result", value))
        if isinstance(result, str) and tool == "query_script":
            result = json.loads(result)
        if not isinstance(result, Mapping):
            raise ValidationError(f"VectCut result is not an object for {tool}")
        if result.get("success") is False:
            raise ValidationError(f"VectCut rejected {tool}: {result.get('error')}")
        return result


def default_vectcut_draft_folder(system: str | None = None, home: Path | None = None) -> Path:
    """Return the conventional Jianying draft root without assuming a particular host machine."""
    system = system or platform.system()
    home = home or Path.home()
    if system == "Darwin":
        return home / "Movies" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"
    return home / ".local" / "share" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"


def _vectcut_transform(transform: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"transform_x", "transform_y", "scale_x", "scale_y", "rotation"}
    return {key: value for key, value in transform.items() if key in allowed}


def _assign_privacy_overlay_tracks(controls: Any) -> dict[str, str]:
    """Color overlay intervals into the fewest editor-native image lanes.

    VectCut cannot place overlapping image segments on one physical track.
    Interval coloring is optimal for this case: the number of generated lanes
    equals the maximum simultaneous overlay count, and non-overlapping covers
    reuse an existing lane.  This protects editability without turning a
    modest control list into an unmanageable stack of tracks.
    """
    grouped: dict[str, list[tuple[int, int, str]]] = {}
    for control in controls:
        if not control.get("enabled", True) or control.get("kind") != "privacy_overlay":
            continue
        active_range = control.get("active_range", {})
        start, end = active_range.get("start"), active_range.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            raise ValidationError(
                f"privacy_overlay control {control['control_id']} requires a non-empty active_range"
            )
        grouped.setdefault(control["track_id"], []).append(
            (round(float(start) * 1_000_000), round(float(end) * 1_000_000), control["control_id"])
        )

    assignments: dict[str, str] = {}
    for logical_track, intervals in grouped.items():
        lane_ends: list[int] = []
        for start_us, end_us, control_id in sorted(intervals, key=lambda item: (item[0], item[1], item[2])):
            reusable = [index for index, lane_end_us in enumerate(lane_ends) if lane_end_us <= start_us]
            if reusable:
                lane_index = reusable[0]
                lane_ends[lane_index] = end_us
            else:
                lane_index = len(lane_ends)
                lane_ends.append(end_us)
            assignments[control_id] = f"{logical_track}__L{lane_index + 1:02d}"
    return assignments


def _require_full_segment_control(segment: Mapping[str, Any], control: Mapping[str, Any]) -> None:
    active = control.get("active_range", {})
    segment_start = segment["timeline_start"]
    segment_end = segment_start + (segment["source_out"] - segment["source_in"]) / segment["speed"]
    if active and (active.get("start") != segment_start or active.get("end") != segment_end):
        raise ValidationError(
            f"VectCut mask control {control['control_id']} must target a time-bounded treatment segment; "
            "split the treatment segment to the control range before compiling"
        )


def _resolve_refs(value: Any, results: Mapping[str, Mapping[str, Any]]) -> Any:
    if isinstance(value, dict) and set(value) == {"$ref"}:
        parts = value["$ref"].split(".")
        if len(parts) < 3 or parts[1] != "result":
            raise ValidationError(f"invalid call-plan reference: {value['$ref']}")
        resolved: Any = results.get(parts[0])
        if resolved is None:
            raise ValidationError(f"unresolved call-plan reference: {value['$ref']}")
        for part in parts[2:]:
            if not isinstance(resolved, Mapping) or part not in resolved:
                raise ValidationError(f"unresolved call-plan reference: {value['$ref']}")
            resolved = resolved[part]
        return resolved
    if isinstance(value, dict):
        return {key: _resolve_refs(item, results) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_refs(item, results) for item in value]
    return value
