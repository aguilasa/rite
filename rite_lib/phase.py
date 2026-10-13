"""`rite.py phase` — what one phase of a cycle delivered, finished or in progress. Read-only.

The command that reads it writes prose over these facts; nothing here is re-told from the plan. A gate
result is not data anywhere: it lives in each task's Execution Log, which is returned as written.
"""

from __future__ import annotations

from . import markdown, selection
from .config import OPEN_FIX_STATUSES
from .model import Cycle, Project, RiteError, display
from .stats import root_task

LOG_LINES = 40  # per task: enough for the closing notes, not a whole transcript


def phases(cycle: Cycle) -> list[str]:
    """The cycle's phases in the order their first task appears (tasks come in ID order)."""
    seen: list[str] = []
    for t in cycle.tasks:
        ph = str(t.fields.get("phase"))
        if ph not in seen:
            seen.append(ph)
    return seen


def default_phase(cycle: Cycle) -> str:
    """The last phase with a task done — a closed phase or the one in progress."""
    done = {str(t.fields.get("phase")) for t in cycle.tasks if t.status == "done"}
    for ph in reversed(phases(cycle)):
        if ph in done:
            return ph
    raise RiteError(f"cycle {cycle.name} has no task done yet; name a phase with --phase")


def _log(project: Project, body: str) -> dict:
    found = markdown.first_section(body, project.section_titles("execution_log"))
    lines = (found[1] if found else "").strip().splitlines()
    return {"text": "\n".join(lines[-LOG_LINES:]), "truncated": len(lines) > LOG_LINES}


def phase_report(project: Project, cycle: Cycle, phase: str | None = None, *,
                 review_age_days: int = 7) -> dict:
    known = phases(cycle)
    phase = str(phase) if phase is not None else default_phase(cycle)
    if phase not in known:
        raise RiteError(f"cycle {cycle.name} has no phase {phase!r}; phases: {', '.join(known) or 'none'}")
    index = cycle.by_id()
    tasks = [t for t in cycle.tasks if str(t.fields.get("phase")) == phase]
    ids = {t.id for t in tasks}
    fixes = [f for f in cycle.fixes if (root := root_task(f, index)) is not None and root.id in ids]
    waiting = {t.id: selection.unmet_deps(t, index) for t in tasks if t.status == "pending"}
    summary = selection.summary(cycle, review_age_days=review_age_days)
    return {
        "cycle": cycle.name,
        "phase": phase,
        "phases": known,
        "tasks": [{
            "id": t.id, "title": t.title, "status": t.status, "type": t.fields.get("type"),
            "path": display(project.root, t.path), "done_commit": t.fields.get("done_commit"),
            "done_on": t.fields.get("done_on"), "reviewed_on": t.fields.get("reviewed_on"),
            "log": _log(project, t.body),
        } for t in tasks],
        "fixes": [{
            "id": f.id, "title": f.title, "severity": f.fields.get("severity"), "status": f.status,
            "origin": f.fields.get("origin"),
        } for f in fixes],
        "pending": [t.id for t in tasks if t.status in ("pending", "in-progress") and not waiting.get(t.id)],
        "blocked": {t.id: waiting.get(t.id) or [] for t in tasks
                    if t.status == "blocked" or waiting.get(t.id)},
        "finished": all(t.status in ("done", "skipped") for t in tasks)
                    and not any(f.status in OPEN_FIX_STATUSES for f in fixes),
        "next": summary["suggestion"],
    }


def render_text(r: dict) -> str:
    lines = [f"cycle {r['cycle']}, phase {r['phase']} ({'finished' if r['finished'] else 'in progress'})"]
    for t in r["tasks"]:
        lines.append(f"  {t['id']} [{t['status']}] {t['title']}"
                     + (f" — {t['done_commit']}" if t["done_commit"] else ""))
    for f in r["fixes"]:
        lines.append(f"  {f['id']} [{f['severity']}, {f['status']}] {f['title']}")
    if r["blocked"]:
        lines.append("  blocked: " + ", ".join(f"{k} ({', '.join(v) or 'status=blocked'})"
                                              for k, v in r["blocked"].items()))
    lines.append(f"  next: /rite:{r['next']['command']} — {r['next']['reason']}")
    return "\n".join(lines)
