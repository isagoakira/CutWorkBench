from __future__ import annotations

import json
from typing import Any, Mapping, Protocol
from urllib import error, request

from .errors import ValidationError


class VectCutCompiler:
    """Compiles a frozen workbench revision into an auditable VectCut call plan."""

    def compile(self, project: Mapping[str, Any], *, draft_folder: str | None = None) -> dict[str, Any]:
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
            if control.get("enabled", True) and control.get("kind") not in {"mask", "mask_blur", "effect"}:
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
        for segment in segments:
            track = project["tracks"][segment["track_id"]]
            source = project["sources"][segment["source_id"]]
            if track["kind"] not in {"video", "audio"}:
                continue
            tool = "add_video" if track["kind"] == "video" else "add_audio"
            media_key = "video_url" if track["kind"] == "video" else "audio_url"
            arguments: dict[str, Any] = {
                "draft_id": draft_ref,
                media_key: source["locator"],
                "start": segment["source_in"],
                "end": segment["source_out"],
                "target_start": segment["timeline_start"],
                "track_name": segment["track_id"],
                "width": canvas["width"],
                "height": canvas["height"],
                "speed": segment["speed"],
            }
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

    def call(self, tool: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
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
        if not isinstance(result, Mapping):
            raise ValidationError(f"VectCut result is not an object for {tool}")
        return result


def _vectcut_transform(transform: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"transform_x", "transform_y", "scale_x", "scale_y", "rotation"}
    return {key: value for key, value in transform.items() if key in allowed}


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
