"""`rite.py sections` — propose the `[sections]` block from the titles a repository already writes.

Rite finds a fix's Evidence, a profile's Gates, an item's Files by their titles; a repository that
writes them in another language gets nothing back, silently. This reads the items and profiles, and
recognises each section by what it holds — fenced `$ ` lines, paths that exist, command lines, dated
log lines — never by the words of its title. Every guess comes with its evidence; a key nothing
matches reliably comes out commented, with its candidates. `--write` merges only what matched.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import batch, check as checkmod, compose, config, markdown
from .model import Cycle, Item, Project, RiteError, display

# the keys, in the order they claim titles: a title given to one key is not offered to the next
KEYS = ("execution_log", "evidence", "verification", "files", "scope", "phase_checks",
        "confirmed_decisions", "gates", "serialized_resources", "generated_artifacts")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CHECKBOX = re.compile(r"(?m)^\s*[-*]\s+\[[ xX]\]")
_NAME_BULLET = re.compile(r"^\s*[-*]\s+(?:`[\w.-]+`|[\w.-]+)\s*(?:[—:–-]\s.*)?$")
_BULLET = re.compile(r"^\s*[-*]\s+")
_FIRST_TOKEN = re.compile(r"(?m)^\s*[-*]\s+`?([^\s`]+)")
_HEADER = re.compile(r"^\s*\[\[?\s*[\w.\"' -]+\s*\]\]?\s*(?:#.*)?$")

HOW = {
    "evidence": "the first section with fenced `$ ` lines",
    "verification": "the last section after the evidence with a checkbox, a code span or a command",
    "files": "a fix section listing paths",
    "scope": "a task section listing paths",
    "execution_log": "the last section of the item",
    "phase_checks": "a profile section naming phases",
    "confirmed_decisions": "the first section of the profile",
    "gates": "the profile section with the most command lines",
    "serialized_resources": "a profile section listing only short names",
    "generated_artifacts": "a profile section between the decisions and the gates",
}


@dataclass
class Vote:
    title: str
    file: str
    detail: str = ""


@dataclass
class Tally:
    key: str
    files: int = 0                                           # files of the kind this key reads
    votes: dict[str, list[Vote]] = field(default_factory=dict)
    seen: dict[str, int] = field(default_factory=dict)       # title -> files where it occurs
    hints: dict[str, Vote] = field(default_factory=dict)     # candidates that never get accepted


def h2_sections(text: str) -> list[tuple[str, str]]:
    """(title, body) of each level-2 section, in document order; code blocks are not headings."""
    out: list[tuple[str, list[str]]] = []
    fence = None
    for line in text.splitlines():
        m = markdown._FENCE_RE.match(line)
        if m:
            fence = m.group(1) if fence is None else (None if m.group(1) == fence else fence)
        elif fence is None:
            h = markdown._HEADING_RE.match(line)
            if h and len(h.group(1)) <= 2:
                out.append((h.group(2).strip(), []) if len(h.group(1)) == 2 else ("", []))
                continue
        if out:
            out[-1][1].append(line)
    return [(title, "\n".join(body)) for title, body in out if title]


def _commands(body: str) -> list[str]:
    commands, _, broken = compose._shell_lines(body)
    return commands + broken


def _command_lines(body: str) -> int:
    """How many of the section's gate commands are command lines (hold a space), not names."""
    return sum(1 for c in compose.gate_commands(body) if " " in c)


def _path_bullets(body: str) -> int:
    """Entries that open with a path — bullets, or table rows — when they are most of the section's
    entries; else 0. Prose mentions paths too; a list of them is what a files section is."""
    entries = [m.group(1).rstrip(",;:") for m in _FIRST_TOKEN.finditer(body)]
    for line in body.splitlines():
        if line.strip().startswith("|") and not re.fullmatch(r"[\s|:-]+", line):
            cells = markdown.table_cells(line)
            span = compose.CODE_SPAN.search(cells[0]) if cells else None
            entries.append(span.group(1).strip() if span else (cells[0] if cells else ""))
    hits = sum(1 for token in entries if batch._looks_like_path(token))
    return hits if entries and 2 * hits >= len(entries) else 0


def _table_command_rows(body: str) -> int:
    """Table rows holding a command line — shown as a candidate, never read as gates."""
    return sum(1 for line in body.splitlines() if line.strip().startswith("|")
               and any(" " in m.group(1) for m in compose.CODE_SPAN.finditer(line)))


def _names_only(body: str) -> bool:
    """Every bullet opens with one short name (`display`, `- emulator — one at a time`), not a path."""
    bullets = [line for line in body.splitlines() if _BULLET.match(line)]
    return (bool(bullets) and all(_NAME_BULLET.match(line) for line in bullets)
            and not _path_bullets(body))


class Detector:
    def __init__(self, project: Project, cycles: list[Cycle]):
        self.p = project
        self.cycles = cycles
        self.tallies = {key: Tally(key) for key in KEYS}
        self.taken: set[str] = set()

    # --- voting -----------------------------------------------------------------
    def _see(self, key: str, sections: list[tuple[str, str]]) -> None:
        tally = self.tallies[key]
        tally.files += 1
        for title in {t for t, _ in sections}:
            tally.seen[title] = tally.seen.get(title, 0) + 1

    def _vote(self, key: str, title: str | None, path: Path, detail: str = "") -> None:
        if title:
            self.tallies[key].votes.setdefault(title, []).append(
                Vote(title, display(self.p.root, path), detail))

    def read_fix(self, item: Item) -> None:
        sections = h2_sections(item.body)
        for key in ("evidence", "verification", "files", "execution_log"):
            self._see(key, sections)
        first = next(((i, t, b) for i, (t, b) in enumerate(sections) if _commands(b)), None)
        if first:
            self._vote("evidence", first[1], item.path, f"{len(_commands(first[2]))} `$ ` line(s)")
            later = [(t, b) for t, b in sections[first[0] + 1:-1] if not _path_bullets(b)]
            checked = [t for t, b in later
                       if _CHECKBOX.search(b) or compose.CODE_SPAN.search(b) or _commands(b)]
            if checked:
                self._vote("verification", checked[-1], item.path)
        self._read_item(item, sections, "files")

    def read_task(self, item: Item) -> None:
        sections = h2_sections(item.body)
        for key in ("scope", "execution_log"):
            self._see(key, sections)
        self._read_item(item, sections, "scope")

    def _read_item(self, item: Item, sections: list[tuple[str, str]], paths_key: str) -> None:
        # the last section is the log, whose lines open with the paths a change touched
        found = max(sections[:-1], key=lambda s: _path_bullets(s[1]), default=None)
        if found and _path_bullets(found[1]):
            self._vote(paths_key, found[0], item.path, f"{_path_bullets(found[1])} path(s)")
        if sections:
            title, body = sections[-1]
            self._vote("execution_log", title, item.path, "dated" if _DATE.search(body) else "")

    def read_profile(self, path: Path) -> None:
        sections = h2_sections(path.read_text(encoding="utf-8", errors="replace"))
        for key in ("phase_checks", "confirmed_decisions", "gates", "serialized_resources",
                    "generated_artifacts"):
            self._see(key, sections)
        labels = self.p.section_titles("phase_label")
        phases = max(sections, key=lambda s: len(checkmod.covered_phases(s[1], labels)), default=None)
        if phases and checkmod.covered_phases(phases[1], labels):
            self._vote("phase_checks", phases[0], path,
                       f"{len(checkmod.covered_phases(phases[1], labels))} phase(s)")
        if sections:
            self._vote("confirmed_decisions", sections[0][0], path, "first section")
        gates = max(sections, key=lambda s: _command_lines(s[1]), default=None)
        bullets = _command_lines(gates[1]) if gates else 0
        if bullets:
            self._vote("gates", gates[0], path, f"{bullets} command line(s)")
        table = max(sections, key=lambda s: _table_command_rows(s[1]), default=None)
        rows = _table_command_rows(table[1]) if table else 0
        if rows:
            self.tallies["gates"].hints.setdefault(table[0], Vote(
                table[0], display(self.p.root, path),
                f"a table of {rows} command line(s); gates are read from bullets only — list the "
                "ones every item must pass"))
        # where the gates sit, for the sections around them
        gate_at = (sections.index(table) if rows > bullets else sections.index(gates) if bullets else None)
        # resources sit after the gates in the template; a names-only section there wins
        named = [i for i, (_, b) in enumerate(sections) if i != gate_at and _names_only(b)]
        after = [i for i in named if gate_at is not None and i > gate_at]
        names = sections[(after or named)[0]][0] if named else None
        self._vote("serialized_resources", names, path, "short names")
        between = [t for t, _ in sections[1:gate_at]] if gate_at else []
        for title in between:  # a candidate only: nothing in its body says "generated"
            self._vote("generated_artifacts", title, path, "between decisions and gates")

    # --- verdict ----------------------------------------------------------------
    def run(self) -> dict:
        profiles: dict[Path, None] = {}
        for cycle in self.cycles:
            for item in cycle.items:
                (self.read_fix if item.kind == "fix" else self.read_task)(item)
            if cycle.profile_path.is_file():
                profiles[cycle.profile_path] = None
        for path in profiles:
            self.read_profile(path)
        return {key: self.verdict(key) for key in KEYS}

    def verdict(self, key: str) -> dict:
        tally = self.tallies[key]
        need = min(2, tally.files) or 1
        ranked = sorted(tally.votes.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        accepted, candidates = [], []
        for title, votes in ranked:
            entry = {"title": title, "votes": len(votes), "occurs": tally.seen.get(title, 0),
                     "example": votes[0].file, "detail": votes[0].detail}
            # the most voted title, and any other that holds its signal in most files where it occurs;
            # generated_artifacts is never accepted: its position is all there is to go on
            share = title == ranked[0][0] or 2 * len(votes) >= tally.seen.get(title, len(votes))
            reliable = (key != "generated_artifacts" and title not in self.taken
                        and len(votes) >= need and share)
            (accepted if reliable else candidates).append(entry)
        candidates += [{"title": v.title, "votes": 0, "occurs": tally.seen.get(v.title, 0),
                        "example": v.file, "detail": v.detail}
                       for v in tally.hints.values() if v.title not in tally.votes]
        candidates = [c for c in candidates if c["title"] not in self.taken]  # another key has it
        self.taken.update(e["title"] for e in accepted)
        current = self.p.section_titles(key)
        explicit = key in _user_sections(self.p)
        detected = [e["title"] for e in accepted]
        if explicit:  # what the user wrote stays first; detection only adds
            titles = [*current, *(t for t in detected if t not in current)]
        else:
            titles = detected or current
        return {"titles": titles, "current": current, "confident": bool(accepted),
                "changed": bool(accepted) and titles != current, "how": HOW[key],
                "files": tally.files, "evidence": accepted, "candidates": candidates}


def _user_sections(project: Project) -> dict:
    file = project.root / config.CONFIG_NAME
    try:
        return tomllib.loads(file.read_text(encoding="utf-8")).get("sections", {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def toml_value(titles: list[str]) -> str:
    quoted = [json.dumps(t, ensure_ascii=False) for t in titles]
    return quoted[0] if len(quoted) == 1 else "[" + ", ".join(quoted) + "]"


def detect(project: Project, cycles: list[Cycle]) -> dict:
    keys = Detector(project, cycles).run()
    return {"cycles": [c.name for c in cycles], "keys": keys, "block": render_block(project, keys)}


def render_block(project: Project, keys: dict) -> str:
    lines = ["[sections]"]
    order = [k for k in config.DEFAULTS["sections"] if k != "phase_label"]
    lines.append(f"phase_label = {toml_value(project.section_titles('phase_label'))}  # not detected")
    for key in order:
        v = keys[key]
        if v["confident"]:
            proof = "; ".join(f"{json.dumps(e['title'], ensure_ascii=False)}: {e['votes']} of {v['files']}"
                              f" (e.g. {e['example']}{', ' + e['detail'] if e['detail'] else ''})"
                              for e in v["evidence"])
            lines += [f"# {key} — {v['how']}: {proof}", f"{key} = {toml_value(v['titles'])}"]
        else:
            seen = ", ".join(f"{json.dumps(e['title'], ensure_ascii=False)} "
                             f"({e['votes'] or e['detail']})" for e in v["candidates"][:5]) or "none"
            lines += [f"# {key} — {v['how']}: no reliable match; candidates: {seen}",
                      f"# {key} = {toml_value(v['current'])}"]
    return "\n".join(lines) + "\n"


# --- --write ---------------------------------------------------------------------
def _split_comment(value: str) -> tuple[str, str]:
    """(value, trailing comment) of the text after `=`, with `#` inside a string left alone."""
    quote = None
    i = 0
    while i < len(value):
        ch = value[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return value[:i].rstrip(), value[i:]
        i += 1
    return value.rstrip(), ""


def merge(text: str, values: dict[str, list[str]]) -> str:
    """``text`` (a rite.toml) with each key of ``values`` set in `[sections]`, and nothing else
    changed: comments, other keys, their order and alignment stay."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r"^\s*\[sections\]\s*(?:#.*)?$", line)), None)
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "[sections]", *(f"{k} = {toml_value(v)}" for k, v in values.items())]
        return "\n".join(lines) + "\n"
    end = next((i for i in range(start + 1, len(lines)) if _HEADER.match(lines[i])), len(lines))
    pending = dict(values)
    i = start + 1
    while i < end:
        m = re.match(r"^(\s*)([A-Za-z0-9_-]+)(\s*=\s*)(.*)$", lines[i])
        if not m or m.group(2) not in pending:
            i += 1
            continue
        last = i
        if m.group(4).lstrip().startswith("[") and "]" not in _split_comment(m.group(4))[0]:
            while last + 1 < end and "]" not in _split_comment(lines[last])[0]:
                last += 1
        comment = _split_comment(lines[last] if last != i else m.group(4))[1]
        new = f"{m.group(1)}{m.group(2)}{m.group(3)}{toml_value(pending.pop(m.group(2)))}"
        lines[i:last + 1] = [f"{new}  {comment}" if comment else new]
        end -= last - i
        i += 1
    at = end
    while at > start + 1 and not lines[at - 1].strip():
        at -= 1
    lines[at:at] = [f"{k} = {toml_value(v)}" for k, v in pending.items()]
    return "\n".join(lines) + "\n"


def write(project: Project, keys: dict) -> dict:
    """Merge the keys detection is sure of into rite.toml; what it read back must be what it meant."""
    values = {k: v["titles"] for k, v in keys.items() if v["changed"]}
    file = project.root / config.CONFIG_NAME
    if not values:
        return {"file": display(project.root, file), "written": {}}
    text = file.read_text(encoding="utf-8")
    new = merge(text, values)
    parsed = config.parse(project.root, new)
    for key, titles in values.items():
        got = parsed["sections"][key]
        if (got if isinstance(got, list) else [got]) != titles:
            raise RiteError(f"merging [sections].{key} into {config.CONFIG_NAME} read back {got!r}")
    file.write_text(new, encoding="utf-8", newline="\n")
    return {"file": display(project.root, file), "written": values}
