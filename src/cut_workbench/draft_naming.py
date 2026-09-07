from __future__ import annotations

import re


_WINDOWS_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def default_draft_name(
    project_title: str,
    *,
    revision: int,
    change_summary: str | None = None,
    release_version: int | None = None,
) -> str:
    """Return the default editor-draft label: project-vN-change."""
    project_name = _file_safe_component(project_title.split("｜", 1)[0]) or "untitled-project"
    version = release_version if release_version is not None else revision
    if not isinstance(version, int) or version < 1:
        raise ValueError("release_version must be a positive integer")
    progress = _file_safe_component(change_summary or "编辑发布") or "编辑发布"
    return f"{project_name}-v{version}-{progress}"


def _file_safe_component(value: str) -> str:
    cleaned = _WINDOWS_FORBIDDEN.sub("-", str(value)).strip(" .-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80]
