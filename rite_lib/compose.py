"""Composite subcommands: one CLI call where a command used to spend five turns.

Each of these answers a whole question of the rite (*what do I work on?*, *what must I read?*,
*is it green?*, *what else mentions this?*, *record it*) instead of a step of it. Why: a turn costs
the whole context, so the ceremony around the work was measured as a third of an invocation's cost.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from . import check as checkmod, gitutil, markdown, ops, selection, views
from .model import Cycle, Item, Project, RiteError, display, resolve_link

CODE_SPAN = re.compile(r"`([^`]+)`")


# --- shared helpers ------------------------------------------------------------
def _repo_dir(project: Project, item: Item | None) -> Path:
    if item is None:
        return project.root
    try:
        return project.git_root(item)
    except RiteError:
        return project.root


def _cycle_digest(project: Project, cycle: Cycle) -> dict:
    """What `rite.toml` says that changes how an item is worked on — no prose, no defaults to re-read."""
    cfg = project.cfg
    return {
        "languages": {k: cfg["project"][k] for k in ("docs_language", "code_language", "commit_language")},
        "link_style": cfg.link_style,
        "read_only": list(cfg["guards"]["read_only"]),
        "generated": [{"paths": g.get("paths"), "generator": g.get("generator"), "check": g.get("check")}
                      for g in cfg["guards"]["generated"]],
        "gates": list(cfg["gates"]["global"]),
        "never_stage": list(cfg["commit"]["never_stage"]),
        "serialized_resources": [r.get("name") for r in cfg["resources"]["serialized"]],
        "limits": dict(cfg["limits"]),
        "context_kb": cfg["output"]["context_kb"],
    }


def _item_facts(project: Project, item: Item) -> dict:
    f = item.fields
    return {
        "id": item.id, "kind": item.kind, "path": display(project.root, item.path),
        "title": item.title, "status": item.status, "type": f.get("type"), "phase": f.get("phase"),
        "severity": f.get("severity"), "origin": f.get("origin"), "repo": item.repo,
        "source_of_truth": f.get("source_of_truth"), "files": f.get("files") or [],
        "resources": f.get("resources") or [], "depends_on": item.depends_on,
    }


def _repo_kb(root: Path) -> int | None:
    """Rough size of a repository, from git's own count — cheap on any size."""
    if not gitutil.is_repo(root):
        return None
    out = gitutil.run(root, "count-objects", "-v", check=False)
    total = 0
    for line in out.splitlines():
        key, _, value = line.partition(":")
        if key.strip() in ("size", "size-pack") and value.strip().isdigit():
            total += int(value.strip())
    return total


# --- begin ---------------------------------------------------------------------
def begin(project: Project, *, kind: str, cycle_name: str | None, item_id: str | None) -> dict:
    """Resolve cycle and item, take the item, and hand back everything the first turn needed.

    Idempotent: an item already in progress is returned unchanged, so a resumed run does not rewrite
    files or add a second log line.
    """
    cycle = project.resolve_cycle(cycle_name)
    index = cycle.by_id()
    if item_id:
        if item_id not in index:
            raise RiteError(f"{item_id} is not an item of cycle {cycle.name}")
        item = index[item_id]
        if item.kind != ("task" if kind in ("task", "review") else "fix"):
            raise RiteError(f"{item_id} is a {item.kind}, not a {kind}")
        unmet = selection.unmet_deps(item, index)
        reason = "named explicitly"
        if unmet:
            raise RiteError(f"{item_id} waits for {', '.join(unmet)}")
    else:
        pick = {"task": selection.next_task, "fix": selection.next_fix,
                "review": selection.next_review}[kind](cycle)
        item, reason = pick.item, pick.reason
        if item is None:
            return {"cycle": cycle.name, "kind": kind, "item": None, "reason": reason,
                    "blocked_by": pick.blocked_by}
    taken = False
    if kind in ("task", "fix") and item.status == "pending":
        ops.mark(project, cycle, item, "in-progress")
        taken = True
    repo_dir = _repo_dir(project, item)
    return {
        "cycle": cycle.name, "kind": kind, "reason": reason, "taken": taken,
        "paths": {
            "cycle": display(project.root, cycle.path),
            "progress": display(project.root, cycle.progress_path),
            "fixes": display(project.root, cycle.fixes_path),
            "profile": display(project.root, cycle.profile_path),
            "profile_exists": cycle.profile_path.is_file(),
            "pitfalls": display(project.root, cycle.pitfalls_path),
            "plan": cycle.meta.get("plan"),
        },
        "prefix": cycle.prefix, "ticket": cycle.ticket, "local": cycle.local,
        "workspace": project.workspace, "repos": project.repos() if project.workspace else [],
        "item": _item_facts(project, item),
        "commit": ops.commit_refs(project, cycle, item),
        "config": _cycle_digest(project, cycle),
        "repo_kb": _repo_kb(repo_dir),
        "next_step": f"rite context {item.id} --json",
    }


# --- context -------------------------------------------------------------------
def _slice_anchor(text: str, anchor: str) -> tuple[int, int] | None:
    """(first line, last line) of the anchored heading and everything under it, 1-based inclusive."""
    lines = text.splitlines()
    heads = []  # (line index, level, slug, number)
    seen: dict[str, int] = {}
    for i, line in enumerate(lines):
        m = markdown._HEADING_RE.match(line)
        if not m:
            continue
        title = m.group(2)
        slug = markdown.github_slug(title)
        dup = seen.get(slug, 0)
        seen[slug] = dup + 1
        num = markdown._SECTION_NO_RE.match(title.strip())
        heads.append((i, len(m.group(1)), slug if dup == 0 else f"{slug}-{dup}",
                      num.group(1) if num else None))
    want = anchor.lstrip("#").strip()
    start = level = None
    for i, lvl, slug, num in heads:
        if want and (slug == want or (num and num == want.rstrip("."))):
            start, level = i, lvl
            break
    if start is None:  # explicit anchors (<a id="5.2">) sit on their own line
        for i, line in enumerate(lines):
            if re.search(rf'(?:name|id)=["\']{re.escape(want)}["\']|\{{#{re.escape(want)}\}}', line):
                start = i
                level = next((lvl for j, lvl, _, _ in heads if j >= i), 2)
                break
    if start is None:
        return None
    end = len(lines)
    for i, lvl, _, _ in heads:
        if i > start and lvl <= level:
            end = i
            break
    return start + 1, end


def _pitfall_entries(text: str, terms: list[str]) -> list[str]:
    """Entries of the pitfalls file that mention one of the terms; entries are headings or bullets."""
    if not text.strip() or not terms:
        return []
    blocks, current = [], []
    for line in text.splitlines():
        if markdown._HEADING_RE.match(line) or (line.startswith(("- ", "* ")) and current):
            if current:
                blocks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    lowered = [t.lower() for t in terms if t]
    return [b for b in blocks if b and any(t in b.lower() for t in lowered)]


def _plan_part(project: Project, item: Item) -> dict:
    sot = str(item.fields.get("source_of_truth") or "")
    if not sot:
        return {"name": "source_of_truth", "text": "", "note": "the item declares none"}
    path, anchor = resolve_link(project.root, item.path, sot)
    rel = display(project.root, path)
    if not path.is_file():
        return {"name": rel, "text": "", "note": f"{rel} does not exist"}
    text = path.read_text(encoding="utf-8", errors="replace")
    span = _slice_anchor(text, anchor) if anchor else None
    if span is None:
        head = "\n".join(text.splitlines()[:80])
        note = (f"anchor #{anchor} not found; first 80 lines shown — read on with "
                f"`sed -n '1,200p' {rel}`") if anchor else f"whole file; slice it with `sed -n` if long"
        return {"name": rel, "text": head, "note": note, "anchor": anchor}
    first, last = span
    body = "\n".join(text.splitlines()[first - 1:last])
    return {"name": f"{rel}#{anchor}", "text": body, "lines": [first, last], "file": rel,
            "note": f"section and its subsections (`sed -n '{first},{last}p' {rel}` for the same text)"}


def _shares(parts: list[dict], budget: int) -> list[int]:
    """Budget per part, smallest first: everyone gets an equal share, and what a small part does not
    use goes to the bigger ones. Why: a 26 KB item file once ate the whole budget and left its plan
    section and its profile rules at zero bytes — the cut has to hurt the biggest part, not the rest."""
    sizes = [len(((p.get("text") or "")).encode("utf-8")) for p in parts]
    shares = [0] * len(parts)
    remaining, left = budget, len(parts)
    for index in sorted(range(len(parts)), key=lambda i: sizes[i]):
        share = remaining // left if left else 0
        shares[index] = min(sizes[index], share)
        remaining -= shares[index]
        left -= 1
    return shares


def context(project: Project, *, item_id: str, cycle_name: str | None = None) -> dict:
    """Everything one item needs read, sliced: the item, its plan section, the profile's rules for it,
    and the pitfalls that mention its files, type or phase. Deterministic for the same inputs."""
    cycle, item = project.find_item(item_id, project.resolve_cycle(cycle_name) if cycle_name else None)
    parts: list[dict] = [{"name": display(project.root, item.path), "text": item.body.strip()}]
    parts.append(_plan_part(project, item))

    if cycle.profile_path.is_file():
        profile = cycle.profile_path.read_text(encoding="utf-8", errors="replace")
        rel = display(project.root, cycle.profile_path)
        for title in ("Confirmed decisions", "Gates", "Generated artifacts"):
            body = markdown.section(profile, title)
            if body and body.strip():
                parts.append({"name": f"{rel} § {title}", "text": body.strip()})
        phase = item.fields.get("phase")
        checks = markdown.section(profile, project.cfg["sections"]["phase_checks"])
        if checks and phase is not None:
            label = project.cfg["sections"]["phase_label"]
            wanted = [b for b in re.split(r"(?m)^(?=#{3,6}\s|\s*[-*]\s+\*\*)", checks)
                      if re.search(rf"(?i)\b{re.escape(label)}s?\s+{re.escape(str(phase))}\b", b)]
            if wanted:
                parts.append({"name": f"{rel} § {project.cfg['sections']['phase_checks']} "
                                      f"({label} {phase})", "text": "\n".join(w.strip() for w in wanted)})
    terms = [*(str(f) for f in (item.fields.get("files") or [])),
             str(item.fields.get("type") or ""), item.repo or "",
             f"{project.cfg['sections']['phase_label']} {item.fields.get('phase')}"]
    if cycle.pitfalls_path.is_file():
        entries = _pitfall_entries(cycle.pitfalls_path.read_text(encoding="utf-8", errors="replace"), terms)
        if entries:
            parts.append({"name": f"{display(project.root, cycle.pitfalls_path)} (matching entries)",
                          "text": "\n\n".join(entries)})

    budget = int(project.cfg["output"]["context_kb"]) * 1024
    used, cut = 0, []
    for part, room in zip(parts, _shares(parts, budget)):
        text = part.get("text") or ""
        if len(text.encode("utf-8")) > room:
            keep = text.encode("utf-8")[:room].decode("utf-8", "ignore")
            dropped = len(text.encode("utf-8")) - len(keep.encode("utf-8"))
            part["text"] = keep
            part["truncated_bytes"] = dropped
            where = part.get("file") or part["name"].split(" §")[0].split("#")[0]
            part["read_rest"] = f"sed -n '{part.get('lines', [1, 1])[0]},$p' {where}"
            cut.append({"part": part["name"], "bytes": dropped, "command": part["read_rest"]})
        used += len(part["text"].encode("utf-8"))
    return {"id": item.id, "cycle": cycle.name, "repo": item.repo, "item": _item_facts(project, item),
            "parts": parts, "bytes": used, "budget": budget, "truncated": cut}


def render_context(data: dict) -> str:
    lines = [f"# context {data['id']} ({data['bytes'] // 1024} KB of {data['budget'] // 1024} KB)"]
    for part in data["parts"]:
        lines += ["", f"## {part['name']}"]
        if part.get("note"):
            lines.append(f"<!-- {part['note']} -->")
        if part.get("text"):
            lines.append(part["text"])
        if part.get("truncated_bytes"):
            lines.append(f"<!-- {part['truncated_bytes']} bytes cut; rest: {part['read_rest']} -->")
    return "\n".join(lines)


# --- gates ---------------------------------------------------------------------
def profile_gates(project: Project, cycle: Cycle) -> list[str]:
    """Commands the profile's Gates section lists, one per code span."""
    if not cycle.profile_path.is_file():
        return []
    body = markdown.section(cycle.profile_path.read_text(encoding="utf-8", errors="replace"), "Gates")
    out = []
    for line in (body or "").splitlines():
        if line.strip().startswith(("-", "*")):
            span = CODE_SPAN.search(line)
            if span:
                out.append(span.group(1).strip())
    return out


def gates(project: Project, *, cycle_name: str | None, item_id: str | None, tail: int = 20) -> dict:
    cycle = project.resolve_cycle(cycle_name)
    item = None
    if item_id:
        _, item = project.find_item(item_id, cycle)
    where = _repo_dir(project, item)
    commands = [*project.cfg["gates"]["global"], *profile_gates(project, cycle)]
    results = []
    for command in commands:
        proc = subprocess.run(command, shell=True, cwd=where, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env={**os.environ})
        output = (proc.stdout or "") + (proc.stderr or "")
        lines = output.splitlines()
        results.append({
            "command": command, "exit_code": proc.returncode, "passed": proc.returncode == 0,
            "output": output if proc.returncode else "\n".join(lines[-tail:]),
            "truncated": proc.returncode == 0 and len(lines) > tail,
        })
    return {"cycle": cycle.name, "item": item.id if item else None,
            "where": display(project.root, where), "gates": results,
            "passed": all(r["passed"] for r in results), "count": len(results)}


# --- sweep ---------------------------------------------------------------------
def sweep_targets(project: Project, cycle: Cycle) -> list[Path]:
    """The documents a change can make stale: the cycle, its profile and pitfalls, the plans, and the
    repository's own top-level markdown."""
    targets: list[Path] = []
    for base in (cycle.path, project.cfg.path("plans_dir")):
        if base.is_dir():
            targets += [p for p in sorted(base.rglob("*.md"))]
    for single in (cycle.profile_path, cycle.pitfalls_path, project.root / "rite.toml"):
        if single.is_file():
            targets.append(single)
    targets += sorted(p for p in project.root.glob("*.md") if p.is_file())
    seen, out = set(), []
    for path in targets:
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def sweep(project: Project, *, terms: list[str], cycle_name: str | None, item_id: str | None = None) -> dict:
    cycle = project.resolve_cycle(cycle_name)
    cap = int(project.cfg["limits"]["sweep_hits"])
    skip = None
    if item_id:
        _, item = project.find_item(item_id, cycle)
        skip = item.path
    found = {}
    for term in terms:
        hits = []
        lowered = term.lower()
        for path in sweep_targets(project, cycle):
            if path == skip:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if lowered not in text.lower():
                continue
            for n, line in enumerate(text.splitlines(), start=1):
                if lowered in line.lower():
                    hits.append({"file": display(project.root, path), "line": n,
                                 "text": line.strip()[:160]})
                    if len(hits) >= cap:
                        break
            if len(hits) >= cap:
                break
        found[term] = {"hits": hits, "capped": len(hits) >= cap}
    return {"cycle": cycle.name, "terms": terms, "results": found,
            "files_searched": len(sweep_targets(project, cycle))}


# --- finish --------------------------------------------------------------------
def finish(project: Project, *, item_id: str, cycle_name: str | None, sha: str = "HEAD",
           commit: bool = True) -> dict:
    """Close the item, verify the cycle and say what comes next — the three calls that ended every run."""
    cycle, item = project.find_item(item_id, project.resolve_cycle(cycle_name) if cycle_name else None)
    closed = ops.close(project, cycle, item, sha=sha, commit=commit)
    cycle = project.load_cycle(cycle.path, archived=cycle.archived)
    findings = checkmod.run(project, [cycle], quick=True)
    errors = [str(f) for f in findings if f.level == "error"]
    kind = "review" if item.kind == "task" else "fix"
    pick = (selection.next_review if kind == "review" else selection.next_fix)(cycle)
    if kind == "review" and pick.item is None:
        pick = selection.next_task(cycle)
        kind = "task"
    return {"closed": closed, "check": {"errors": errors, "warnings":
                                        [str(f) for f in findings if f.level == "warn"]},
            "next": {"kind": kind, **pick.as_dict(project.root)},
            "synced": [display(project.root, p) for p in views.sync(project, cycle)]}
