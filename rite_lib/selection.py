"""Deterministic selection: next task / review / fix, and the cycle status summary."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .config import SEVERITIES
from .model import Cycle, Item

SATISFIED = {"done", "skipped", "stale"}


@dataclass
class Pick:
    item: Item | None
    reason: str
    blocked_by: dict[str, list[str]] | None = None

    def as_dict(self, root) -> dict:
        from .model import display
        return {
            "id": self.item.id if self.item else None,
            "title": self.item.title if self.item else None,
            "path": display(root, self.item.path) if self.item else None,
            "reason": self.reason,
            "blocked_by": self.blocked_by or {},
        }


def unmet_deps(item: Item, index: dict[str, Item]) -> list[str]:
    return [d for d in item.depends_on if d not in index or index[d].status not in SATISFIED]


def next_task(cycle: Cycle) -> Pick:
    index = cycle.by_id()
    tasks = cycle.tasks
    for t in tasks:
        if t.status == "in-progress":
            return Pick(t, "in-progress task resumes first")
    blocked: dict[str, list[str]] = {}
    for t in tasks:
        if t.status != "pending":
            continue
        missing = unmet_deps(t, index)
        if not missing:
            return Pick(t, "first pending task (in ID order) whose depends_on are satisfied")
        blocked[t.id] = missing
    if blocked:
        first = next(iter(blocked))
        return Pick(None, f"all pending tasks are blocked; {first} waits for {', '.join(blocked[first])}", blocked)
    explicit = [t.id for t in tasks if t.status == "blocked"]
    if explicit:
        return Pick(None, f"no pending task; status=blocked: {', '.join(explicit)}", {i: [] for i in explicit})
    return Pick(None, "no pending task")


def review_queue(cycle: Cycle) -> list[Item]:
    return [t for t in cycle.tasks if t.status == "done" and t.fields.get("reviewed_on") == "pending"]


def next_review(cycle: Cycle) -> Pick:
    queue = review_queue(cycle)
    if queue:
        return Pick(queue[0], "lowest-ID task done and awaiting review")
    return Pick(None, "review queue is empty")


def open_fixes(cycle: Cycle) -> list[Item]:
    return [f for f in cycle.fixes if f.status in ("pending", "in-progress")]


def next_fix(cycle: Cycle) -> Pick:
    index = cycle.by_id()
    fixes = sorted(open_fixes(cycle), key=lambda f: (f.status != "in-progress", f.severity_rank, f.n))
    blocked: dict[str, list[str]] = {}
    for f in fixes:
        missing = unmet_deps(f, index)
        if f.status == "in-progress":
            return Pick(f, "in-progress fix resumes first")
        if not missing:
            return Pick(f, "most severe open fix (then lowest ID) whose depends_on are satisfied")
        blocked[f.id] = missing
    if blocked:
        first = next(iter(blocked))
        return Pick(None, f"all open fixes are blocked; {first} waits for {', '.join(blocked[first])}", blocked)
    return Pick(None, "no open fix")


def _age(date_value, today: dt.date) -> int | None:
    try:
        return (today - dt.date.fromisoformat(str(date_value))).days
    except ValueError:
        return None


def summary(cycle: Cycle, *, review_age_days: int, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    counts = {s: 0 for s in ("pending", "in-progress", "done", "blocked", "skipped")}
    for t in cycle.tasks:
        counts[t.status] = counts.get(t.status, 0) + 1
    queue = review_queue(cycle)
    aged = [t for t in queue if (_age(t.fields.get("done_on"), today) or 0) > review_age_days]
    fixes = open_fixes(cycle)
    by_sev = {s: sum(1 for f in fixes if f.fields.get("severity") == s) for s in SEVERITIES}
    task_pick, fix_pick, review_pick = next_task(cycle), next_fix(cycle), next_review(cycle)

    if by_sev["critical"] or by_sev["high"]:
        suggestion = ("fix", "critical/high fixes are open — fix before building on top of them")
    elif aged or len(queue) >= 3:
        suggestion = ("review", f"review queue has {len(queue)} item(s)"
                      + (f", {len(aged)} older than {review_age_days} days" if aged else ""))
    elif task_pick.item:
        suggestion = ("execute", f"next task {task_pick.item.id} is ready")
    elif queue:
        suggestion = ("review", "no task ready; review queue not empty")
    elif fix_pick.item:
        suggestion = ("fix", "no task ready; open fixes remain")
    elif not cycle.tasks:
        suggestion = ("plan-to-tasks", "cycle has no tasks")
    elif all(t.status in ("done", "skipped") for t in cycle.tasks) and not fixes:
        suggestion = ("close-cycle", "every task done/skipped and reviewed, no open fix")
    else:
        suggestion = ("unblock", task_pick.reason)

    return {
        "cycle": cycle.name,
        "prefix": cycle.prefix,
        "archived": cycle.archived,
        "tasks": {**counts, "total": len(cycle.tasks)},
        "review_queue": [t.id for t in queue],
        "review_aged": [t.id for t in aged],
        "open_fixes": by_sev,
        "next_task": task_pick,
        "next_review": review_pick,
        "next_fix": fix_pick,
        "suggestion": {"command": suggestion[0], "reason": suggestion[1]},
    }
