"""`rite.py stats` — the numbers a retro starts from. Counted, never estimated."""

from __future__ import annotations

import datetime as dt
import statistics

from . import markdown
from .config import SEVERITIES
from .model import Cycle, Project, display


def _days(a, b) -> int | None:
    try:
        return (dt.date.fromisoformat(str(b)) - dt.date.fromisoformat(str(a))).days
    except ValueError:
        return None


def cycle_stats(project: Project, cycle: Cycle) -> dict:
    tasks, fixes = cycle.tasks, cycle.fixes
    by_status = {}
    for t in tasks:
        by_status[t.status] = by_status.get(t.status, 0) + 1
    fix_status = {}
    for f in fixes:
        fix_status[f.status] = fix_status.get(f.status, 0) + 1
    sev = {s: sum(1 for f in fixes if f.fields.get("severity") == s) for s in SEVERITIES}
    per_origin: dict[str, int] = {}
    for f in fixes:
        origin = str(f.fields.get("origin") or "?")
        per_origin[origin] = per_origin.get(origin, 0) + 1
    latency = [d for t in tasks if (d := _days(t.fields.get("done_on"), t.fields.get("reviewed_on"))) is not None]
    by_phase: dict[str, dict] = {}
    index = cycle.by_id()
    for t in tasks:
        ph = str(t.fields.get("phase"))
        by_phase.setdefault(ph, {"tasks": 0, "fixes": 0})["tasks"] += 1
    for f in fixes:
        origin = index.get(str(f.fields.get("origin")))
        while origin is not None and origin.kind == "fix":  # fixes of fixes count against the root task
            origin = index.get(str(origin.fields.get("origin")))
        if origin is not None:
            by_phase.setdefault(str(origin.fields.get("phase")), {"tasks": 0, "fixes": 0})["fixes"] += 1
    log_titles = project.section_titles("execution_log")
    return {
        "cycle": cycle.name,
        "path": display(project.root, cycle.path),
        "archived": cycle.archived,
        "tasks": {"total": len(tasks), **by_status},
        "fixes": {"total": len(fixes), **fix_status, "by_severity": sev},
        "fixes_per_task": round(len(fixes) / len(tasks), 2) if tasks else None,
        "fixes_by_origin": dict(sorted(per_origin.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_phase": by_phase,
        "review_latency_days": {
            "median": statistics.median(latency) if latency else None,
            "max": max(latency) if latency else None,
            "reviewed": len(latency),
        },
        "fix_files": [display(project.root, f.path) for f in fixes],
        "items_without_log": [i.id for i in cycle.items
                              if i.status in ("done", "stale")
                              and not (markdown.first_section(i.body, log_titles) or ("", ""))[1].strip()],
    }


def render_text(s: dict) -> str:
    t, f = s["tasks"], s["fixes"]
    lines = [
        f"cycle {s['cycle']} ({s['path']}){' [archived]' if s['archived'] else ''}",
        "  tasks: " + ", ".join(f"{k} {v}" for k, v in t.items()),
        "  fixes: " + ", ".join(f"{k} {v}" for k, v in f.items() if k != "by_severity"),
        "  by severity: " + ", ".join(f"{k} {v}" for k, v in f["by_severity"].items()),
        f"  fixes per task: {s['fixes_per_task']}",
        "  most fixes from: " + (", ".join(f"{k} ({v})" for k, v in list(s["fixes_by_origin"].items())[:5]) or "—"),
        "  by phase: " + ", ".join(f"{p}: {v['tasks']}t/{v['fixes']}f" for p, v in s["by_phase"].items()),
        f"  review latency (days): median {s['review_latency_days']['median']}, "
        f"max {s['review_latency_days']['max']} over {s['review_latency_days']['reviewed']} reviews",
    ]
    if s["items_without_log"]:
        lines.append("  closed without execution log: " + ", ".join(s["items_without_log"]))
    return "\n".join(lines)
