"""Composite subcommands: one CLI call where a command used to spend five turns.

Each of these answers a whole question of the rite (*what do I work on?*, *what must I read?*,
*is it green?*, *what else mentions this?*, *record it*) instead of a step of it. Why: a turn costs
the whole context, so the ceremony around the work was measured as a third of an invocation's cost.
"""

from __future__ import annotations

import functools
import os
import re
import signal
import subprocess
from pathlib import Path
from typing import Callable

from . import check as checkmod, gitutil, markdown, ops, selection, views
from .config import DEFAULTS
from .model import Cycle, Item, Project, RiteError, display, resolve_link
from .naming import as_list

CODE_SPAN = re.compile(r"`([^`]+)`")
# a list item: the marker, then a space — `**Bold prose**` opens with a star and is no bullet
BULLET = re.compile(r"^\s*[-*+]\s")


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
        "push": cfg["commit"]["push"],
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
def begin(project: Project, *, kind: str, cycle_name: str | None, item_id: str | None,
          claim: bool = True) -> dict:
    """Resolve cycle and item, take the item, and hand back everything the first turn needed.

    Idempotent: an item already in progress is returned unchanged, so a resumed run does not rewrite
    files or add a second log line. ``claim=False`` takes nothing: a run that only plans must not make
    its item the one the next run resumes first.
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
    if claim and kind in ("task", "fix") and item.status == "pending":
        ops.mark(project, cycle, item, "in-progress")
        taken = True
    repo_dir = _repo_dir(project, item)
    return {
        "cycle": cycle.name, "kind": kind, "reason": reason, "taken": taken,
        "paths": {
            "cycle": display(project.root, cycle.path),
            "progress": display(project.root, cycle.progress_path),
            "fixes": display(project.root, cycle.fixes_path),
            "progress_state": display(project.root, cycle.progress_state_path),
            "fixes_state": display(project.root, cycle.fixes_state_path),
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
        for key in ("confirmed_decisions", "gates", "generated_artifacts"):
            found = markdown.first_section(profile, project.section_titles(key))
            if found and found[1].strip():
                parts.append({"name": f"{rel} § {found[0]}", "text": found[1].strip()})
        phase = item.fields.get("phase")
        checks = markdown.first_section(profile, project.section_titles("phase_checks"))
        if checks and phase is not None:
            label = project.section_title("phase_label")
            labels = checkmod.label_pattern(project.section_titles("phase_label"))
            wanted = [b for b in re.split(r"(?m)^(?=#{3,6}\s|\s*[-*]\s+\*\*)", checks[1])
                      if re.search(rf"(?i)\b{labels}s?\s+{re.escape(str(phase))}\b", b)]
            if wanted:
                parts.append({"name": f"{rel} § {checks[0]} ({label} {phase})",
                              "text": "\n".join(w.strip() for w in wanted)})
    terms = [*(str(f) for f in (item.fields.get("files") or [])),
             str(item.fields.get("type") or ""), item.repo or "",
             *(f"{label} {item.fields.get('phase')}" for label in project.section_titles("phase_label"))]
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
def gate_commands(body: str) -> list[str]:
    """Commands a Gates section lists, one per bullet's code span. Never from a table: a table under
    Gates was measured to be a catalogue of tools — placeholders, emulator runs, a writer — and every
    item runs its gates before it closes."""
    out = []
    for line in body.splitlines():
        if BULLET.match(line):
            span = CODE_SPAN.search(line)
            if span:
                out.append(span.group(1).strip())
    return out


def profile_gates(project: Project, cycle: Cycle) -> list[str]:
    """Commands the profile's gates section lists."""
    if not cycle.profile_path.is_file():
        return []
    found = markdown.first_section(cycle.profile_path.read_text(encoding="utf-8", errors="replace"),
                                   project.section_titles("gates"))
    return gate_commands(found[1]) if found else []


def gates(project: Project, *, cycle_name: str | None, item_id: str | None, tail: int = 20) -> dict:
    cycle = project.resolve_cycle(cycle_name)
    item = None
    if item_id:
        _, item = project.find_item(item_id, cycle)
    where = _repo_dir(project, item)
    commands = [*project.cfg["gates"]["global"], *profile_gates(project, cycle)]
    shell = project_shell(project)
    results = []
    for command in commands:
        run = _run_one(command, where, tail, shell)
        results.append({"command": command, "exit_code": run["exit_code"], "passed": run["exit_code"] == 0,
                        "output": run["output"], "truncated": run["truncated"]})
    return {"cycle": cycle.name, "item": item.id if item else None,
            "where": display(project.root, where), "shell": shell_name(shell), "gates": results,
            "passed": all(r["passed"] for r in results), "count": len(results)}


# --- reproduce -----------------------------------------------------------------
SHELL_ERRORS = (126, 127)  # the shell could not run the command at all: not found, not executable
# a path a failed command could not open: `ls: cannot access 'x'`, `head: cannot open 'x' for reading`,
# `python: can't open file 'x'`, node's `ENOENT: …, open 'x'` — quoted; `grep: x: No such file…` — bare
_GONE = ("No such file or directory", "ENOENT")
_GONE_QUOTED = re.compile(r"""(?:cannot access|can't open file|cannot open|ENOENT\b[^'"\n]*?)\s*['"\u2018]"""
                          r"""([^'"\u2019\n]+)['"\u2019]""")
_GONE_BARE = re.compile(r"""(?:^|[:\s])([^\s:'"]+):\s*No such file or directory""")


def _missing_paths(output: str, where: Path) -> list[str]:
    """Paths a failed command reports it could not find and that are indeed absent from ``where``:
    evidence citing a file of someone's scratch copy fails the same before and after a repair."""
    found: list[str] = []
    for line in output.splitlines():
        if not any(g in line for g in _GONE):
            continue
        match = _GONE_QUOTED.search(line) or _GONE_BARE.search(line)
        if not match or match.group(1) in found:
            continue
        try:
            gone = not (where / match.group(1)).exists()
        except OSError:
            gone = True
        if gone:
            found.append(match.group(1))
    return found


def _fenced(body: str) -> list[list[str]]:
    """The lines of each fenced block of a section."""
    blocks, current = [], None
    for line in body.splitlines():
        if markdown._FENCE_RE.match(line):
            if current is None:
                current = []
            else:
                blocks.append(current)
                current = None
        elif current is not None:
            current.append(line)
    return blocks


_HEREDOC = re.compile(r"""(?<!<)<<(?!<)-?\s*(['"]?)([A-Za-z_][\w-]*)\1""")


def _continued(line: str) -> str:
    """A line that goes on a command: the `> ` prompt a copied bash session shows is not part of it."""
    line = line.rstrip()
    return line[2:] if line.startswith("> ") else line


def _shell_lines(body: str) -> tuple[list[str], list[str], list[str]]:
    """Commands (`$ ` lines inside fences), every other line of those fences (the recorded output),
    and the commands a heredoc left open.

    A command goes on over a line ending in a backslash and over the body of each heredoc it opens, up
    to its delimiter — one command, run whole. Why: run line by line, `python - <<'EOF'` got no body
    and a continued `for` loop half its text; exit 2 read like a reproduced symptom. A heredoc with no
    closing delimiter is not run at all: half a command measures nothing."""
    commands, recorded, broken = [], [], []
    for block in _fenced(body):
        i = 0
        while i < len(block):
            stripped = block[i].strip()
            i += 1
            if not stripped.startswith("$"):
                if stripped:
                    recorded.append(block[i - 1].rstrip())
                continue
            command = stripped[1:].strip()
            if not command:
                continue
            while command.endswith("\\") and i < len(block):
                command += "\n" + _continued(block[i])
                i += 1
            closed = True
            for m in _HEREDOC.finditer(command):
                delimiter, body_lines = m.group(2), []
                while i < len(block) and _continued(block[i]).strip() != delimiter:
                    body_lines.append(_continued(block[i]))
                    i += 1
                if i == len(block):
                    closed = False
                    break
                command += "\n" + "\n".join([*body_lines, delimiter])
                i += 1
            (commands if closed else broken).append(command)
    return commands, recorded, broken


def evidence_commands(text: str, evidence: list[str] | None = None,
                      verification: list[str] | None = None) -> dict:
    """Where a fix says how to see its symptom: `$ ` lines of the fenced Evidence, else of the
    Verification, else code spans of the Verification's bullets. None of those: not runnable.

    ``evidence`` and ``verification`` are the titles `[sections]` accepts (the defaults when None).
    `source` names the kind of section whatever the language; `heading` is the title found. `why`
    tells the empty cases apart: `no_section` (neither title is there — `looked_for` lists them; a
    title mismatch, not a clean fix; `near` lists headings that begin with one), `no_command` (a
    section is there, with nothing to run) or `unterminated` (a heredoc never closed; `broken`)."""
    evidence = evidence or as_list(DEFAULTS["sections"]["evidence"])
    verification = verification or as_list(DEFAULTS["sections"]["verification"])
    found_evidence = markdown.first_section(text, evidence)
    found_verification = markdown.first_section(text, verification)
    commands, recorded, broken = _shell_lines(found_evidence[1] if found_evidence else "")
    if broken:
        return {"source": "Evidence", "heading": found_evidence[0], "why": "unterminated", "broken": broken,
                "commands": [], "recorded": recorded}
    if commands:
        return {"source": "Evidence", "heading": found_evidence[0], "why": "ok", "commands": commands,
                "recorded": recorded}
    body = found_verification[1] if found_verification else ""
    commands, _, broken = _shell_lines(body)
    if broken:
        return {"source": "Verification", "heading": found_verification[0], "why": "unterminated",
                "broken": broken, "commands": [], "recorded": recorded}
    if not commands:
        commands = [span.group(1).strip() for line in body.splitlines()
                    if BULLET.match(line) for span in [CODE_SPAN.search(line)] if span]
    if commands:
        return {"source": "Verification", "heading": found_verification[0], "why": "ok",
                "commands": commands, "recorded": recorded}
    if found_evidence or found_verification:
        return {"source": None, "heading": None, "why": "no_command", "commands": [], "recorded": recorded}
    return {"source": None, "heading": None, "why": "no_section", "looked_for": [*evidence, *verification],
            "near": markdown.near_headings(text, [*evidence, *verification]), "commands": [],
            "recorded": recorded}


def _export(repo: Path, into: Path) -> None:
    """A copy of HEAD, for evidence that writes files: `git archive HEAD`, unpacked."""
    import io
    import tarfile
    data = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=repo, capture_output=True,
                          check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(into, filter="data")
        else:  # Python before 3.11.4
            tar.extractall(into)


def find_bash() -> list[str] | None:
    """Bash, as Claude Code runs it — Git Bash on Windows. Gates and evidence are written and tried in
    that shell, so `grep 'a  b' f` must mean there what it meant when it was written; cmd.exe would
    pass the quotes as text. None: no bash found."""
    import shutil
    if os.name != "nt":
        return [found, "-c"] if (found := shutil.which("bash")) else None
    candidates = [os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")]
    git = shutil.which("git")
    if git:  # <Git>/cmd/git.exe or <Git>/mingw64/bin/git.exe; never WSL's System32 bash
        for root in Path(git).resolve().parents[:3]:
            candidates += [root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return [str(candidate), "-c"]
    return None


def project_shell(project: Project) -> list[str] | None:
    """The shell `[gates].shell` names: `bash` (default; the platform's own shell when there is none)
    or `system` (cmd.exe on Windows, sh elsewhere), for gates written for cmd.exe."""
    return None if project.cfg["gates"]["shell"] == "system" else find_bash()


def shell_name(shell: list[str] | None) -> str:
    return Path(shell[0]).stem if shell else "system"


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill a command and whatever it started: a shell's children outlive the shell."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        proc.kill()


def _run_one(command: str, where: Path, tail: int, shell: list[str] | None = None, *,
             timeout: float | None = None, cap_bytes: int | None = None) -> dict:
    """Run one command and keep its output: the tail when it passes, else up to ``cap_bytes`` of its
    end (`truncated` when cut). Past ``timeout`` seconds the command and its children are killed:
    `timed_out`, no exit code, the output so far."""
    import tempfile
    import time
    run = ([*shell, command], False) if shell else (command, True)
    # a file, not a pipe: a child left in the background keeps a pipe open, and reading it to its
    # end waited forever; nor does an endless output pile up in memory
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    started = time.monotonic()
    with tempfile.TemporaryFile() as out:
        # stdin closed: a heredoc arrives one line at a time, and `python -` would wait on it forever
        proc = subprocess.Popen(run[0], shell=run[1], cwd=where, stdout=out, stderr=out,
                                stdin=subprocess.DEVNULL, env={**os.environ}, **group)
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            proc.wait()
        seconds = round(time.monotonic() - started, 1)
        size = out.seek(0, os.SEEK_END)
        out.seek(max(0, size - cap_bytes) if cap_bytes else 0)
        raw = out.read()
    output = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
    clipped = len(raw) < size
    if clipped and "\n" in output:
        output = output.split("\n", 1)[1]  # a line cut in half is noise
    code = None if timed_out else proc.returncode
    lines = output.splitlines()
    return {"command": command, "exit_code": code, "shell_error": code in SHELL_ERRORS,
            "timed_out": timed_out, "seconds": seconds, "output_bytes": size,
            "missing_path": _missing_paths(output, where) if code else [],
            "output": "\n".join(lines[-tail:]) if code == 0 else output,
            "truncated": clipped or (code == 0 and len(lines) > tail)}


def _undecidable(runs: list[dict]) -> dict:
    """A fix whose evidence could not run as written has no verdict: never *stale*."""
    missing = list(dict.fromkeys(p for r in runs for p in r["missing_path"]))
    return {"missing_path": missing, "timed_out": any(r["timed_out"] for r in runs),
            "cannot_decide": bool(missing) or any(r["shell_error"] or r["timed_out"] for r in runs)}


def reproduce(project: Project, *, fix_id: str | None, cycle_name: str | None, all_open: bool = False,
              tail: int = 20, scratch: bool = False, timeout: float | None = None,
              progress: Callable[[int, int, dict], None] | None = None) -> dict:
    """Run the evidence of one fix, or of every open fix of the cycle, and measure — never judge.

    Whoever calls compares the output with the recorded Evidence and writes the verdict. Fixes run
    one after the other, so a fix holding a serialized resource never shares it. An output above
    `[limits].inline_triage_max_output_kb` is cut to its tail and flagged `over_limit`: the main
    thread does not hold it; that fix goes to an agent. Runs only commands written in the
    repository's own versioned fix files — the same trust `[gates].global` has. A blocked fix runs
    its `unblocked_by` in place of its evidence: exit 0 says the environment it waited on is there.
    A fix whose command could not run as written (`shell_error`, `missing_path`) is `cannot_decide`,
    and so is one whose command outlived `timeout` (`[limits].reproduce_timeout_s`): it was killed
    with its children, `timed_out`. ``progress`` hears of each fix as soon as it is measured."""
    import shutil
    import tempfile
    cycle = project.resolve_cycle(cycle_name)
    if all_open:
        fixes = sorted(selection.open_fixes(cycle), key=lambda f: f.n)
    elif fix_id:
        _, item = project.find_item(fix_id, cycle)
        if item.kind != "fix":
            raise RiteError(f"{fix_id} is a {item.kind}, not a fix")
        fixes = [item]
    else:
        raise RiteError("name a fix, or pass --all")
    limit_kb = project.cfg["limits"]["inline_triage_max_output_kb"]
    if timeout is None:
        timeout = project.cfg["limits"]["reproduce_timeout_s"]
    if timeout <= 0:
        raise RiteError("--timeout must be a number of seconds > 0")
    shell = project_shell(project)
    # one byte past the limit: enough to tell an output over it, never the whole of an endless one
    run = functools.partial(_run_one, tail=tail, shell=shell, timeout=timeout, cap_bytes=int(limit_kb * 1024) + 1)
    copies: dict[Path, Path] = {}
    results = []
    try:
        for fix in fixes:
            if fix.status == "blocked":
                # the evidence needs what the environment lacks; the unblock command is what decides
                command = str(fix.fields.get("unblocked_by") or "").strip()
                results.append({
                    "id": fix.id, "path": display(project.root, fix.path), "runnable": False,
                    "source": None, "heading": None, "why": "blocked", "blocked": True,
                    "unblocked_by": command or None,
                    "unblock": run(command, _repo_dir(project, fix)) if command else None,
                    "resources": fix.fields.get("resources") or [],
                    "recorded": [], "commands": [], "held_bytes": 0, "over_limit": False,
                    "missing_path": [], "timed_out": False, "cannot_decide": False,
                })
                if progress:
                    progress(len(results), len(fixes), results[-1])
                continue
            found = evidence_commands(fix.path.read_text(encoding="utf-8", errors="replace"),
                                      project.section_titles("evidence"), project.section_titles("verification"))
            repo = _repo_dir(project, fix)
            where = repo
            if scratch and found["commands"]:
                if repo not in copies:
                    copies[repo] = Path(tempfile.mkdtemp(prefix="rite-reproduce-"))
                    _export(repo, copies[repo])
                where = copies[repo]
            runs = [run(command, where) for command in found["commands"]]
            # what holding it inline would cost: a failing command's whole output, a passing one's tail
            held = sum(len(r["output"].encode("utf-8")) if r["exit_code"] == 0 else r["output_bytes"] for r in runs)
            over = held > limit_kb * 1024
            if over:
                for r in runs:
                    r["output"] = "\n".join(r["output"].splitlines()[-tail:])
                    r["truncated"] = True
            results.append({
                "id": fix.id, "path": display(project.root, fix.path), "runnable": bool(found["commands"]),
                "source": found["source"], "heading": found["heading"], "why": found["why"], "blocked": False,
                **{k: found[k] for k in ("looked_for", "near", "broken") if k in found},
                "resources": fix.fields.get("resources") or [],
                "recorded": found["recorded"], "commands": runs, "held_bytes": held, "over_limit": over,
                **_undecidable(runs),
            })
            if progress:
                progress(len(results), len(fixes), results[-1])
    finally:
        for copy in copies.values():
            shutil.rmtree(copy, ignore_errors=True)
    return {"cycle": cycle.name, "scratch": scratch, "limit_kb": limit_kb, "timeout_s": timeout,
            "shell": shell_name(shell), "count": len(results),
            "fixes": results}


# --- sweep ---------------------------------------------------------------------
def sweep_targets(project: Project, cycle: Cycle) -> list[Path]:
    """The documents a change can make stale: the cycle, its profile and pitfalls, the plans, and the
    repository's own top-level markdown."""
    targets: list[Path] = []
    for base in (cycle.path, project.cfg.path("plans_dir")):
        if base.is_dir():
            targets += [p for p in sorted(base.rglob("*.md"))]
    targets += [p for p in (cycle.progress_state_path, cycle.fixes_state_path) if p.is_file()]
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
def finish(project: Project, *, item_id: str, cycle_name: str | None, sha: str | None = None,
           commit: bool = True, no_repo: bool = False, reason: str = "") -> dict:
    """Close the item, verify the cycle and say what comes next — the three calls that ended every run."""
    cycle, item = project.find_item(item_id, project.resolve_cycle(cycle_name) if cycle_name else None)
    closed = ops.close(project, cycle, item, sha=sha, commit=commit, no_repo=no_repo, reason=reason)
    pushed = _push_after_commit(project, item, no_repo) if closed.get("commit") else []
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
            "synced": [display(project.root, p) for p in views.sync(project, cycle)],
            "pushed": pushed}


def commit_new(project: Project, *, item_id: str, cycle_name: str | None) -> dict:
    """Commit a newly created item and, under `after-each-item`, push the bookkeeping repository."""
    cycle, item = project.find_item(item_id, project.resolve_cycle(cycle_name) if cycle_name else None)
    res = ops.commit_new(project, cycle, item)
    return {**res, "pushed": _push_after_commit(project, item, True) if res.get("commit") else []}


def _push_after_commit(project: Project, item: Item, no_repo: bool) -> list[dict]:
    """`[commit].push = "after-each-item"`: push the work repository and the bookkeeping one.

    Run after `rite finish` and `rite commit-new`. A failed push is reported, never fatal: the
    commit already stands in the local history.
    """
    if project.cfg["commit"]["push"] != "after-each-item":
        return []
    roots = [project.root] if no_repo else [project.git_root(item), project.root]
    result = []
    for root in dict.fromkeys(r.resolve() for r in roots):
        if not gitutil.is_repo(root):
            continue
        entry = {"repo": display(project.root, root) or ".", "ok": True, "error": None}
        try:
            gitutil.push(root)
        except gitutil.GitError as e:
            entry.update(ok=False, error=str(e))
        result.append(entry)
    return result
