"""Generated regions of progress.md / fixes.md. Data lives in item frontmatter; tables are views."""

from __future__ import annotations

from pathlib import Path

from .model import Cycle, Project, make_link

TASKS_REGION = "tasks"
FIXES_REGION = "fixes"


def begin_marker(region: str) -> str:
    return f"<!-- rite:begin {region} -->"


END_MARKER = "<!-- rite:end -->"


def _cell(value) -> str:
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return str(value).replace("|", "\\|").replace("\n", " ")


def tasks_table(project: Project, cycle: Cycle) -> str:
    style = project.cfg.link_style
    rows = ["| ID | Title | Phase | Type | Depends on | Status | Done on | Reviewed on |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in cycle.tasks:
        link = make_link(project.root, cycle.progress_path, t.path, style)
        f = t.fields
        rows.append(f"| [{t.id}]({link}) | {_cell(t.title)} | {_cell(f.get('phase'))} | {_cell(f.get('type'))} "
                    f"| {_cell(t.depends_on)} | {_cell(t.status)} | {_cell(f.get('done_on'))} "
                    f"| {_cell(f.get('reviewed_on'))} |")
    if not cycle.tasks:
        rows.append("| — | *(no tasks yet)* | | | | | | |")
    return "\n".join(rows)


def fixes_table(project: Project, cycle: Cycle) -> str:
    style = project.cfg.link_style
    rows = ["| ID | Title | Origin | Severity | Status | Done on |",
            "| --- | --- | --- | --- | --- | --- |"]
    for fx in cycle.fixes:
        link = make_link(project.root, cycle.fixes_path, fx.path, style)
        f = fx.fields
        rows.append(f"| [{fx.id}]({link}) | {_cell(fx.title)} | {_cell(f.get('origin'))} "
                    f"| {_cell(f.get('severity'))} | {_cell(fx.status)} | {_cell(f.get('done_on'))} |")
    if not cycle.fixes:
        rows.append("| — | *(no fixes)* | | | | |")
    return "\n".join(rows)


def replace_region(text: str, region: str, content: str) -> str:
    begin = begin_marker(region)
    block = f"{begin}\n{content}\n{END_MARKER}"
    start = text.find(begin)
    if start == -1:
        sep = "" if text.endswith("\n\n") or not text else ("\n" if text.endswith("\n") else "\n\n")
        return f"{text}{sep}{block}\n"
    end = text.find(END_MARKER, start)
    if end == -1:
        raise ValueError(f"'{begin}' without '{END_MARKER}'")
    return text[:start] + block + text[end + len(END_MARKER):]


def extract_region(text: str, region: str) -> str | None:
    begin = begin_marker(region)
    start = text.find(begin)
    if start == -1:
        return None
    end = text.find(END_MARKER, start)
    if end == -1:
        return None
    return text[start + len(begin):end].strip("\n")


def expected(project: Project, cycle: Cycle) -> dict[Path, tuple[str, str]]:
    """{file: (region, generated content)}"""
    return {
        cycle.progress_path: (TASKS_REGION, tasks_table(project, cycle)),
        cycle.fixes_path: (FIXES_REGION, fixes_table(project, cycle)),
    }


def out_of_sync(project: Project, cycle: Cycle) -> list[Path]:
    stale = []
    for path, (region, content) in expected(project, cycle).items():
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if extract_region(current, region) != content:
            stale.append(path)
    return stale


def sync(project: Project, cycle: Cycle) -> list[Path]:
    """Rewrite only the generated regions. Idempotent. Returns files that changed."""
    changed = []
    for path, (region, content) in expected(project, cycle).items():
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if not current:
            title = "Fixes" if region == FIXES_REGION else "Progress"
            current = f"# {title} — {cycle.name}\n"
        new = replace_region(current, region, content)
        if new != current:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed.append(path)
    return changed
