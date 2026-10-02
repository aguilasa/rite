"""Generated regions of progress.md (tasks table, dependency graph) / fixes.md. Data lives in the cycle's JSON; tables are views.

The rendering is ``render_md`` (standalone, stdlib only). This module adds what only Rite knows: the
JSON arrays are kept in execution order before rendering, so the rows read in the order work runs.
"""

from __future__ import annotations

from pathlib import Path

from . import render_md, state
from .model import Cycle, Project
from .render_md import END_MARKER, FIXES_REGION, GRAPH_REGION, TASKS_REGION, begin_marker, extract_region, replace_region  # noqa: F401


def names(project: Project) -> dict:
    return {"progress_file": project.progress_name, "fixes_file": project.fixes_name,
            "progress_state": project.progress_state, "fixes_state": project.fixes_state}


def _opts(project: Project) -> dict:
    return {"root": project.root, "link_style": project.cfg.link_style, "names": names(project),
            "phase_label": project.section_title("phase_label")}


def unordered(project: Project, cycle: Cycle) -> list[Path]:
    """State files whose item array is not in execution order (rows would render out of order)."""
    out = []
    for path, kind, key in ((cycle.progress_state_path, "task", project.execution_key(cycle.order)),
                            (cycle.fixes_state_path, "fix", lambda e: project.entry_n("fix", e))):
        entries = [i.fields | {"file": i.file} for i in cycle.items if i.kind == kind]
        if [e.get("id") for e in entries] != [e.get("id") for e in sorted(entries, key=key)]:
            out.append(path)
    return out


def expected(project: Project, cycle: Cycle) -> dict[Path, list[tuple[str, str]]]:
    """{file: [(region, generated content), ...]}"""
    return render_md.views(cycle.path, **_opts(project))


def out_of_sync(project: Project, cycle: Cycle) -> list[Path]:
    return unordered(project, cycle) + render_md.out_of_sync(cycle.path, **_opts(project))


def sync(project: Project, cycle: Cycle) -> list[Path]:
    """Put the JSON arrays in execution order, then rewrite only the generated regions. Idempotent.
    Returns files that changed."""
    changed = []
    if state.reorder(cycle.progress_state_path, "task", project.execution_key(cycle.order)):
        changed.append(cycle.progress_state_path)
    if state.reorder(cycle.fixes_state_path, "fix", lambda e: project.entry_n("fix", e)):
        changed.append(cycle.fixes_state_path)
    return changed + render_md.render(cycle.path, **_opts(project))
