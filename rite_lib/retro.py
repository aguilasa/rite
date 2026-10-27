"""`rite retro-suggest` — where each lesson of a retro could go, with its evidence. Deterministic and
read-only: the retro still decides, this only replaces rereading cycles with a measured list."""

from __future__ import annotations

import re
from pathlib import Path

from . import gitutil, markdown
from .config import NO_COMMIT
from .guard import glob_regex
from .model import Cycle, Item, Project, display

_ENTRY_KEY = re.compile(r"^\s*[-*]\s+(tags|paths|proven by|rule)\s*:\s*(.*)$", re.IGNORECASE)


def _strip_hints(text: str) -> str:
    """Template hints are not entries (the pitfalls template documents its format in a comment)."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _values(raw: str) -> list[str]:
    return [v.strip().strip("`").strip() for v in re.split(r"[,;]", raw) if v.strip().strip("`").strip()]


def pitfall_entries(path: Path) -> list[dict]:
    """Entries of a pitfalls file in the template's format: a heading below the title, then
    `- tags:`, `- paths:`, `- proven by:` and `- rule:` bullets. Anything else is skipped."""
    if not path.is_file():
        return []
    entries: list[dict] = []
    current: dict | None = None
    for line in _strip_hints(path.read_text(encoding="utf-8", errors="replace")).splitlines():
        heading = markdown._HEADING_RE.match(line)
        if heading:
            current = None
            if len(heading.group(1)) >= 2:
                current = {"title": heading.group(2).strip(), "tags": [], "paths": [], "proven_by": []}
                entries.append(current)
            continue
        match = _ENTRY_KEY.match(line)
        if current is None or not match:
            continue
        key, raw = match.group(1).lower(), match.group(2)
        if key == "proven by":
            # `FIX-X-007 (2026-01-02), abc1234 (2026-01-03)`: the first word of each, never the date
            current["proven_by"] += [v.split()[0] for v in _values(raw)]
        elif key in ("tags", "paths"):
            current[key] += [v.removeprefix("./").lstrip("/") for v in _values(raw)] if key == "paths" \
                else _values(raw)
    return entries


def covers(pattern: str, path: str) -> bool:
    """A declared path covers ``path`` exactly, as a folder or as a glob — the rule `rite close` uses."""
    pattern = pattern.strip().removeprefix("./").lstrip("/")
    return bool(pattern) and (path == pattern or path.startswith(pattern.rstrip("/") + "/")
                              or bool(glob_regex(pattern).fullmatch(path)))


def _fix_paths(project: Project, cycle: Cycle, fix: Item) -> list[str]:
    """The fix's declared `files` and the paths of its work commit, but for the files Rite writes."""
    paths = [str(f).removeprefix("./").lstrip("/") for f in (fix.fields.get("files") or [])]
    sha = str(fix.fields.get("done_commit") or "")
    root = project.git_root(fix)
    if sha and sha != NO_COMMIT and gitutil.is_repo(root) and gitutil.resolve(root, sha):
        exempt = {display(root, p) for p in (fix.path, cycle.progress_state_path, cycle.fixes_state_path,
                                             cycle.progress_path, cycle.fixes_path)}
        paths += [p.split(" -> ")[-1] for _, p in gitutil.changed_files(root, sha)
                  if p.split(" -> ")[-1] not in exempt]
    return list(dict.fromkeys(paths))


def _done_dates(cycle: Cycle) -> list[str]:
    return sorted(str(i.fields["done_on"]) for i in cycle.items if re.fullmatch(r"\d{4}-\d{2}-\d{2}",
                                                                                 str(i.fields.get("done_on"))))


def previous_cycle(project: Project, cycle: Cycle, cycles: list[Cycle]) -> Cycle | None:
    """The cycle before this one: of the others, the one that finished last, no later than this one
    started. Cycles record no "follows" link; the dates their items were done are what there is."""
    dates = _done_dates(cycle)
    start = dates[0] if dates else "9999-12-31"
    best: tuple[str, Cycle] | None = None
    for other in cycles:
        done = _done_dates(other)
        if other.path == cycle.path or not done or done[-1] > start:
            continue
        if best is None or done[-1] > best[0]:
            best = (done[-1], other)
    return best[1] if best else None


def _empty(body: str) -> bool:
    return not _strip_hints(body).strip()


def _sections(text: str) -> list[tuple[str, str]]:
    """The `##` sections of a profile, in order, each with its body (subsections included)."""
    out: list[tuple[str, str]] = []
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(r"^##\s+\S", line)]
    for k, i in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        out.append((lines[i][2:].strip(), "\n".join(lines[i + 1:end])))
    return out


def suggest(project: Project, cycle: Cycle, previous: str | None = None) -> dict:
    cycles = project.all_cycles()
    prev = project.resolve_cycle(previous) if previous else previous_cycle(project, cycle, cycles)
    owner = {i.id: c.name for c in cycles for i in c.items}
    own = pitfall_entries(cycle.pitfalls_path)
    files = [display(project.root, cycle.pitfalls_path)] if cycle.pitfalls_path.is_file() else []

    fixes = sorted((f for f in cycle.fixes if f.status != "stale"), key=lambda f: f.id)
    fix_paths = {f.id: _fix_paths(project, cycle, f) for f in fixes}

    keep = []
    for fix in fixes:
        matches = []
        for entry in own:
            if fix.id in entry["proven_by"]:
                matches.append({"title": entry["title"], "file": files[0], "by": "proven_by"})
            elif any(covers(p, path) for p in entry["paths"] for path in fix_paths[fix.id]):
                matches.append({"title": entry["title"], "file": files[0], "by": "paths"})
        keep.append({"fix": fix.id, "origin": fix.fields.get("origin"), "paths": fix_paths[fix.id],
                     "matches_existing": matches, "suggest": "update-existing" if matches else "new"})

    # an entry inherited by copy appears in both files: this cycle's copy wins, the proofs merge
    sources = [(cycle.pitfalls_path, own)]
    if prev is not None and prev.pitfalls_path != cycle.pitfalls_path:
        sources.append((prev.pitfalls_path, pitfall_entries(prev.pitfalls_path)))
    merged: dict[str, dict] = {}
    for path, entries in sources:
        for entry in entries:
            slot = merged.setdefault(entry["title"], {**entry, "file": display(project.root, path),
                                                      "proven_by": []})
            slot["proven_by"] = list(dict.fromkeys([*slot["proven_by"], *entry["proven_by"]]))
    promote = []
    for entry in merged.values():
        proofs = list(entry["proven_by"])
        proofs += [f.id for f in fixes if f.id not in proofs and entry["paths"]
                   and any(covers(p, path) for p in entry["paths"] for path in fix_paths[f.id])]
        where = list(dict.fromkeys(owner[p] for p in proofs if p in owner))
        if len(where) >= 2:
            promote.append({"title": entry["title"], "file": entry["file"], "proven_by": proofs,
                            "cycles": where})

    prune = []
    tracked = gitutil.run(project.root, "ls-files").splitlines() if gitutil.is_repo(project.root) else []
    for entry in own:
        if entry["paths"] and not any(covers(p, t) for p in entry["paths"] for t in tracked):
            prune.append({"kind": "pitfall-paths-gone", "title": entry["title"], "file": files[0],
                          "paths": entry["paths"]})
    limit = int(project.cfg["profile"]["max_kb"]) * 1024
    if cycle.profile_path.is_file() and limit and cycle.profile_path.stat().st_size > limit:
        text = cycle.profile_path.read_text(encoding="utf-8", errors="replace")
        sizes = sorted(((t, len(b.encode("utf-8"))) for t, b in _sections(text)), key=lambda s: -s[1])
        prune.append({"kind": "profile-over-max-kb", "file": display(project.root, cycle.profile_path),
                      "kb": cycle.profile_path.stat().st_size // 1024, "max_kb": limit // 1024,
                      "largest_sections": [{"title": t, "bytes": n} for t, n in sizes]})

    carry_over = []
    if prev is not None and prev.profile_path.is_file() and prev.profile_path != cycle.profile_path:
        now = dict(_sections(cycle.profile_path.read_text(encoding="utf-8", errors="replace"))) \
            if cycle.profile_path.is_file() else {}
        for title, body in _sections(prev.profile_path.read_text(encoding="utf-8", errors="replace")):
            if not _empty(body) and _empty(now.get(title, "")):
                carry_over.append({"section": title, "from_cycle": prev.name,
                                   "content": _strip_hints(body).strip()})

    return {"cycle": cycle.name, "previous": prev.name if prev else None, "pitfalls": files,
            "keep": keep, "promote": promote, "prune": prune, "carry_over": carry_over}


def render_text(s: dict) -> str:
    lines = [f"retro-suggest {s['cycle']} (previous: {s['previous'] or '—'})"]
    lines.append(f"keep ({len(s['keep'])}):")
    for k in s["keep"]:
        hit = ", ".join(m["title"] for m in k["matches_existing"])
        lines.append(f"  {k['fix']}: {k['suggest']}" + (f" — {hit}" if hit else ""))
    lines.append(f"promote ({len(s['promote'])}):")
    lines += [f"  {p['title']} — {', '.join(p['proven_by'])} ({', '.join(p['cycles'])})" for p in s["promote"]]
    lines.append(f"prune ({len(s['prune'])}):")
    for p in s["prune"]:
        lines.append(f"  {p['title']}: paths gone ({', '.join(p['paths'])})" if p["kind"] == "pitfall-paths-gone"
                     else f"  {p['file']}: {p['kb']} KB > {p['max_kb']} KB")
    lines.append(f"carry-over ({len(s['carry_over'])}):")
    lines += [f"  {c['section']} (from {c['from_cycle']})" for c in s["carry_over"]]
    return "\n".join(lines)

