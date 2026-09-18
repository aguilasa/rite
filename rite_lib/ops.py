"""State-changing operations. The only code path allowed to write item status."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from . import frontmatter, gitutil, views
from .config import FIX_STATUSES, SEVERITIES, TASK_STATUSES
from .markdown import append_to_section
from .model import Cycle, Item, Project, RiteError, display, make_link
from .naming import slugify

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BOOKKEEPING_PREFIXES = ("chore(rite):", "rite:")


# --- helpers -----------------------------------------------------------------
def bookkeeping_message(project: Project, verb: str, item_id: str, detail: str = "") -> str:
    head = "chore(rite):" if project.cfg["commit"]["style"] == "conventional" else "rite:"
    return f"{head} {verb} {item_id}{detail}"


def template_path(project: Project, name: str) -> Path:
    local = project.cfg["paths"]["templates_dir"]
    if local:
        candidate = project.root / local / name
        if candidate.is_file():
            return candidate
    return PLUGIN_ROOT / "templates" / name


def render(project: Project, name: str, values: dict) -> str:
    text = template_path(project, name).read_text(encoding="utf-8")
    values = {**values, "execution_log": project.cfg["sections"]["execution_log"]}
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def _write_item(item: Item, updates: dict, log_line: str | None, log_title: str) -> None:
    text = item.path.read_text(encoding="utf-8")
    text = frontmatter.set_fields(text, updates)
    if log_line:
        text = append_to_section(text, log_title, log_line)
    item.path.write_text(text, encoding="utf-8", newline="\n")
    item.fields.update(updates)


def _reload(project: Project, cycle: Cycle) -> Cycle:
    return project.load_cycle(cycle.path, archived=cycle.archived)


def _commit(project: Project, cycle: Cycle, paths: list[Path], message: str) -> str:
    if not gitutil.is_repo(project.root):
        raise RiteError("not a git repository; bookkeeping needs git (use --no-commit to only write files)")
    existing = [p for p in dict.fromkeys(paths) if p.exists()]
    return gitutil.commit_paths(project.root, existing, message)


def _finish(project: Project, cycle: Cycle, item_paths: list[Path], message: str, commit: bool) -> dict:
    cycle = _reload(project, cycle)
    views.sync(project, cycle)
    paths = [*item_paths, cycle.progress_path, cycle.fixes_path]
    sha = _commit(project, cycle, paths, message) if commit else None
    return {"commit": sha, "message": message if commit else None,
            "files": [display(project.root, p) for p in paths if p.exists()]}


def _allocate(path_for_n, start: int) -> tuple[int, Path, int]:
    """Create the first free file atomically (O_EXCL). Returns (n, path, fd)."""
    n = start
    while True:
        path = path_for_n(n)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            return n, path, fd
        except FileExistsError:
            n += 1


def _max_n(items: list[Item]) -> int:
    return max((i.n for i in items), default=0)


# --- creation ----------------------------------------------------------------
def new_task(project: Project, cycle: Cycle, *, title: str, type_: str, phase, depends_on: list[str],
             source_of_truth: str, slug: str | None = None) -> Item:
    if not cycle.prefix:
        raise RiteError(f"cycle {cycle.name} has no 'prefix' in {display(project.root, cycle.progress_path)}")
    types = project.cfg["vocab"]["task_types"]
    if types and type_ not in types:
        raise RiteError(f"type {type_!r} not in [vocab].task_types {types}")
    index = cycle.by_id()
    for dep in depends_on:
        if dep not in index:
            raise RiteError(f"depends_on {dep} is not an item of cycle {cycle.name}")
    slug = slug or slugify(title)
    naming = project.naming
    n, path, fd = _allocate(lambda k: cycle.path / naming.task_file(cycle.prefix, k, slug), _max_n(cycle.tasks) + 1)
    item_id = naming.task_id(cycle.prefix, n)
    text = render(project, "task.md", {
        "id": item_id, "title": frontmatter.dump_value(title), "title_text": title,
        "type": frontmatter.dump_value(type_), "phase": frontmatter.dump_value(phase),
        "depends_on": frontmatter.dump_value(depends_on),
        "source_of_truth": frontmatter.dump_value(source_of_truth),
    })
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    views.sync(project, _reload(project, cycle))
    return project._load_item("task", path, n)


def new_fix(project: Project, cycle: Cycle, *, origin: str, title: str, severity: str,
            depends_on: list[str] | None = None, slug: str | None = None) -> Item:
    if severity not in SEVERITIES:
        raise RiteError(f"severity {severity!r}; expected one of {list(SEVERITIES)}")
    if not cycle.prefix:
        raise RiteError(f"cycle {cycle.name} has no 'prefix' in {display(project.root, cycle.progress_path)}")
    if origin not in cycle.by_id():
        raise RiteError(f"origin {origin} is not an item of cycle {cycle.name}")
    # fix numbers are unique per prefix across every cycle, archived ones included
    same_prefix = [f for c in project.all_cycles() if c.prefix == cycle.prefix for f in c.fixes]
    slug = slug or slugify(title)
    naming = project.naming
    n, path, fd = _allocate(lambda k: cycle.path / naming.fix_file(cycle.prefix, k, slug), _max_n(same_prefix) + 1)
    item_id = naming.fix_id(cycle.prefix, n)
    origin_item = cycle.by_id()[origin]
    text = render(project, "fix.md", {
        "id": item_id, "title": frontmatter.dump_value(title), "title_text": title,
        "origin": origin, "severity": severity,
        "depends_on": frontmatter.dump_value(depends_on or []),
        "origin_link": make_link(project.root, path, origin_item.path, project.cfg.link_style),
    })
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    views.sync(project, _reload(project, cycle))
    return project._load_item("fix", path, n)


def commit_new(project: Project, cycle: Cycle, item: Item) -> dict:
    """Commit a freshly created (and filled-in) item together with the regenerated views."""
    if item.status not in ("pending",):
        raise RiteError(f"{item.id} has status {item.status!r}; commit-new is for newly created items")
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, "open", item.id), True)
    return {"id": item.id, **result}


# --- status transitions ------------------------------------------------------
def close(project: Project, cycle: Cycle, item: Item, *, sha: str = "HEAD", commit: bool = True,
          force: bool = False) -> dict:
    """Record a finished item from its work commit, then commit the bookkeeping separately."""
    if item.status not in ("pending", "in-progress") and not force:
        raise RiteError(f"{item.id} has status {item.status!r}; only pending/in-progress items can be closed")
    if not gitutil.is_repo(project.root):
        raise RiteError("close needs git: done_on and the file list come from the work commit")
    full = gitutil.resolve(project.root, sha)
    if not full:
        raise RiteError(f"{sha!r} is not a commit")
    subj = gitutil.subject(project.root, full)
    if subj.startswith(BOOKKEEPING_PREFIXES) and not force:
        raise RiteError(f"{sha} is a bookkeeping commit ({subj!r}); pass the work commit with --sha")
    short = gitutil.short(project.root, full)
    date = gitutil.commit_date(project.root, full)
    files = gitutil.changed_files(project.root, full)
    updates = {"status": "done", "done_on": date, "done_commit": short}
    if item.kind == "task":
        updates["reviewed_on"] = "pending"
    log = [f"- **Closed** — commit `{short}` ({date}): {subj}",
           f"  - Files (`git show --name-status {short}`):"]
    log += [f"    - `{st} {p}`" for st, p in files] or ["    - *(none)*"]
    _write_item(item, updates, "\n".join(log), project.cfg["sections"]["execution_log"])
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, "close", item.id), commit)
    return {"id": item.id, "done_on": date, "done_commit": short, "work_subject": subj, **result}


def mark(project: Project, cycle: Cycle, item: Item, status: str, *, reason: str = "",
         commit: bool = False) -> dict:
    allowed = [s for s in (TASK_STATUSES if item.kind == "task" else FIX_STATUSES) if s not in ("done", "stale")]
    if status not in allowed:
        raise RiteError(f"mark accepts {allowed} for a {item.kind}; use 'close' for done"
                        + (" and 'mark-stale' for stale" if item.kind == "fix" else ""))
    today = dt.date.today().isoformat()
    log = f"- **{status}** ({today})" + (f": {reason}" if reason else "")
    _write_item(item, {"status": status}, log if (reason or status in ("blocked", "skipped")) else None,
                project.cfg["sections"]["execution_log"])
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, status, item.id), commit)
    return {"id": item.id, "status": status, **result}


def mark_reviewed(project: Project, cycle: Cycle, item: Item, *, fixes: list[str], commit: bool = True,
                  force: bool = False, date: str | None = None) -> dict:
    if item.kind != "task":
        raise RiteError("mark-reviewed applies to tasks")
    if (item.status != "done" or item.fields.get("reviewed_on") != "pending") and not force:
        raise RiteError(f"{item.id} is not awaiting review (status={item.status}, "
                        f"reviewed_on={item.fields.get('reviewed_on')})")
    index = cycle.by_id()
    fix_items = []
    for fid in fixes:
        if fid not in index or index[fid].kind != "fix":
            raise RiteError(f"{fid} is not a fix of cycle {cycle.name}")
        fix_items.append(index[fid])
    date = date or dt.date.today().isoformat()
    head = gitutil.short(project.root, "HEAD") if gitutil.is_repo(project.root) else None
    log = f"- **Reviewed** ({date}) at `{head}`: " + (", ".join(fixes) if fixes else "no finding")
    _write_item(item, {"reviewed_on": date, "review_commit": head}, log, project.cfg["sections"]["execution_log"])
    detail = f" ({len(fixes)} fix{'es' if len(fixes) != 1 else ''}: {', '.join(fixes)})" if fixes else " (no finding)"
    result = _finish(project, cycle, [item.path, *(f.path for f in fix_items)],
                     bookkeeping_message(project, "review", item.id, detail), commit)
    return {"id": item.id, "reviewed_on": date, "review_commit": head, "fixes": fixes, **result}


def mark_stale(project: Project, cycle: Cycle, item: Item, *, reason: str, commit: bool = True) -> dict:
    if item.kind != "fix":
        raise RiteError("mark-stale applies to fixes")
    if item.status not in ("pending", "in-progress"):
        raise RiteError(f"{item.id} has status {item.status!r}")
    if not reason.strip():
        raise RiteError("mark-stale needs --reason: what was measured and why the symptom is gone")
    today = dt.date.today().isoformat()
    head = gitutil.short(project.root, "HEAD") if gitutil.is_repo(project.root) else None
    _write_item(item, {"status": "stale", "done_on": today, "done_commit": head},
                f"- **Stale** ({today}) at `{head}`: {reason}", project.cfg["sections"]["execution_log"])
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, "stale", item.id), commit)
    return {"id": item.id, "status": "stale", **result}
