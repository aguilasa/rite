"""Cycle lifecycle: create a cycle, check it can close, archive it (with link rewriting)."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from . import frontmatter, gitutil, markdown, state, views
from .config import OPEN_FIX_STATUSES
from .model import Cycle, Project, RiteError, display, make_link, resolve_link
from .ops import bookkeeping_message, render, repo_file

LINK_FIELDS = ("source_of_truth", "plan", "profile", "pitfalls")
# a link field in the JSON resolves from the markdown it describes: the progress file for the cycle's
# meta, the item's own file for an item — the same anchors it had as frontmatter
META_LINK_FIELDS = ("plan", "profile", "pitfalls")
_PREFIX_RE = re.compile(r"^[A-Za-z0-9]+$")


# --- new cycle -----------------------------------------------------------------
def new_cycle(project: Project, name: str, prefix: str, *, plan: str | None = None,
              ticket: str | None = None, local: bool = False, commit: bool = False,
              copy_plan: bool = False, pitfalls_from: str | None = None) -> dict:
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", name):
        raise RiteError(f"cycle name {name!r}: use letters, digits, '.', '_' or '-'")
    if not _PREFIX_RE.match(prefix):
        raise RiteError(f"prefix {prefix!r}: letters and digits only")
    if project.is_cycle_dir(project.cycles_root):
        raise RiteError(f"{display(project.root, project.cycles_root)} is a flat single cycle; "
                        "new cycles need cycles_root to be a folder of cycles")
    path = project.cycles_root / name
    if path.exists():
        raise RiteError(f"{display(project.root, path)} already exists")
    for c in project.live_cycles():
        if c.prefix == prefix:
            raise RiteError(f"prefix {prefix} is used by live cycle {c.name}")
    if copy_plan and not plan:
        raise RiteError("--copy-plan needs --plan")
    plan_link, plan_path, copy_from, copied_from = "", None, None, None
    if plan:
        source = _plan_source(project, plan)
        plan_path = source
        if copy_plan:
            plans_dir = project.cfg.path("plans_dir")
            target = plans_dir / source.name
            if source != target.resolve():
                if not target.exists():
                    copy_from = source
                elif target.read_bytes() != source.read_bytes():
                    raise RiteError(f"{display(project.root, target)} already exists and differs from {source}; "
                                    "rename one of them")
                copied_from, plan_path = plan, target
        elif not _inside(project.root, source):
            raise RiteError(f"plan {plan} is outside the repository; pass --copy-plan to copy it into "
                            f"{display(project.root, project.cfg.path('plans_dir'))}")
        plan_link = make_link(project.root, path / project.progress_name, plan_path, project.cfg.link_style)

    pitfalls_source = _pitfalls_source(project, pitfalls_from) if pitfalls_from else None
    naming = project.cfg["naming"]
    profiles = project.cfg.path("profiles_dir")
    profile = profiles / naming["profile_file"].format(cycle=name)
    pitfalls = profiles / naming["pitfalls_file"].format(cycle=name)
    values = {"cycle": name, "prefix": prefix, "plan": frontmatter.dump_value(plan_link or None)}
    created = []
    if copy_from:
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(copy_from, plan_path)
        created.append(plan_path)
    path.mkdir(parents=True)
    for tpl, dest in (("progress.md", path / project.progress_name), ("fixes.md", path / project.fixes_name),
                      ("profile.md", profile), ("pitfalls.md", pitfalls)):
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = render(project, tpl, values)
        if tpl == "profile.md":
            # a local template override may predate the {{phase_checks}} placeholder
            text = text.replace("## Phase-specific checks", "## " + project.section_title("phase_checks"))
        if tpl == "pitfalls.md" and pitfalls_source:
            text = pitfalls_source.read_text(encoding="utf-8")
        if tpl == "progress.md":
            text = text.replace("## Dependency graph", "## " + project.section_title("dependency_graph"))
            # the template's frontmatter seeds progress.json; ticket and local are set, not templated:
            # a local template override may predate these keys
            meta, body = frontmatter.parse(text)
            meta = {**meta, "ticket": ticket or None, "local": bool(local)}
            state.write(path / project.progress_state, state.new_progress(meta))
            created.append(path / project.progress_state)
            text = body.lstrip("\n")
        elif tpl == "fixes.md":
            state.write(path / project.fixes_state, state.new_fixes(name))
            created.append(path / project.fixes_state)
        dest.write_text(text, encoding="utf-8", newline="\n")
        created.append(dest)
    cycle = project.load_cycle(path)
    views.sync(project, cycle)
    sha = None
    if commit and not cycle.local:
        sha = gitutil.commit_paths(project.root, created,
                                   bookkeeping_message(project, "new cycle", name, cycle=cycle))
    local_paths = [path, profile, pitfalls] + ([plan_path] if copy_from else [])
    return {"cycle": name, "prefix": prefix, "path": display(project.root, path), "ticket": cycle.ticket,
            "local": cycle.local, "plan": display(project.root, plan_path) if plan_path else None,
            "plan_copied_from": copied_from,
            "pitfalls_copied_from": display(project.root, pitfalls_source) if pitfalls_source else None,
            "created": [display(project.root, p) for p in created], "commit": sha,
            "ignored": _ignored(project, local_paths) if cycle.local else None}


def _pitfalls_source(project: Project, source: str) -> Path:
    """The pitfalls file a new cycle starts from: a cycle's (live or archived, by name or folder), else
    a file in the repository. What a retro kept lands in the closed cycle's file; this carries it on."""
    try:
        cycle = project.resolve_cycle(source)
    except RiteError:
        return repo_file(project, source, "--pitfalls-from:")
    if not cycle.pitfalls_path.is_file():
        raise RiteError(f"--pitfalls-from: cycle {cycle.name} has no pitfalls file "
                        f"({display(project.root, cycle.pitfalls_path)})")
    return cycle.pitfalls_path


def _plan_source(project: Project, plan: str) -> Path:
    """The plan file ``--plan`` names: repo-relative, root-absolute (``/docs/x.md``) or OS-absolute.

    A leading ``/`` is ambiguous on POSIX, where it is also OS-absolute: the repo file wins when it
    exists, so ``/docs/plans/x.md`` keeps meaning the plan inside the repository.
    """
    p = Path(plan).expanduser()
    in_repo = (project.root / plan.lstrip("/")).resolve()
    if p.is_absolute() and not (plan.startswith("/") and in_repo.is_file()):
        source = p.resolve()
    else:
        source, _ = resolve_link(project.root, project.root / "x", "/" + plan.lstrip("/"))
    if not source.is_file():
        raise RiteError(f"plan {plan} not found")
    return source


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def publish(project: Project, cycle: Cycle) -> dict:
    """Turn a local cycle into a tracked one: `local: false` and one commit with its documents."""
    if project.workspace:
        raise RiteError("rite.toml is outside git (a workspace): there is no repository to publish the cycle to")
    if not cycle.local:
        raise RiteError(f"cycle {cycle.name} is not local")
    paths = [p for p in (cycle.path, cycle.profile_path, cycle.pitfalls_path) if p.exists()]
    ignored = [display(project.root, p) for p in paths if gitutil.is_ignored(project.root, p)]
    if ignored:
        raise RiteError("still ignored by git: " + ", ".join(ignored)
                        + "; remove the matching lines from .gitignore first (git check-ignore -v <path>)")
    if gitutil.run(project.root, "diff", "--cached", "--name-only").strip():
        raise RiteError("the index has staged changes; commit or unstage them first")
    state.update_meta(cycle.progress_state_path, {"local": False})
    cycle = project.load_cycle(cycle.path, archived=cycle.archived)
    views.sync(project, cycle)
    sha = gitutil.commit_paths(project.root, paths,
                               bookkeeping_message(project, "publish cycle", cycle.name, cycle=cycle))
    return {"cycle": cycle.name, "commit": sha, "files": [display(project.root, p) for p in paths]}


def _ignored(project: Project, paths: list[Path]) -> dict[str, bool]:
    """Which of ``paths`` git ignores. A local cycle's documents should all be ignored."""
    if not gitutil.is_repo(project.root):
        return {}
    return {display(project.root, p): gitutil.is_ignored(project.root, p) for p in paths}


# --- close / archive -----------------------------------------------------------
def blockers(project: Project, cycle: Cycle) -> list[str]:
    out = []
    if cycle.archived:
        out.append("cycle is already archived")
    if not cycle.tasks:
        out.append("cycle has no tasks")
    for t in cycle.tasks:
        if t.status not in ("done", "skipped"):
            out.append(f"{t.id} is {t.status}")
        elif t.status == "done" and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(t.fields.get("reviewed_on") or "")):
            out.append(f"{t.id} is not reviewed (reviewed_on={t.fields.get('reviewed_on')})")
    for f in cycle.fixes:
        if f.status == "blocked":  # waiting is still open: a cycle does not close over it
            out.append(f"{f.id} is blocked ({f.fields.get('severity')}) until "
                       f"`{f.fields.get('unblocked_by')}` passes")
        elif f.status in OPEN_FIX_STATUSES:
            out.append(f"{f.id} is open ({f.fields.get('severity')})")
    if views.out_of_sync(project, cycle):
        out.append("views out of sync (rite.py sync)")
    return out


def _md_files(root: Path) -> list[Path]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", ".venv", "__pycache__")]
        files += [Path(dirpath) / f for f in filenames if f.endswith(".md")]
    return files


def _rewrite_target(project: Project, target: str, old_file: Path, new_file: Path, old_dir: Path,
                    new_dir: Path) -> str:
    """A link target written in ``old_file``, as it must read from ``new_file`` once ``old_dir`` moved."""
    if markdown.is_external(target) or target.startswith("#"):
        return target
    path, anchor = resolve_link(project.root, old_file, target)
    try:
        new_target_path = new_dir / path.relative_to(old_dir)
    except ValueError:
        new_target_path = path
    if new_target_path == path and new_file == old_file:
        return target
    if target.startswith("/") and new_target_path == path:
        return target  # root-absolute link to something that did not move
    link = make_link(project.root, new_file, new_target_path,
                     "root-absolute" if target.startswith("/") else "relative")
    return link + (f"#{anchor}" if anchor else "")


def _rewrite(project: Project, text: str, old_file: Path, new_file: Path, old_dir: Path, new_dir: Path) -> str:
    """Rewrite link targets (prose links and link fields) so they resolve after the move."""
    return _map_links(text, lambda t: _rewrite_target(project, t, old_file, new_file, old_dir, new_dir))


def _map_links(text: str, fix_target) -> str:
    """Apply ``fix_target`` to every prose link target and link field, skipping code blocks."""
    lines = text.split("\n")
    prose = {n - 1 for n, _ in markdown.prose_lines(text)}
    link_re = re.compile(r"(?<!!)(\[(?:[^\]\\]|\\.)*\]\(\s*<?)([^)\s>]+)")
    for i, line in enumerate(lines):
        if i in prose:
            lines[i] = link_re.sub(lambda m: m.group(1) + fix_target(m.group(2)), line)
    text = "\n".join(lines)
    try:
        fields, _ = frontmatter.parse(text)
    except frontmatter.FrontmatterError:
        return text
    updates = {}
    for k in LINK_FIELDS:
        if isinstance(fields.get(k), str) and fields[k]:
            new = fix_target(fields[k])
            if new != fields[k]:
                updates[k] = new
    return frontmatter.set_fields(text, updates) if updates else text


def relink(project: Project, cycles: list[Cycle], *, write: bool) -> list[dict]:
    """Rewrite links in cycle files and profiles to [paths].link_style; targets that do not exist stay."""
    style = project.cfg.link_style
    changes = []
    files: list[Path] = []
    for c in cycles:
        files += [c.progress_path, c.fixes_path, c.profile_path, c.pitfalls_path, *(i.path for i in c.items)]
    for f in dict.fromkeys(p for p in files if p.is_file()):
        count = 0

        def fix_target(target: str, f=f) -> str:
            nonlocal count
            if markdown.is_external(target) or target.startswith("#"):
                return target
            path, anchor = resolve_link(project.root, f, target)
            if not path.exists():
                return target
            new = make_link(project.root, f, path, style) + (f"#{anchor}" if anchor else "")
            if new != target:
                count += 1
            return new

        text = f.read_text(encoding="utf-8")
        new_text = _map_links(text, fix_target)
        if new_text != text:
            changes.append({"file": display(project.root, f), "links": count})
            if write:
                f.write_text(new_text, encoding="utf-8", newline="\n")
    for c in cycles:
        for path in (c.progress_state_path, c.fixes_state_path):
            if not path.is_file():
                continue
            count = 0

            def fix_field(target: str, md: Path) -> str:
                nonlocal count
                if markdown.is_external(target) or target.startswith("#"):
                    return target
                resolved, anchor = resolve_link(project.root, md, target)
                if not resolved.exists():
                    return target
                new = make_link(project.root, md, resolved, style) + (f"#{anchor}" if anchor else "")
                count += new != target
                return new

            data = state.read(path)
            if _map_state_links(project, data, c.path, c.path, fix_field):
                changes.append({"file": display(project.root, path), "links": count})
                if write:
                    state.write(path, data)
    return changes


def _map_state_links(project: Project, data: dict, old_dir: Path, new_dir: Path, fix_field) -> bool:
    """Apply ``fix_field(target, markdown_file)`` to the link fields of a cycle's JSON document, where
    the markdown file is the one the field describes, as it was before a move (``old_dir``). Returns
    True when a field changed."""
    changed = False

    def apply(holder: dict, keys, md: Path) -> None:
        nonlocal changed
        for k in keys:
            value = holder.get(k)
            if isinstance(value, str) and value:
                new = fix_field(value, md)
                if new != value:
                    holder[k] = new
                    changed = True

    apply(data, META_LINK_FIELDS, old_dir / project.progress_name)
    for key in (state.TASKS, state.FIXES):
        for entry in data.get(key) or []:
            if isinstance(entry, dict) and entry.get("file"):
                apply(entry, LINK_FIELDS, old_dir / str(entry["file"]))
    return changed


def archive(project: Project, cycle: Cycle, *, commit: bool = True, dry_run: bool = False) -> dict:
    blocking = blockers(project, cycle)
    old_dir = cycle.path
    new_dir = project.archive_dir / old_dir.name
    result = {"cycle": cycle.name, "from": display(project.root, old_dir),
              "to": display(project.root, new_dir), "blockers": blocking, "rewritten": [], "commit": None}
    if blocking or dry_run:
        return result
    if old_dir == project.cycles_root:
        raise RiteError("a flat single-cycle layout cannot be archived into itself; move it by hand")
    if new_dir.exists():
        raise RiteError(f"{display(project.root, new_dir)} already exists")
    local = cycle.local
    commit = commit and not local
    if not local and not gitutil.is_repo(project.root):
        raise RiteError("archive needs git (git mv keeps history)")
    if commit and gitutil.run(project.root, "diff", "--cached", "--name-only").strip():
        raise RiteError("the index has staged changes; commit or unstage them first (archive commits the index)")

    # compute rewrites from the old layout, then move, then write
    rewrites: dict[Path, str] = {}
    for f in _md_files(project.root):
        text = f.read_text(encoding="utf-8", errors="replace")
        new_f = new_dir / f.relative_to(old_dir) if old_dir in f.parents else f
        new_text = _rewrite(project, text, f, new_f, old_dir, new_dir)
        if new_text != text:
            rewrites[new_f] = new_text
    for c in project.all_cycles():
        for path in (c.progress_state_path, c.fixes_state_path):
            if not path.is_file():
                continue
            data = state.read(path)
            here = new_dir / c.path.relative_to(old_dir) if c.path == old_dir or old_dir in c.path.parents else c.path

            def fix_field(target: str, md: Path, here=here, there=c.path) -> str:
                new_md = here / md.relative_to(there)
                return _rewrite_target(project, target, md, new_md, old_dir, new_dir)

            if _map_state_links(project, data, c.path, here, fix_field):
                rewrites[here / path.name] = state.dumps(data)
    new_dir.parent.mkdir(parents=True, exist_ok=True)
    if local:
        shutil.move(old_dir, new_dir)  # nothing of a local cycle is in git to move
    else:
        gitutil.mv(project.root, old_dir, new_dir)
    for path, text in rewrites.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    result["rewritten"] = [display(project.root, p) for p in rewrites]
    result["local"] = local
    if commit:
        # git mv already staged the rename; add the rewritten files and the moved folder's untracked leftovers
        paths = [str(new_dir.relative_to(project.root)), *(str(p.relative_to(project.root)) for p in rewrites)]
        gitutil.run(project.root, "add", "--", *paths)
        gitutil.run(project.root, "commit", "-q", "-m", bookkeeping_message(project, "archive", cycle.name, cycle=cycle))
        result["commit"] = gitutil.short(project.root, "HEAD")
    return result
