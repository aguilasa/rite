"""`rite.py batch-plan` — inventory, conflict matrix and waves for a batch.

A batch is not "run everything in parallel". Two items go in the same wave only when they share no
file, no serialized resource and no dependency. The graph speaks of logical dependency, the matrix of
physical contention — when they disagree, the matrix wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import markdown
from .guard import glob_regex
from .model import Cycle, Item, Project, RiteError, display
from .selection import SATISFIED, open_fixes

_CODE_SPAN = re.compile(r"`([^`\s]+)`")
_BARE_BULLET = re.compile(r"(?m)^\s*[-*]\s+([^\s`\[(]+)")
_WILD = re.compile(r"[*?\[]")
# where in the file, not which file: `grep -n` and editors (`:12`, `:12:7`), GitHub (`#L12`, `#L12-L20`)
_LOCATION = re.compile(r"(?::\d+(?::\d+)?|#L\d+(?:-L?\d+)?)$")


@dataclass
class Planned:
    item: Item
    files: list[str]
    resources: list[str]
    files_declared: bool
    wave: int = 0
    conflicts: dict[str, list[str]] = field(default_factory=dict)


def _as_list(value) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _looks_like_path(token: str) -> bool:
    return "/" in token or "." in token.rsplit("/", 1)[-1]


def paths_in(body: str, root: Path | None = None) -> list[str]:
    """Paths in backticks; and, given the repository ``root``, a bullet that opens with a bare path
    that exists there (`- src/a.py (the parser)`) — existence keeps prose out. A location suffix
    (`a.md:512`, `a.md#L12`) is dropped: the conflict matrix compares files, and `a.md:512` is none."""
    found = []
    for m in _CODE_SPAN.finditer(body):
        token = _LOCATION.sub("", m.group(1).strip())
        if _looks_like_path(token):
            found.append(token.lstrip("./"))
    if root is not None:
        for m in _BARE_BULLET.finditer(body):
            token = _LOCATION.sub("", m.group(1).rstrip(",;:")).lstrip("./")
            try:
                exists = _looks_like_path(token) and (root / token).exists()
            except (OSError, ValueError):  # not a path the platform can even name
                exists = False
            if exists:
                found.append(token)
    return list(dict.fromkeys(found))


def _section_paths(text: str, titles: list[str], root: Path | None = None) -> list[str]:
    found_section = markdown.first_section(text, titles)
    return paths_in(found_section[1], root) if found_section else []


def predicted_files(project: Project, item: Item) -> tuple[list[str], bool]:
    """Declared `files:` frontmatter wins; else the paths under the `[sections]` files and scope
    titles. (paths, declared?)"""
    declared = _as_list(item.fields.get("files"))
    if declared:
        return declared, True
    try:
        root = project.git_root(item)
    except RiteError:
        root = project.root
    paths = (_section_paths(item.body, project.section_titles("files"), root)
             + _section_paths(item.body, project.section_titles("scope"), root))
    return list(dict.fromkeys(paths)), False


def _static_prefix(pattern: str) -> str:
    m = _WILD.search(pattern)
    return pattern[: m.start()] if m else pattern


def globs_overlap(a: str, b: str) -> bool:
    a, b = a.strip().lstrip("/"), b.strip().lstrip("/")
    if a == b or glob_regex(a).match(b) or glob_regex(b).match(a):
        return True
    if _WILD.search(a) or _WILD.search(b):
        pa, pb = _static_prefix(a), _static_prefix(b)
        return pa.startswith(pb) or pb.startswith(pa)
    return False


def serialized_names(project: Project, cycle: Cycle) -> set[str]:
    names = {str(r["name"]) for r in project.cfg["resources"]["serialized"]}
    if cycle.profile_path.is_file():
        found = markdown.first_section(cycle.profile_path.read_text(encoding="utf-8"),
                                       project.section_titles("serialized_resources"))
        for line in (found[1] if found else "").splitlines():
            m = re.match(r"\s*[-*]\s+`?([\w.-]+)`?", line)
            if m and m.group(1).lower() not in ("none", "n/a"):
                names.add(m.group(1))
    return names


def select(cycle: Cycle, kind: str, count: int | None, ids: list[str]) -> list[Item]:
    index = cycle.by_id()
    if ids:
        missing = [i for i in ids if i not in index]
        if missing:
            raise RiteError(f"not in cycle {cycle.name}: {', '.join(missing)}")
        chosen = [index[i] for i in ids]
        kinds = {i.kind for i in chosen}
        if len(kinds) > 1:
            raise RiteError("a batch holds tasks or fixes, not both")
        # canonical order, whatever order the IDs were typed in
        rank = {t.id: k for k, t in enumerate(cycle.tasks)}  # execution order, not ID order
        return sorted(chosen, key=lambda i: (i.severity_rank, i.n) if i.kind == "fix" else (0, rank[i.id]))
    count = count or 2
    if kind == "task":
        pool = [t for t in cycle.tasks if t.status in ("in-progress", "pending")]
        pool.sort(key=lambda t: t.status != "in-progress")  # stable: keeps execution order
    else:
        pool = sorted((f for f in open_fixes(cycle) if f.status != "blocked"),
                      key=lambda f: (f.status != "in-progress", f.severity_rank, f.n))
    chosen: list[Item] = []
    taken: set[str] = set()
    for it in pool:
        if len(chosen) >= count:
            break
        if all(d in taken or (d in index and index[d].status in SATISFIED) for d in it.depends_on):
            chosen.append(it)
            taken.add(it.id)
    return chosen


def plan(project: Project, cycle: Cycle, items: list[Item]) -> dict:
    serial = serialized_names(project, cycle)
    planned = []
    for it in items:
        files, declared = predicted_files(project, it)
        res = [r for r in _as_list(it.fields.get("resources"))]
        planned.append(Planned(it, files, res, declared))
    in_batch = {p.item.id: p for p in planned}
    warnings = []
    for p in planned:
        unknown = [r for r in p.resources if r not in serial]
        if unknown:
            warnings.append(f"{p.item.id}: resources {unknown} are not declared serialized (ignored for conflicts)")
        if not p.files:
            warnings.append(f"{p.item.id}: no predicted files — declare `files:` in its frontmatter; "
                            "until then it runs alone")
        blocking = [d for d in p.item.depends_on if d not in in_batch and
                    (d not in cycle.by_id() or cycle.by_id()[d].status not in SATISFIED)]
        if blocking:
            warnings.append(f"{p.item.id}: depends on {blocking}, outside the batch and not done")

    def conflict(a: Planned, b: Planned) -> list[str]:
        why = []
        if a.item.fields.get("type") == "closing" or b.item.fields.get("type") == "closing":
            why.append("closing task runs alone")
        if not a.files or not b.files:
            why.append("unknown files")
        # paths are relative to the item's repository; two repositories never share a file
        same_repo = a.item.repo == b.item.repo
        shared = sorted({f"{x}" for x in a.files for y in b.files if same_repo and globs_overlap(x, y)})
        if shared:
            why.append("files: " + ", ".join(shared))
        res = sorted(set(a.resources) & set(b.resources) & serial)
        if res:
            why.append("resources: " + ", ".join(res))
        if b.item.id in a.item.depends_on or a.item.id in b.item.depends_on:
            why.append("depends_on")
        return why

    for i, a in enumerate(planned):
        for b in planned[i + 1:]:
            why = conflict(a, b)
            if why:
                a.conflicts[b.item.id] = why
                b.conflicts[a.item.id] = why

    # place dependencies before dependents, otherwise keep the given order
    ordered: list[Planned] = []
    remaining = list(planned)
    while remaining:
        placed = {q.item.id for q in ordered}
        ready = next((p for p in remaining
                      if all(d in placed or d not in in_batch for d in p.item.depends_on)), remaining[0])
        ordered.append(ready)
        remaining.remove(ready)

    waves: list[list[Planned]] = []
    for p in ordered:
        floor = max((in_batch[d].wave + 1 for d in p.item.depends_on if d in in_batch), default=0)
        w = floor
        while w < len(waves) and any(q.item.id in p.conflicts for q in waves[w]):
            w += 1
        if w == len(waves):
            waves.append([])
        p.wave = w
        waves[w].append(p)
    # closing tasks go last, after every other wave
    closers = [p for p in planned if p.item.fields.get("type") == "closing"]
    if closers:
        closer_ids = {c.item.id for c in closers}
        others = [[p for p in wave if p.item.id not in closer_ids] for wave in waves]
        waves = [w for w in others if w] + [[c] for c in closers]
        for n, wave in enumerate(waves):
            for p in wave:
                p.wave = n

    root = project.root
    return {
        "cycle": cycle.name,
        "kind": items[0].kind if items else None,
        "items": [{
            "id": p.item.id, "title": p.item.title, "path": display(root, p.item.path), "repo": p.item.repo,
            "type": p.item.fields.get("type"), "severity": p.item.fields.get("severity"),
            "files": p.files, "files_declared": p.files_declared, "resources": p.resources,
            "depends_on": p.item.depends_on, "wave": p.wave + 1, "conflicts": p.conflicts,
        } for p in planned],
        "waves": [[p.item.id for p in wave] for wave in waves],
        "serialized_resources": sorted(serial),
        "warnings": warnings,
    }


def render_text(data: dict) -> str:
    lines = [f"batch plan — cycle {data['cycle']} ({len(data['items'])} {data['kind'] or 'item'}s)", ""]
    for it in data["items"]:
        files = ", ".join(it["files"]) or "?"
        lines.append(f"{it['id']} [wave {it['wave']}] {it['title']}")
        repo = f" in {it['repo']}" if it.get("repo") else ""
        lines.append(f"  files{repo}{'' if it['files_declared'] else ' (inferred)'}: {files}")
        if it["resources"]:
            lines.append(f"  resources: {', '.join(it['resources'])}")
    lines.append("")
    lines.append("conflicts:")
    pairs = {(min(a["id"], b), max(a["id"], b)): why for a in data["items"] for b, why in a["conflicts"].items()}
    lines += [f"  {a} x {b}: {'; '.join(why)}" for (a, b), why in sorted(pairs.items())] or ["  none"]
    lines.append("")
    for n, wave in enumerate(data["waves"], start=1):
        lines.append(f"wave {n}: {', '.join(wave)}")
    if data["warnings"]:
        lines.append("")
        lines += [f"warning: {w}" for w in data["warnings"]]
    return "\n".join(lines)
