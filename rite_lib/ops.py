"""State-changing operations. The only code path allowed to write item status."""

from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

from . import frontmatter, gitutil, views
from .config import FIX_STATUSES, NO_COMMIT, SEVERITIES, TASK_STATUSES
from .markdown import append_to_section
from .model import Cycle, Item, Project, RiteError, display, make_link
from .naming import slugify

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BOOKKEEPING_PREFIXES = ("chore(rite):", "rite:")
# a ticket template may put the key before the subject ("PROJ-1 chore(rite): close ...")
_BOOKKEEPING_RE = re.compile(r"(?:^|\s)(?:chore\(rite\)|rite):\s")


def is_bookkeeping(subject: str) -> bool:
    return bool(_BOOKKEEPING_RE.search(subject))


# --- commit messages -----------------------------------------------------------
def commit_refs(project: Project, cycle: Cycle, item: Item | None = None) -> dict:
    """How a commit of this cycle names what it belongs to — the one place that decides it.

    A tracked cycle refers to the item (`Refs: <ID>`) so `git log --grep <ID>` finds its commits.
    A local cycle does not: its documents are not in the repository, so the ID would point nowhere.
    The cycle's ticket goes in every commit either way; the tracker lives outside the repository.
    """
    fmt = project.cfg["commit"]["ticket_format"]
    ticket = cycle.ticket
    trailers = [f"Refs: {item.id}"] if item and not cycle.local else []
    subject_template = "{subject}"
    if ticket:
        if "{subject}" in fmt:
            subject_template = fmt.replace("{ticket}", ticket)
        else:
            trailers.append(fmt.replace("{ticket}", ticket))
    return {"local": cycle.local, "ticket": ticket, "repo": item.repo if item else None,
            "subject_template": subject_template, "trailers": trailers}


def compose_message(refs: dict, subject: str, body: str = "") -> str:
    head = refs["subject_template"].replace("{subject}", subject)
    parts = [head, body.strip(), "\n".join(refs["trailers"])]
    return "\n\n".join(p for p in parts if p)


def bookkeeping_message(project: Project, verb: str, item_id: str, detail: str = "",
                        cycle: Cycle | None = None) -> str:
    head = "chore(rite):" if project.cfg["commit"]["style"] == "conventional" else "rite:"
    subject = f"{head} {verb} {item_id}{detail}"
    if cycle is None:
        return subject
    # the item ID is already in the subject; only the ticket is added
    return compose_message(commit_refs(project, cycle), subject)


def template_path(project: Project, name: str) -> Path:
    local = project.cfg["paths"]["templates_dir"]
    if local:
        candidate = project.root / local / name
        if candidate.is_file():
            return candidate
    return PLUGIN_ROOT / "templates" / name


def render(project: Project, name: str, values: dict) -> str:
    text = template_path(project, name).read_text(encoding="utf-8")
    values = {**{key: project.section_title(key) for key in project.cfg["sections"]}, **values}
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def _write_item(item: Item, updates: dict, log_line: str | None, log_titles: list[str]) -> None:
    text = item.path.read_text(encoding="utf-8")
    text = frontmatter.set_fields(text, updates)
    if log_line:
        text = append_to_section(text, log_titles, log_line)
    item.path.write_text(text, encoding="utf-8", newline="\n")
    item.fields.update(updates)


def _head(project: Project, item: Item) -> str | None:
    """HEAD of the repository the item's work lives in; None when there is none to read."""
    try:
        root = project.git_root(item)
    except RiteError:
        return None
    return gitutil.short(root, "HEAD") if gitutil.is_repo(root) else None


def _check_repo(project: Project, repo: str | None) -> str | None:
    repo = (repo or "").strip().strip("/") or None
    if repo and not project.is_git((project.root / repo).resolve()):
        raise RiteError(f"repo {repo!r} is not a git repository under {project.root} "
                        f"(repositories here: {', '.join(project.repos()) or 'none'})")
    return repo


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
    # a local cycle's documents are not in git (usually ignored, where `git add` would fail):
    # the state is written to the files and that is the whole record
    commit = commit and not cycle.local
    sha = _commit(project, cycle, paths, message) if commit else None
    return {"commit": sha, "message": message if commit else None, "local": cycle.local,
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
             source_of_truth: str, slug: str | None = None, repo: str | None = None) -> Item:
    if not cycle.prefix:
        raise RiteError(f"cycle {cycle.name} has no 'prefix' in {display(project.root, cycle.progress_path)}")
    types = project.cfg["vocab"]["task_types"]
    if types and type_ not in types:
        raise RiteError(f"type {type_!r} not in [vocab].task_types {types}")
    index = cycle.by_id()
    for dep in depends_on:
        if dep not in index:
            raise RiteError(f"depends_on {dep} is not an item of cycle {cycle.name}")
    repo = _check_repo(project, repo)
    if project.workspace and not repo:
        raise RiteError("rite.toml is outside git (a workspace): pass --repo, the repository the task's work "
                        f"lands in ({', '.join(project.repos()) or 'none found'})")
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
    if repo:
        text = frontmatter.set_fields(text, {"repo": repo})
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    views.sync(project, _reload(project, cycle))
    return project._load_item("task", path, n)


def new_fix(project: Project, cycle: Cycle, *, origin: str, title: str, severity: str,
            depends_on: list[str] | None = None, slug: str | None = None, repo: str | None = None) -> Item:
    if severity not in SEVERITIES:
        raise RiteError(f"severity {severity!r}; expected one of {list(SEVERITIES)}")
    if not cycle.prefix:
        raise RiteError(f"cycle {cycle.name} has no 'prefix' in {display(project.root, cycle.progress_path)}")
    if origin not in cycle.by_id():
        raise RiteError(f"origin {origin} is not an item of cycle {cycle.name}")
    repo = _check_repo(project, repo or cycle.by_id()[origin].repo)  # a fix defaults to its origin's repo
    if project.workspace and not repo:
        raise RiteError(f"rite.toml is outside git (a workspace) and {origin} names no repo: pass --repo")
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
    if repo:
        text = frontmatter.set_fields(text, {"repo": repo})
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    views.sync(project, _reload(project, cycle))
    return project._load_item("fix", path, n)


def commit_new(project: Project, cycle: Cycle, item: Item) -> dict:
    """Commit a freshly created (and filled-in) item together with the regenerated views."""
    if item.status not in ("pending",):
        raise RiteError(f"{item.id} has status {item.status!r}; commit-new is for newly created items")
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, "open", item.id, cycle=cycle), True)
    return {"id": item.id, **result}


# --- status transitions ------------------------------------------------------
def close(project: Project, cycle: Cycle, item: Item, *, sha: str | None = None, commit: bool = True,
          force: bool = False, no_repo: bool = False, reason: str = "") -> dict:
    """Record a finished item from its work commit, then commit the bookkeeping separately.

    With `no_repo` there is no work commit: the item's only artifact lives outside git (a workspace
    document). `done_commit` gets the NO_COMMIT sentinel and the reason goes in the Execution Log.
    """
    if item.status not in ("pending", "in-progress") and not force:
        raise RiteError(f"{item.id} has status {item.status!r}; only pending/in-progress items can be closed")
    if no_repo:
        return _close_without_commit(project, cycle, item, sha=sha, reason=reason, commit=commit)
    sha = sha or "HEAD"
    root = project.git_root(item)
    if not gitutil.is_repo(root):
        raise RiteError("close needs git: done_on and the file list come from the work commit")
    where = f" in {item.repo}" if item.repo else ""
    full = gitutil.resolve(root, sha)
    if not full:
        raise RiteError(f"{sha!r} is not a commit{where}")
    subj = gitutil.subject(root, full)
    if is_bookkeeping(subj) and not force:
        raise RiteError(f"{sha} is a bookkeeping commit ({subj!r}); pass the work commit with --sha")
    short = gitutil.short(root, full)
    date = gitutil.commit_date(root, full)
    files = gitutil.changed_files(root, full)
    updates = {"status": "done", "done_on": date, "done_commit": short}
    if item.kind == "task":
        updates["reviewed_on"] = "pending"
    git_c = f"git -C {item.repo}" if item.repo else "git"
    log = [f"- **Closed** — commit `{short}`{where} ({date}): {subj}",
           f"  - Files (`{git_c} show --name-status {short}`):"]
    log += [f"    - `{st} {p}`" for st, p in files] or ["    - *(none)*"]
    _write_item(item, updates, "\n".join(log), project.section_titles("execution_log"))
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, "close", item.id, cycle=cycle), commit)
    return {"id": item.id, "repo": item.repo, "done_on": date, "done_commit": short, "work_subject": subj,
            **result}


def _close_without_commit(project: Project, cycle: Cycle, item: Item, *, sha: str | None, reason: str,
                          commit: bool) -> dict:
    if sha:
        raise RiteError("--no-repo and --sha exclude each other: an item has a work commit or it has none")
    if not reason.strip():
        raise RiteError("close --no-repo needs --reason: what was done and where (which documents)")
    date = dt.date.today().isoformat()
    updates = {"status": "done", "done_on": date, "done_commit": NO_COMMIT}
    if item.kind == "task":
        updates["reviewed_on"] = "pending"
    _write_item(item, updates, f"- **Closed** — no work commit ({date}): {reason.strip()}",
                project.section_titles("execution_log"))
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, "close", item.id, cycle=cycle), commit)
    return {"id": item.id, "repo": item.repo, "done_on": date, "done_commit": NO_COMMIT, "work_subject": None,
            **result}


def mark(project: Project, cycle: Cycle, item: Item, status: str, *, reason: str = "",
         commit: bool = False) -> dict:
    allowed = [s for s in (TASK_STATUSES if item.kind == "task" else FIX_STATUSES) if s not in ("done", "stale")]
    if status not in allowed:
        raise RiteError(f"mark accepts {allowed} for a {item.kind}; use 'close' for done"
                        + (" and 'mark-stale' for stale" if item.kind == "fix" else ""))
    today = dt.date.today().isoformat()
    log = f"- **{status}** ({today})" + (f": {reason}" if reason else "")
    _write_item(item, {"status": status}, log if (reason or status in ("blocked", "skipped")) else None,
                project.section_titles("execution_log"))
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, status, item.id, cycle=cycle), commit)
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
    head = _head(project, item)
    log = f"- **Reviewed** ({date}) at `{head}`: " + (", ".join(fixes) if fixes else "no finding")
    _write_item(item, {"reviewed_on": date, "review_commit": head}, log,
                project.section_titles("execution_log"))
    detail = f" ({len(fixes)} fix{'es' if len(fixes) != 1 else ''}: {', '.join(fixes)})" if fixes else " (no finding)"
    result = _finish(project, cycle, [item.path, *(f.path for f in fix_items)],
                     bookkeeping_message(project, "review", item.id, detail, cycle=cycle), commit)
    return {"id": item.id, "reviewed_on": date, "review_commit": head, "fixes": fixes, **result}


def mark_stale(project: Project, cycle: Cycle, item: Item, *, reason: str, commit: bool = True) -> dict:
    if item.kind != "fix":
        raise RiteError("mark-stale applies to fixes")
    if item.status not in ("pending", "in-progress"):
        raise RiteError(f"{item.id} has status {item.status!r}")
    if not reason.strip():
        raise RiteError("mark-stale needs --reason: what was measured and why the symptom is gone")
    today = dt.date.today().isoformat()
    head = _head(project, item)
    _write_item(item, {"status": "stale", "done_on": today, "done_commit": head},
                f"- **Stale** ({today}) at `{head}`: {reason}", project.section_titles("execution_log"))
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, "stale", item.id, cycle=cycle), commit)
    return {"id": item.id, "status": "stale", **result}


def rebind(project: Project, cycle: Cycle, item: Item, *, sha: str, commit: bool = True) -> dict:
    """Point a closed item at its work commit again after a squash or rebase rewrote that commit.

    Only `done_commit` changes: the item stays done and its review state is kept. Why not close again:
    closing reopens the review and repeats the Execution Log entry for work that did not change.
    """
    if item.status not in ("done", "stale"):
        raise RiteError(f"{item.id} has status {item.status!r}; rebind is for done or stale items")
    root = project.git_root(item)
    if not gitutil.is_repo(root):
        raise RiteError("rebind needs git")
    full = gitutil.resolve(root, sha)
    if not full:
        raise RiteError(f"{sha!r} is not a commit" + (f" in {item.repo}" if item.repo else ""))
    subj = gitutil.subject(root, full)
    if is_bookkeeping(subj):
        raise RiteError(f"{sha} is a bookkeeping commit ({subj!r}); pass the work commit")
    old = item.fields.get("done_commit")
    short = gitutil.short(root, full)
    if str(old) == short:
        raise RiteError(f"{item.id} already points at {short}")
    today = dt.date.today().isoformat()
    _write_item(item, {"done_commit": short},
                f"- **Rebound** ({today}): done_commit `{old}` -> `{short}`: {subj}",
                project.section_titles("execution_log"))
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, "rebind", item.id, cycle=cycle),
                     commit)
    return {"id": item.id, "old_commit": old, "done_commit": short, "work_subject": subj, **result}
