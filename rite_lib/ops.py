"""State-changing operations. The only code path allowed to write item status (the cycle's JSON)."""

from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

from . import frontmatter, gitutil, markdown, state, views
from .config import FIX_STATUSES, NO_COMMIT, SEVERITIES, TASK_STATUSES
from .guard import glob_regex
from .markdown import append_to_section
from .model import Cycle, Item, Project, RiteError, display, make_link, resolve_link
from .naming import slugify

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BOOKKEEPING_PREFIXES = ("chore(rite):", "rite:")
# a ticket template may put the key before the subject ("PROJ-1 chore(rite): close ...")
_BOOKKEEPING_RE = re.compile(r"(?:^|\s)(?:chore\(rite\)|rite):\s")


def is_bookkeeping(subject: str) -> bool:
    return bool(_BOOKKEEPING_RE.search(subject))


# --- time spent ------------------------------------------------------------------
def now() -> str:
    """The current time as ISO 8601 with offset; `RITE_NOW` overrides it (tests)."""
    fixed = os.environ.get("RITE_NOW")
    if fixed:
        return dt.datetime.fromisoformat(fixed).isoformat(timespec="seconds")
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _seconds(start, end) -> int | None:
    try:
        return max(0, int((dt.datetime.fromisoformat(str(end)) - dt.datetime.fromisoformat(str(start)))
                          .total_seconds()))
    except (TypeError, ValueError):
        return None


def timing(item: Item, status: str, at: str) -> dict:
    """The time fields a move to ``status`` at ``at`` writes. Only the periods spent `in-progress`
    count: `active_since` opens one, leaving `in-progress` adds it to `active_s`. An item that never
    opened a period (one older than these fields) gets nothing invented."""
    f = item.fields
    updates: dict = {}
    if f.get("active_since") and status != "in-progress":
        spent = _seconds(f["active_since"], at)
        updates["active_s"] = int(f.get("active_s") or 0) + (spent or 0)
        updates["active_since"] = None
    elif status == "in-progress" and not f.get("active_since"):
        updates["active_since"] = at
        if not f.get("started_at"):
            updates["started_at"] = at
        if f.get("active_s") is None:
            updates["active_s"] = 0
    if status in ("done", "stale") and (f.get("active_since") or f.get("started_at")):
        updates["finished_at"] = at
    return updates


# --- commit messages -----------------------------------------------------------
def commit_refs(project: Project, cycle: Cycle, item: Item | None = None) -> dict:
    """How a commit of this cycle names what it belongs to — the one place that decides it.

    A tracked cycle refers to the item (`Refs: <ID>`) so `git log --grep <ID>` finds its commits.
    A local cycle does not: its documents are not in the repository, so the ID would point nowhere.
    The cycle's ticket goes in every commit either way; the tracker lives outside the repository.
    `co_author_footer` is not a trailer Rite writes: it tells the agent whether its own attribution stays.
    """
    fmt = project.cfg["commit"]["ticket_format"]
    ticket = cycle.ticket
    # a repository outside the root holds none of Rite's documents: the ID would point nowhere there
    external = bool(item) and project.is_external(item)
    trailers = [f"Refs: {item.id}"] if item and not cycle.local and not external else []
    subject_template = "{subject}"
    if ticket:
        if "{subject}" in fmt:
            subject_template = fmt.replace("{ticket}", ticket)
        else:
            trailers.append(fmt.replace("{ticket}", ticket))
    refs = {"local": cycle.local, "ticket": ticket, "repo": project.repo_of(item) if item else None,
            "subject_template": subject_template, "trailers": trailers,
            "co_author_footer": project.cfg["commit"]["co_author_footer"]}
    if project.multi_repo:
        refs["external"] = external
        if item or project.default_repo:  # a workspace root without a default is no repository
            refs["repo_dir"] = project.work_dir(item).as_posix()
    return refs


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
    """Set fields in the item's JSON entry; the Execution Log line goes in its markdown body."""
    try:
        state.update_item(item.state_path, item.kind, item.id, updates)
    except state.StateError as exc:
        raise RiteError(str(exc)) from exc
    if log_line:
        text = item.path.read_text(encoding="utf-8")
        item.path.write_text(append_to_section(text, log_titles, log_line), encoding="utf-8", newline="\n")
        item._md = None
    item.fields.update(updates)


# planning fields: what the model fills in after creating an item; every other field is the CLI's
PLANNING_FIELDS = ("files", "resources", "depends_on")
CYCLE_FIELDS = ("order", "ticket", "plan", "pitfalls")


def seed(text: str, item_id: str) -> tuple[dict, str]:
    """Split a rendered item template into (its frontmatter, the markdown to write).

    The template's frontmatter seeds the item's JSON entry — so a local template override may add its
    own keys — and the file keeps only its `id`: the JSON is the one place fields live.
    """
    fields, body = frontmatter.parse(text)
    return fields, f"---\nid: {frontmatter.dump_value(item_id)}\n---\n{body}"


def _entry(item_id: str, rel: str, fields: dict) -> dict:
    return {"id": item_id, "file": rel, **{k: v for k, v in fields.items() if k not in ("id", "file")}}


def _head(project: Project, item: Item) -> str | None:
    """HEAD of the repository the item's work lives in; None when there is none to read."""
    try:
        root = project.git_root(item)
    except RiteError:
        return None
    return gitutil.short(root, "HEAD") if gitutil.is_repo(root) else None


def _check_repo(project: Project, repo: str | None) -> str | None:
    """The repository a new item names, checked: the given one, else `[paths].default_repo` — written
    into the item, so changing the default later does not move the work an item already recorded."""
    repo = (repo or "").strip().strip("/") or project.default_repo
    if repo and not project.is_git(project.repo_dir(repo)):
        where = (f"{project.repo_map[repo]} ([repos].{repo})" if repo in project.repo_map
                 else f"under {project.root}")
        raise RiteError(f"repo {repo!r} is not a git repository {where} "
                        f"(repositories here: {', '.join(project.repo_names()) or 'none'})")
    return repo


def _reload(project: Project, cycle: Cycle) -> Cycle:
    return project.load_cycle(cycle.path, archived=cycle.archived)


def _commit(project: Project, cycle: Cycle, paths: list[Path], message: str, removed: list[Path] = ()) -> str:
    if not gitutil.is_repo(project.root):
        raise RiteError("not a git repository; bookkeeping needs git (use --no-commit to only write files)")
    existing = [p for p in dict.fromkeys(paths) if p.exists()]
    return gitutil.commit_paths(project.root, [*existing, *removed], message)


def _finish(project: Project, cycle: Cycle, item_paths: list[Path], message: str, commit: bool,
            removed: list[Path] = ()) -> dict:
    """Sync the views and commit. ``removed``: tracked files deleted on purpose, whose removal is staged."""
    cycle = _reload(project, cycle)
    views.sync(project, cycle)
    paths = [*item_paths, cycle.progress_state_path, cycle.fixes_state_path, cycle.progress_path, cycle.fixes_path]
    # a local cycle's documents are not in git (usually ignored, where `git add` would fail):
    # the state is written to the files and that is the whole record
    commit = commit and not cycle.local
    sha = _commit(project, cycle, paths, message, removed) if commit else None
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


def _max_n(items: list[Item], deleted_ids: list[str] = (), project: Project | None = None) -> int:
    """The highest number in use — deleted IDs included: a number is never handed out twice."""
    numbers = [i.n for i in items]
    for item_id in deleted_ids:
        parsed = project.naming.parse_id(item_id) if project else None
        if parsed and str(parsed[1].get("n") or "").isdigit():
            numbers.append(int(parsed[1]["n"]))
    return max(numbers, default=0)


def _deleted_ids(cycles: list[Cycle], kind: str) -> list[str]:
    return [str(d.get("id")) for c in cycles for d in c.deleted
            if isinstance(d, dict) and d.get("kind", "task") == kind]


# --- creation ----------------------------------------------------------------
def new_task(project: Project, cycle: Cycle, *, title: str, type_: str, phase, depends_on: list[str],
             source_of_truth: str, slug: str | None = None, repo: str | None = None) -> Item:
    if not cycle.prefix:
        raise RiteError(f"cycle {cycle.name} has no 'prefix' in {display(project.root, cycle.progress_path)}")
    types = project.cfg["vocab"]["task_types"]
    if types and type_ not in types:
        raise RiteError(f"type {type_!r} not in [vocab].task_types {types}")
    _check_depends(cycle, None, depends_on)
    repo = _check_repo(project, repo)
    if project.workspace and not repo:
        raise RiteError("rite.toml is outside git (a workspace): pass --repo, the repository the task's work "
                        f"lands in ({', '.join(project.repo_names()) or 'none found'})")
    slug = slug or slugify(title)
    naming = project.naming
    n, path, fd = _allocate(lambda k: cycle.path / naming.task_file(cycle.prefix, k, slug), _max_n(cycle.tasks, _deleted_ids([cycle], "task"), project) + 1)
    item_id = naming.task_id(cycle.prefix, n)
    rendered = render(project, "task.md", {
        "id": item_id, "title": frontmatter.dump_value(title), "title_text": title,
        "type": frontmatter.dump_value(type_), "phase": frontmatter.dump_value(phase),
        "depends_on": frontmatter.dump_value(depends_on),
        "source_of_truth": frontmatter.dump_value(source_of_truth),
    })
    return _create(project, cycle, "task", item_id, path, fd, rendered, repo)


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
    prefixed = [c for c in project.all_cycles() if c.prefix == cycle.prefix]
    same_prefix = [f for c in prefixed for f in c.fixes]
    slug = slug or slugify(title)
    naming = project.naming
    n, path, fd = _allocate(lambda k: cycle.path / naming.fix_file(cycle.prefix, k, slug), _max_n(same_prefix, _deleted_ids(prefixed, "fix"), project) + 1)
    item_id = naming.fix_id(cycle.prefix, n)
    origin_item = cycle.by_id()[origin]
    rendered = render(project, "fix.md", {
        "id": item_id, "title": frontmatter.dump_value(title), "title_text": title,
        "origin": origin, "severity": severity,
        "depends_on": frontmatter.dump_value(depends_on or []),
        "origin_link": make_link(project.root, path, origin_item.path, project.cfg.link_style),
    })
    return _create(project, cycle, "fix", item_id, path, fd, rendered, repo)


def _create(project: Project, cycle: Cycle, kind: str, item_id: str, path: Path, fd: int, rendered: str,
            repo: str | None) -> Item:
    """Write the item's markdown (taken by `_allocate`) and add its entry to the cycle's JSON."""
    try:
        fields, text = seed(rendered, item_id)
    except frontmatter.FrontmatterError as exc:
        os.close(fd)
        path.unlink()
        raise RiteError(f"template for a {kind}: {exc}") from exc
    if repo:
        fields["repo"] = repo
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    state_path = cycle.progress_state_path if kind == "task" else cycle.fixes_state_path
    default = state.new_progress(cycle.meta) if kind == "task" else state.new_fixes(cycle.name)
    try:
        state.add_item(state_path, kind, _entry(item_id, path.relative_to(cycle.path).as_posix(), fields), default)
    except state.StateError as exc:
        path.unlink()
        raise RiteError(str(exc)) from exc
    cycle = _reload(project, cycle)
    views.sync(project, cycle)
    return cycle.by_id()[item_id]


def commit_new(project: Project, cycle: Cycle, item: Item) -> dict:
    """Commit a freshly created (and filled-in) item together with the regenerated views."""
    if item.status not in ("pending",):
        raise RiteError(f"{item.id} has status {item.status!r}; commit-new is for newly created items")
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, "open", item.id, cycle=cycle), True)
    return {"id": item.id, **result}


def _check_depends(cycle: Cycle, item: Item | None, deps: list[str]) -> None:
    """Dependencies stay inside the cycle and the graph stays acyclic. ``item`` is None for an item
    being created: nothing depends on it yet, so it cannot close a loop."""
    index = cycle.by_id()
    for dep in deps:
        if item is not None and dep == item.id:
            raise RiteError(f"{item.id} cannot depend on itself")
        if dep not in index:
            raise RiteError(f"depends_on {dep} is not an item of cycle {cycle.name}")
    if item is None:
        return
    graph = {i.id: i.depends_on for i in cycle.items}
    graph[item.id] = deps
    trail: list[str] = []
    cleared: set[str] = set()  # explored without reaching the item

    def visit(node: str) -> None:
        if node == item.id and trail:
            raise RiteError("depends_on would close a dependency cycle: " + " -> ".join([*trail, node]))
        if node in trail or node in cleared:
            return
        trail.append(node)
        for dep in graph.get(node, []):
            visit(dep)
        trail.pop()
        cleared.add(node)

    visit(item.id)


def set_fields(project: Project, cycle: Cycle, item: Item, updates: dict) -> dict:
    """Set an item's planning fields (`files`, `resources`, `depends_on`) — the only fields the model
    writes. `depends_on` grows as a phase does: a closing task covers tasks added after it."""
    bad = [k for k in updates if k not in PLANNING_FIELDS]
    if bad:
        raise RiteError(f"rite set writes {list(PLANNING_FIELDS)} only; {', '.join(bad)} "
                        "belongs to the CLI (close, mark, mark-reviewed, mark-stale, rebind)")
    for key, value in updates.items():
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise RiteError(f"{key} must be a list of strings")
    if "depends_on" in updates:
        if item.status in ("done", "stale"):
            raise RiteError(f"{item.id} is {item.status}: its dependencies were the order it ran in")
        _check_depends(cycle, item, updates["depends_on"])
    _write_item(item, updates, None, [])
    views.sync(project, _reload(project, cycle))
    return {"id": item.id, **updates, "file": display(project.root, item.state_path)}


def repo_file(project: Project, path: str, what: str) -> Path:
    """An existing file inside the repository, named repo-relative or root-absolute."""
    target, _ = resolve_link(project.root, project.root / "x", "/" + path.strip().lstrip("/"))
    if not target.is_file():
        raise RiteError(f"{what} {path} not found in the repository")
    return target


def set_cycle(project: Project, cycle: Cycle, updates: dict) -> dict:
    """Set the cycle's `order`, `ticket`, `plan` or `pitfalls`."""
    bad = [k for k in updates if k not in CYCLE_FIELDS]
    if bad:
        raise RiteError(f"rite set-cycle writes {list(CYCLE_FIELDS)} only, not {', '.join(bad)}")
    if "order" in updates:
        tasks = {t.id for t in cycle.tasks}
        order = updates["order"]
        unknown = [i for i in order if i not in tasks]
        if unknown:
            raise RiteError(f"order lists {', '.join(unknown)}, not tasks of cycle {cycle.name}")
        if len(set(order)) != len(order):
            raise RiteError("order lists a task twice")
    if updates.get("pitfalls"):
        updates["pitfalls"] = make_link(project.root, cycle.progress_path,
                                        repo_file(project, updates["pitfalls"], "pitfalls file"),
                                        project.cfg.link_style)
    try:
        state.update_meta(cycle.progress_state_path, updates)
    except state.StateError as exc:
        raise RiteError(str(exc)) from exc
    views.sync(project, _reload(project, cycle))
    return {"cycle": cycle.name, **updates, "file": display(project.root, cycle.progress_state_path)}


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
    where = f" in {project.repo_of(item)}" if project.repo_of(item) else ""
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
    # the work commit ends the work: in a batch the `finish` calls come later, one after another
    at = gitutil.commit_time(root, full)
    if item.fields.get("active_since") and (_seconds(item.fields["active_since"], at) or 0) <= 0:
        at = now()  # a commit older than the period (a rebind, a clock skew) cannot end it
    updates.update(timing(item, "done", at))
    if item.kind == "task":
        updates["reviewed_on"] = "pending"
    label = project.repo_label(item)
    git_c = f"git -C {label}" if label else "git"
    log = [f"- **Closed** — commit `{short}`{where} ({date}): {subj}",
           f"  - Files (`{git_c} show --name-status {short}`):"]
    log += [f"    - `{st} {p}`" for st, p in files] or ["    - *(none)*"]
    declared = _declared_files(item)
    # the item's document and the cycle's state and views: what Rite itself writes during the work
    exempt = {display(root, p) for p in (item.path, cycle.progress_state_path, cycle.fixes_state_path,
                                         cycle.progress_path, cycle.fixes_path)}
    outside = _outside_declared(declared, files, exempt) if declared else []
    if outside:
        log.append(f"  - **Outside declared files** ({', '.join(f'`{d}`' for d in declared)}):")
        log += [f"    - `{p}`" for p in outside]
    _write_item(item, updates, "\n".join(log), project.section_titles("execution_log"))
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, "close", item.id, cycle=cycle), commit)
    return {"id": item.id, "repo": project.repo_of(item), "done_on": date, "done_commit": short, "work_subject": subj,
            "outside_files": outside, **result}


def _declared_files(item: Item) -> list[str]:
    value = item.fields.get("files")
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _outside_declared(declared: list[str], files: list[tuple[str, str]], exempt: set[str]) -> list[str]:
    """Paths of the work commit that no declared `files` entry covers — a warning, never a refusal:
    the scope was a prediction, and the review judges whether leaving it was right. A rename counts by
    its new path; an ``exempt`` path (the item's document, the files Rite writes) is never outside."""
    patterns = [d.strip().removeprefix("./").lstrip("/") for d in declared if d.strip()]
    outside = []
    for _, path in files:
        path = path.split(" -> ")[-1]
        if path in exempt:
            continue
        if not any(path == d or path.startswith(d.rstrip("/") + "/") or glob_regex(d).fullmatch(path)
                   for d in patterns):
            outside.append(path)
    return outside


def _close_without_commit(project: Project, cycle: Cycle, item: Item, *, sha: str | None, reason: str,
                          commit: bool) -> dict:
    if sha:
        raise RiteError("--no-repo and --sha exclude each other: an item has a work commit or it has none")
    if not reason.strip():
        raise RiteError("close --no-repo needs --reason: what was done and where (which documents)")
    date = dt.date.today().isoformat()
    updates = {"status": "done", "done_on": date, "done_commit": NO_COMMIT, **timing(item, "done", now())}
    if item.kind == "task":
        updates["reviewed_on"] = "pending"
    _write_item(item, updates, f"- **Closed** — no work commit ({date}): {reason.strip()}",
                project.section_titles("execution_log"))
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, "close", item.id, cycle=cycle), commit)
    return {"id": item.id, "repo": project.repo_of(item), "done_on": date, "done_commit": NO_COMMIT,
            "work_subject": None, **result}


def mark(project: Project, cycle: Cycle, item: Item, status: str, *, reason: str = "",
         unblocked_by: str = "", commit: bool = False) -> dict:
    """Set a status `close` and `mark-stale` do not. A blocked task waits on another task, which Rite
    re-evaluates by itself; a blocked fix waits on the environment, which Rite does not know — so it
    names the command that passes once the environment is there, and `reproduce` runs it."""
    allowed = [s for s in (TASK_STATUSES if item.kind == "task" else FIX_STATUSES) if s not in ("done", "stale")]
    if status not in allowed:
        raise RiteError(f"mark accepts {allowed} for a {item.kind}; use 'close' for done"
                        + (" and 'mark-stale' for stale" if item.kind == "fix" else ""))
    unblocked_by = unblocked_by.strip()
    blocked_fix = item.kind == "fix" and status == "blocked"
    if unblocked_by and not blocked_fix:
        raise RiteError("--unblocked-by applies to a fix marked blocked")
    if blocked_fix and not unblocked_by:
        raise RiteError('a blocked fix needs --unblocked-by "<command>": the command that passes once the '
                        "environment is there. A block with no exit test is a lost item: nothing re-checks it")
    if blocked_fix and not reason.strip():
        raise RiteError("a blocked fix needs --reason: what is missing, and the SHA of any partial work")
    updates: dict = {"status": status, **timing(item, status, now())}
    if blocked_fix:
        updates["unblocked_by"] = unblocked_by
    elif item.kind == "fix" and item.fields.get("unblocked_by") is not None:
        updates["unblocked_by"] = None  # leaving the block: its exit test goes with it
    today = dt.date.today().isoformat()
    log = f"- **{status}** ({today})" + (f": {reason}" if reason else "")
    if blocked_fix:
        log += f" — unblocked by `{unblocked_by}`"
    _write_item(item, updates, log if (reason or status in ("blocked", "skipped")) else None,
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
    updates = {"reviewed_on": date, "review_commit": head}
    spent = _seconds(item.fields.get("review_started_at"), now())
    if spent is not None:
        updates["review_s"] = spent
    _write_item(item, updates, log, project.section_titles("execution_log"))
    detail = f" ({len(fixes)} fix{'es' if len(fixes) != 1 else ''}: {', '.join(fixes)})" if fixes else " (no finding)"
    result = _finish(project, cycle, [item.path, *(f.path for f in fix_items)],
                     bookkeeping_message(project, "review", item.id, detail, cycle=cycle), commit)
    return {"id": item.id, "reviewed_on": date, "review_commit": head, "fixes": fixes,
            "review_s": updates.get("review_s"), **result}


def mark_review_started(project: Project, cycle: Cycle, item: Item) -> str:
    """Open a review of a task: its latest attempt is what `review_s` measures, because an interrupted
    review is redone from scratch by a fresh agent. Writes the JSON and the views; commits nothing."""
    at = now()
    _write_item(item, {"review_started_at": at}, None, project.section_titles("execution_log"))
    views.sync(project, _reload(project, cycle))
    return at


def mark_stale(project: Project, cycle: Cycle, item: Item, *, reason: str, commit: bool = True) -> dict:
    if item.kind != "fix":
        raise RiteError("mark-stale applies to fixes")
    if item.status == "blocked":
        raise RiteError(f"{item.id} is blocked: stale needs the symptom measured, and its environment is "
                        f"missing — once `{item.fields.get('unblocked_by')}` passes, mark it pending and reproduce")
    if item.status not in ("pending", "in-progress"):
        raise RiteError(f"{item.id} has status {item.status!r}")
    if not reason.strip():
        raise RiteError("mark-stale needs --reason: what was measured and why the symptom is gone")
    today = dt.date.today().isoformat()
    head = _head(project, item)
    _write_item(item, {"status": "stale", "done_on": today, "done_commit": head, **timing(item, "stale", now())},
                f"- **Stale** ({today}) at `{head}`: {reason}", project.section_titles("execution_log"))
    result = _finish(project, cycle, [item.path], bookkeeping_message(project, "stale", item.id, cycle=cycle), commit)
    return {"id": item.id, "status": "stale", **result}


DELETABLE = ("pending", "blocked", "skipped")


def _outside_views(text: str) -> str:
    """The text with each generated region blanked, line numbers kept: the views re-render without
    the item, so their links are not the user's to rewrite."""
    out, inside = [], False
    for line in text.split("\n"):
        if line.strip().startswith("<!-- rite:begin "):
            inside = True
        out.append("" if inside else line)
        if inside and line.strip() == "<!-- rite:end -->":
            inside = False
    return "\n".join(out)


def _inbound_links(project: Project, cycle: Cycle, item: Item) -> list[str]:
    """`path:line` of every markdown link to the item's file from the cycle's documents, its profile,
    pitfalls and plan: prose the user rewrites, never Rite."""
    files = [p for p in sorted(cycle.path.rglob("*.md")) if p != item.path]
    files += [cycle.profile_path, cycle.pitfalls_path]
    if cycle.meta.get("plan"):
        files.append(resolve_link(project.root, cycle.progress_path, str(cycle.meta["plan"]))[0])
    target = item.path.resolve()
    found = []
    for path in dict.fromkeys(files):
        if not path.is_file():
            continue
        for line, link in markdown.links(_outside_views(path.read_text(encoding="utf-8"))):
            if markdown.is_external(link):
                continue
            if resolve_link(project.root, path, link)[0] == target:
                found.append(f"{display(project.root, path)}:{line}")
    return found


def delete_item(project: Project, cycle: Cycle, item: Item, *, reason: str, detach: bool = False,
                dry_run: bool = False, commit: bool = True) -> dict:
    """Remove an item created by mistake: its file, its entry, and — with `detach` — its place in other
    items' `depends_on`. Only an item never worked on: one with a work commit has a history, and giving
    it up is `mark skipped` (task) or `mark-stale` (fix). Its ID is kept under `deleted`."""
    if item.status not in DELETABLE or item.fields.get("done_commit"):
        way_out = "mark it skipped" if item.kind == "task" else "mark-stale it"
        raise RiteError(f"{item.id} has status {item.status!r}: only items never worked on ({', '.join(DELETABLE)}) "
                        f"are deleted; to give it up, {way_out}")
    origins = [f.id for f in cycle.fixes if str(f.fields.get("origin")) == item.id]
    dependents = [i.id for i in cycle.items if i.id != item.id and item.id in i.depends_on]
    links = _inbound_links(project, cycle, item)
    blockers = ([f"{fid} has origin {item.id}: delete that fix first" for fid in origins]
                + ([] if detach else [f"{d} depends_on {item.id}: pass --detach to drop it" for d in dependents])
                + [f"{where} links to {display(project.root, item.path)}: rewrite that link" for where in links])
    in_order = item.id in (cycle.meta.get("order") or [])
    result = {"id": item.id, "kind": item.kind, "title": item.title, "status": item.status,
              "file": display(project.root, item.path), "blockers": blockers,
              "detach": dependents, "order": in_order}
    if dry_run:
        return {**result, "eligible": not blockers}
    if blockers:
        raise RiteError(f"{item.id} cannot be deleted:\n  " + "\n  ".join(blockers))
    if not reason.strip():
        raise RiteError("delete needs --reason: why the item should not exist (a duplicate, created by mistake)")
    index = cycle.by_id()
    for dep_id in dependents:
        dep = index[dep_id]
        _write_item(dep, {"depends_on": [d for d in dep.depends_on if d != item.id]}, None, [])
    if in_order:
        state.update_meta(cycle.progress_state_path,
                          {"order": [i for i in cycle.meta["order"] if i != item.id]})
    today = dt.date.today().isoformat()
    tombstone = {"id": item.id, "kind": item.kind, "title": item.title, "reason": reason.strip(),
                 "deleted_on": today}
    try:
        state.remove_item(item.state_path, item.kind, item.id, tombstone)
    except state.StateError as exc:
        raise RiteError(str(exc)) from exc
    root = project.root
    tracked = gitutil.is_repo(root) and gitutil.is_tracked(root, item.path)
    item.path.unlink()
    touched = [index[d].path for d in dependents]
    message = bookkeeping_message(project, "delete", item.id, f" ({reason.strip()})", cycle=cycle)
    res = _finish(project, cycle, touched, message, commit, removed=[item.path] if tracked else [])
    return {**result, "deleted_on": today, "reason": reason.strip(), **res}


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
        raise RiteError(f"{sha!r} is not a commit" + (f" in {project.repo_of(item)}" if project.repo_of(item) else ""))
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
