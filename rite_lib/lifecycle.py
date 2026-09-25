"""Cycle lifecycle: create a cycle, check it can close, archive it (with link rewriting)."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from . import frontmatter, gitutil, markdown, views
from .model import Cycle, Project, RiteError, display, make_link, resolve_link
from .ops import bookkeeping_message, render

LINK_FIELDS = ("source_of_truth", "plan", "profile", "pitfalls")
_PREFIX_RE = re.compile(r"^[A-Za-z0-9]+$")


# --- new cycle -----------------------------------------------------------------
def new_cycle(project: Project, name: str, prefix: str, *, plan: str | None = None,
              ticket: str | None = None, local: bool = False, commit: bool = False) -> dict:
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
    plan_link = ""
    if plan:
        plan_path, _ = resolve_link(project.root, project.root / "x", plan if plan.startswith("/") else "/" + plan)
        if not plan_path.is_file():
            raise RiteError(f"plan {plan} not found")
        plan_link = make_link(project.root, path / project.progress_name, plan_path, project.cfg.link_style)

    naming = project.cfg["naming"]
    profiles = project.cfg.path("profiles_dir")
    profile = profiles / naming["profile_file"].format(cycle=name)
    pitfalls = profiles / naming["pitfalls_file"].format(cycle=name)
    values = {"cycle": name, "prefix": prefix, "plan": frontmatter.dump_value(plan_link or None)}
    created = []
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
        if tpl == "progress.md":
            # set, not templated: a local template override may predate these keys
            text = frontmatter.set_fields(text, {"ticket": ticket or None, "local": bool(local)})
        dest.write_text(text, encoding="utf-8", newline="\n")
        created.append(dest)
    cycle = project.load_cycle(path)
    views.sync(project, cycle)
    sha = None
    if commit and not cycle.local:
        sha = gitutil.commit_paths(project.root, created,
                                   bookkeeping_message(project, "new cycle", name, cycle=cycle))
    return {"cycle": name, "prefix": prefix, "path": display(project.root, path), "ticket": cycle.ticket,
            "local": cycle.local, "created": [display(project.root, p) for p in created], "commit": sha,
            "ignored": _ignored(project, [path, profile, pitfalls]) if cycle.local else None}


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
    text = cycle.progress_path.read_text(encoding="utf-8")
    cycle.progress_path.write_text(frontmatter.set_fields(text, {"local": False}), encoding="utf-8", newline="\n")
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
        if f.status in ("pending", "in-progress"):
            out.append(f"{f.id} is open ({f.fields.get('severity')})")
        elif f.status == "blocked":
            out.append(f"{f.id} is blocked ({f.fields.get('severity')}) until "
                       f"`{f.fields.get('unblocked_by')}` passes")
    if views.out_of_sync(project, cycle):
        out.append("views out of sync (rite.py sync)")
    return out


def _md_files(root: Path) -> list[Path]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", ".venv", "__pycache__")]
        files += [Path(dirpath) / f for f in filenames if f.endswith(".md")]
    return files


def _rewrite(project: Project, text: str, old_file: Path, new_file: Path, old_dir: Path, new_dir: Path) -> str:
    """Rewrite link targets (prose links and link fields) so they resolve after the move."""

    def moved(p: Path) -> Path:
        try:
            return new_dir / p.relative_to(old_dir)
        except ValueError:
            return p

    def fix_target(target: str) -> str:
        if markdown.is_external(target) or target.startswith("#"):
            return target
        path, anchor = resolve_link(project.root, old_file, target)
        new_target_path = moved(path)
        if new_target_path == path and new_file == old_file:
            return target
        if target.startswith("/") and new_target_path == path:
            return target  # root-absolute link to something that did not move
        link = make_link(project.root, new_file, new_target_path,
                         "root-absolute" if target.startswith("/") else "relative")
        return link + (f"#{anchor}" if anchor else "")

    return _map_links(text, fix_target)


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
    return changes


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
