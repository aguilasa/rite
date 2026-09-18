"""Cycle lifecycle: create a cycle, check it can close, archive it (with link rewriting)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import frontmatter, gitutil, markdown, views
from .model import Cycle, Project, RiteError, display, make_link, resolve_link
from .ops import bookkeeping_message, render

LINK_FIELDS = ("source_of_truth", "plan", "profile", "pitfalls")
_PREFIX_RE = re.compile(r"^[A-Za-z0-9]+$")


# --- new cycle -----------------------------------------------------------------
def new_cycle(project: Project, name: str, prefix: str, *, plan: str | None = None,
              commit: bool = False) -> dict:
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
            text = text.replace("## Phase-specific checks", "## " + project.cfg["sections"]["phase_checks"])
        dest.write_text(text, encoding="utf-8", newline="\n")
        created.append(dest)
    cycle = project.load_cycle(path)
    views.sync(project, cycle)
    sha = None
    if commit:
        sha = gitutil.commit_paths(project.root, created, bookkeeping_message(project, "new cycle", name))
    return {"cycle": name, "prefix": prefix, "path": display(project.root, path),
            "created": [display(project.root, p) for p in created], "commit": sha}


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

    lines = text.split("\n")
    code_lines = {n - 1 for n in range(1, len(lines) + 1)} - {n - 1 for n, _ in markdown.prose_lines(text)}
    link_re = re.compile(r"(?<!!)(\[(?:[^\]\\]|\\.)*\]\(\s*<?)([^)\s>]+)")
    for i, line in enumerate(lines):
        if i in code_lines:
            continue
        lines[i] = link_re.sub(lambda m: m.group(1) + fix_target(m.group(2)), line)
    text = "\n".join(lines)
    try:
        fields, _ = frontmatter.parse(text)
    except frontmatter.FrontmatterError:
        return text  # not ours to rewrite: frontmatter beyond the supported subset
    updates = {k: fix_target(str(fields[k])) for k in LINK_FIELDS
               if isinstance(fields.get(k), str) and fields.get(k) and fix_target(str(fields[k])) != fields[k]}
    return frontmatter.set_fields(text, updates) if updates else text


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
    if not gitutil.is_repo(project.root):
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
    gitutil.mv(project.root, old_dir, new_dir)
    for path, text in rewrites.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    result["rewritten"] = [display(project.root, p) for p in rewrites]
    if commit:
        # git mv already staged the rename; add the rewritten files and the moved folder's untracked leftovers
        paths = [str(new_dir.relative_to(project.root)), *(str(p.relative_to(project.root)) for p in rewrites)]
        gitutil.run(project.root, "add", "--", *paths)
        gitutil.run(project.root, "commit", "-q", "-m", bookkeeping_message(project, "archive", cycle.name))
        result["commit"] = gitutil.short(project.root, "HEAD")
    return result
