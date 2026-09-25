"""`rite.py check` — conventions made mechanical."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import gitutil, markdown, views
from .config import FIX_STATUSES, NO_COMMIT, SEVERITIES, TASK_STATUSES
from .model import Cycle, Item, Project, RiteError, display, resolve_link

REQUIRED = {
    "task": ("id", "title", "type", "phase", "depends_on", "source_of_truth", "status",
             "done_on", "done_commit", "reviewed_on"),
    "fix": ("id", "title", "origin", "severity", "status", "depends_on", "done_on", "done_commit"),
}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# a script an evidence line runs: `python x.py`, `bash tools/x.sh`, `node x.mjs`, `./x`
_SCRIPT_RE = re.compile(r"""(?:^|[;&|(]\s*|\s)(?:(?:python3?|py|sh|bash|node|ruby|perl)\s+(?:-\S+\s+)*"""
                        r"""([^\s;&|<>'"-][^\s;&|<>'"]*\.(?:py|sh|mjs|cjs|js|rb|pl))"""
                        r"""|\./([^\s;&|<>'"]+))""")
# a commit named by its hash: hex with a letter and a digit, so neither `deadbeef` nor `1234567`
_SHA = re.compile(r"(?<![\w/-])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![\w-])")
_GIT_AT = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:show|log|ls-tree|cat-file|blame|archive)\b")
_GIT_DIFF = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?diff\b")
# a revision range as one argument: `a..b`, `a...b`, either side possibly empty
_RANGE = re.compile(r"(\S*?)\.\.\.?(\S*)")
_PY_HEREDOC = re.compile(r"""\bpython3?\s+-\s*<<-?\s*(['"]?)([A-Za-z_][\w-]*)\1""")


def _dynamic(path: str) -> bool:
    """A path the shell builds (`$DIR/x.py`, `~/x`, `<placeholder>`), or an absolute one."""
    return not path or any(c in path for c in "$~<>{}*") or path.startswith(("/", "\\")) or ":" in path


def _pinned(command: str) -> bool:
    """A command that reads a commit named by its hash prints the same before and after a repair.
    `git diff <sha>` alone compares with the working tree, so a diff needs two revisions. A range
    is fixed only between two hashes: one with `HEAD`, a branch, a tag or an empty side
    (`<sha>..HEAD`, `<sha>...main`, `<sha>..`) moves with the repository, so it is dropped."""
    kept, fixed_range = [], False
    for token in command.split():
        m = _RANGE.fullmatch(token)
        if not m:
            kept.append(token)
        elif _SHA.fullmatch(m.group(1)) and _SHA.fullmatch(m.group(2)):
            fixed_range = True
            kept.append(token)
    shas = _SHA.findall(" ".join(kept))
    if not shas:
        return False
    if _GIT_AT.search(command):
        return True
    return bool(_GIT_DIFF.search(command)) and (len(shas) > 1 or fixed_range)


def _python_heredoc(command: str) -> str | None:
    """The body of a `python - <<EOF` heredoc in ``command``, else None."""
    m = _PY_HEREDOC.search(command.splitlines()[0])
    if not m:
        return None
    lines = command.splitlines()[1:]
    return "\n".join(lines[:-1] if lines and lines[-1].strip() == m.group(2) else lines)


def label_pattern(labels) -> str:
    """A regex alternation of the phase labels (`[sections].phase_label`, a title or a list)."""
    labels = [labels] if isinstance(labels, str) else labels
    return "(?:" + "|".join(re.escape(label) for label in labels) + ")"


def covered_phases(body: str, labels) -> set[str]:
    """Phases a profile's phase-checks section has entries for.

    Accepts single phases ("Phase 3") and ranges ("Phase 4-5", "Phase 6–7"): one entry often covers
    phases that share their checks.
    """
    covered: set[str] = set()
    rx = re.compile(rf"(?i)\b{label_pattern(labels)}s?\s+(\w+)(?:\s*[-–]\s*(\d+))?\b")
    for m in rx.finditer(body):
        first, last = m.group(1), m.group(2)
        if last and first.isdigit() and int(first) <= int(last):
            covered.update(str(n) for n in range(int(first), int(last) + 1))
        else:
            covered.add(first)
    return covered


@dataclass
class Finding:
    level: str  # "error" | "warn"
    path: str
    message: str
    line: int | None = None

    def __str__(self) -> str:
        loc = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.level.upper():5} {loc}: {self.message}"


class Checker:
    def __init__(self, project: Project, *, quick: bool = False):
        self.p = project
        self.quick = quick
        self.findings: list[Finding] = []
        self.git = not project.workspace and not quick
        # a workspace with no repository under it has nothing to check commits against
        self.bare = project.workspace and not project.repos()

    def err(self, path: Path, msg: str, line: int | None = None) -> None:
        self.findings.append(Finding("error", display(self.p.root, path), msg, line))

    def warn(self, path: Path, msg: str, line: int | None = None) -> None:
        self.findings.append(Finding("warn", display(self.p.root, path), msg, line))

    # ------------------------------------------------------------------
    def run(self, cycles: list[Cycle]) -> list[Finding]:
        if self.bare and not self.quick:
            self.warn(self.p.root / "rite.toml", "not a git repository and none under it; commit checks skipped")
        all_cycles = self.p.all_cycles()
        owner = {i.id: c for c in all_cycles for i in c.items}
        seen: dict[tuple[str, str], Path] = {}
        for c in all_cycles:  # IDs must be unique across live and archived cycles
            for i in c.items:
                key = (i.kind, i.id)
                if key in seen and seen[key] != i.path:
                    self.err(i.path, f"duplicate ID {i.id} (also {display(self.p.root, seen[key])})")
                seen.setdefault(key, i.path)
        for cycle in cycles:
            self.check_cycle(cycle, owner)
        return self.findings

    def check_cycle(self, cycle: Cycle, owner: dict[str, Cycle]) -> None:
        if not cycle.prefix:
            self.err(cycle.progress_path, "frontmatter lacks 'prefix'")
        if "order" in cycle.meta and not isinstance(cycle.meta["order"], list):
            self.err(cycle.progress_path, "'order' must be a list of task IDs")
        if cycle.meta.get("local") not in (None, True, False):
            self.err(cycle.progress_path, f"'local' must be true or false, not {cycle.meta['local']!r}")
        if cycle.meta.get("ticket") is not None and not isinstance(cycle.meta["ticket"], str):
            self.err(cycle.progress_path, f"'ticket' must be a string, not {cycle.meta['ticket']!r}")
        if self.git:
            self.check_tracking(cycle)
        task_ids = {t.id for t in cycle.tasks}
        seen_order: set[str] = set()
        for item_id in cycle.order:
            if item_id in seen_order:
                self.err(cycle.progress_path, f"'order' lists {item_id} twice")
            elif item_id not in task_ids:
                self.err(cycle.progress_path, f"'order' lists {item_id}, which is not a task of this cycle")
            seen_order.add(item_id)
        for path in views.out_of_sync(self.p, cycle):
            self.err(path, "generated table out of sync with item frontmatter (run: rite.py sync)")
        index = cycle.by_id()
        for item in cycle.items:
            self.check_item(cycle, item, index, owner)
        self.check_cycles_in_graph(cycle, index)
        if not self.quick:
            self.check_profile(cycle)
            self.check_fix_sections(cycle)
            for f in [cycle.progress_path, cycle.fixes_path, *(i.path for i in cycle.items)]:
                if f.is_file():
                    self.check_links(f)

    def check_item(self, cycle: Cycle, item: Item, index: dict[str, Item], owner: dict[str, Cycle]) -> None:
        if item.parse_error:
            self.err(item.path, f"frontmatter: {item.parse_error}")
            return
        f = item.fields
        if not f:
            self.err(item.path, "missing frontmatter")
            return
        for key in REQUIRED[item.kind]:
            if key not in f:
                self.err(item.path, f"missing field '{key}'")
        parsed = self.p.naming.parse_id(str(f.get("id", "")))
        if not parsed or parsed[0] != item.kind:
            self.err(item.path, f"id {f.get('id')!r} does not match [naming].{item.kind}_id")
        else:
            groups = parsed[1]
            if groups.get("prefix") and cycle.prefix and groups["prefix"] != cycle.prefix:
                # when [naming] declares lists, a cycle may legitimately hold items an earlier convention
                # named with another prefix; with single templates, a stray prefix is a typo
                n = self.p.naming
                single = all(len(tpls) == 1 for tpls in
                             (n.task_id_tpls, n.fix_id_tpls, n.task_file_tpls, n.fix_file_tpls))
                report = self.err if single else self.warn
                report(item.path, f"id prefix {groups['prefix']} differs from cycle prefix {cycle.prefix}")
            if int(groups["n"]) != item.n:
                self.err(item.path, f"id number {groups['n']} differs from file name number {item.n}")

        statuses = TASK_STATUSES if item.kind == "task" else FIX_STATUSES
        if item.status not in statuses:
            self.err(item.path, f"status {item.status!r} not in {list(statuses)}")
        if item.kind == "task":
            types = self.p.cfg["vocab"]["task_types"]
            if types and f.get("type") not in types:
                self.err(item.path, f"type {f.get('type')!r} not in [vocab].task_types")
            self.check_source_of_truth(item)
            self.check_review_state(item)
        else:
            if f.get("severity") not in SEVERITIES:
                self.err(item.path, f"severity {f.get('severity')!r} not in {list(SEVERITIES)}")
            origin = str(f.get("origin") or "")
            if origin not in index:
                where = owner.get(origin)
                self.err(item.path, f"origin {origin or '(empty)'} "
                         + (f"belongs to cycle {where.name}" if where else "does not exist"))

        for dep in item.depends_on:
            if dep == item.id:
                self.err(item.path, "depends_on itself")
            elif dep not in index:
                where = owner.get(dep)
                self.err(item.path, f"depends_on {dep} "
                         + (f"crosses into cycle {where.name}; dependencies stay inside a cycle"
                            if where else "does not exist"))

        self.check_repo(item)
        self.check_done_state(item)

    def git_root(self, item: Item) -> Path | None:
        """Where the item's commits are checked; None when they cannot be (reported by check_repo)."""
        if self.quick or self.bare:
            return None
        try:
            return self.p.git_root(item)
        except RiteError:  # reported by check_repo
            return None

    def check_repo(self, item: Item) -> None:
        if self.bare:
            return
        repo = item.fields.get("repo")
        if repo is not None and not isinstance(repo, str):
            self.err(item.path, f"'repo' must be a folder name, not {repo!r}")
            return
        try:
            self.p.git_root(item)
        except RiteError as exc:
            self.err(item.path, str(exc).removeprefix(f"{item.id}: "))

    def check_done_state(self, item: Item) -> None:
        f = item.fields
        done_like = item.status == "done" or item.status == "stale"
        for key in ("done_on",):
            val = f.get(key)
            if done_like and not (val and _DATE_RE.match(str(val))):
                self.err(item.path, f"status {item.status} needs {key} as YYYY-MM-DD (use rite.py close)")
            if not done_like and val not in (None, ""):
                self.err(item.path, f"{key} is set but status is {item.status}")
        sha = f.get("done_commit")
        if item.status == "done":
            if not sha:
                self.err(item.path, "status done without done_commit (use rite.py close)")
            elif str(sha) == NO_COMMIT:  # closed with --no-repo: nothing to resolve
                pass
            elif (root := self.git_root(item)) is None:
                pass
            elif not gitutil.resolve(root, str(sha)):
                self.err(item.path, f"done_commit {sha} is not a commit in {item.repo or 'this repository'} "
                         f"(rewritten by a squash or rebase? rite.py rebind {item.id} --sha <commit>)")
            elif not gitutil.is_ancestor(root, str(sha), "HEAD"):
                # a warning: the commit may sit on another branch; a rewritten one lingers until gc
                self.warn(item.path, f"done_commit {sha} is not in the history of HEAD (squashed or rebased? "
                          f"rite.py rebind {item.id} --sha <commit>; or it lives on another branch)")

    def check_tracking(self, cycle: Cycle) -> None:
        """A local cycle's folder should be ignored by git, a tracked one's should not."""
        ignored = gitutil.is_ignored(self.p.root, cycle.progress_path)
        if cycle.local and not ignored:
            self.warn(cycle.progress_path, "cycle is local but git does not ignore its folder; "
                      "its documents can slip into a commit (add the folder to .gitignore)")
        elif not cycle.local and ignored:
            self.warn(cycle.progress_path, "git ignores this cycle's folder but it is not 'local: true'; "
                      "bookkeeping commits will fail (set local: true, or stop ignoring it)")

    def check_review_state(self, item: Item) -> None:
        rv = item.fields.get("reviewed_on")
        if item.status == "done":
            if rv is None:
                self.err(item.path, "done task with reviewed_on null; expected 'pending' or a date")
            elif rv != "pending" and not _DATE_RE.match(str(rv)):
                self.err(item.path, f"reviewed_on {rv!r} is neither 'pending' nor YYYY-MM-DD")
        elif rv not in (None, ""):
            self.err(item.path, f"reviewed_on set but status is {item.status}")

    def check_source_of_truth(self, item: Item) -> None:
        sot = item.fields.get("source_of_truth")
        if not sot:
            self.err(item.path, "source_of_truth is empty")
            return
        self.check_target(item.path, str(sot), "source_of_truth", None)

    def check_target(self, file: Path, target: str, what: str, line: int | None) -> None:
        style = self.p.cfg.link_style
        path_part = target.split("#", 1)[0]
        if path_part:
            if style == "root-absolute" and not path_part.startswith("/"):
                self.err(file, f"{what} {target!r} must be root-absolute (start with '/')", line)
            elif style == "relative" and path_part.startswith("/"):
                self.err(file, f"{what} {target!r} must be relative ([paths].link_style = relative)", line)
        path, anchor = resolve_link(self.p.root, file, target)
        if not path.exists():
            self.err(file, f"{what} {target!r} points to a missing file", line)
            return
        if anchor and path.is_file() and path.suffix == ".md" and not markdown.has_anchor(path, anchor):
            self.err(file, f"{what} {target!r}: no heading/anchor '#{anchor}' in {path.name}", line)

    def check_links(self, file: Path) -> None:
        text = file.read_text(encoding="utf-8", errors="replace")
        for line, target in markdown.links(text):
            if markdown.is_external(target):
                continue
            self.check_target(file, target, "link", line)

    def check_cycles_in_graph(self, cycle: Cycle, index: dict[str, Item]) -> None:
        state: dict[str, int] = {}

        def visit(node: str, trail: list[str]) -> None:
            if state.get(node) == 2 or node not in index:
                return
            if state.get(node) == 1:
                loop = trail[trail.index(node):] + [node]
                self.err(index[node].path, "dependency cycle: " + " -> ".join(loop))
                return
            state[node] = 1
            for dep in index[node].depends_on:
                visit(dep, trail + [node])
            state[node] = 2

        for node in index:
            visit(node, [])

    def check_fix_sections(self, cycle: Cycle) -> None:
        """An open fix with neither an evidence nor a verification title reproduces as "nothing to
        run" — which reads like a clean fix. A warning: a legacy repository is like this until its
        `[sections]` names its own titles (`rite.py sections` proposes them)."""
        titles = [*self.p.section_titles("evidence"), *self.p.section_titles("verification")]
        for fix in cycle.fixes:
            if fix.status not in ("pending", "in-progress"):
                continue
            if markdown.first_section(fix.body, titles) is None:
                near = "".join(f"; near: '{h}'" for h in markdown.near_headings(fix.body, titles))
                self.warn(fix.path, "no section titled " + " / ".join(f"'{t}'" for t in titles)
                          + f": reproduce finds no command (set [sections].evidence / verification){near}")
            else:
                self.check_evidence_runs(fix)

    def check_evidence_runs(self, fix: Item) -> None:
        """Evidence must run from the repository as written. Two ways it was seen not to: a script
        that lived in a reviewer's scratch copy (`python run.py`), and a `python -` heredoc whose body
        is the output it printed. Warnings: a script an earlier `$` line creates is not seen.
        Evidence must also be able to pass once fixed: a command over a pinned git revision prints
        the same after the repair, so the fix would reproduce forever."""
        from . import compose  # compose imports this module
        try:
            root = self.p.git_root(fix)
        except RiteError:
            root = self.p.root
        for key in ("evidence", "verification"):
            found = markdown.first_section(fix.body, self.p.section_titles(key))
            if not found:
                continue
            moved = False  # after a `cd`, relative paths are no longer the repository's
            for command in compose._shell_lines(found[1])[0]:
                first = command.splitlines()[0]
                moved = moved or bool(re.search(r"(?:^|[;&|]\s*)cd\s", command))
                if not moved:
                    for script in (a or b for a, b in _SCRIPT_RE.findall(first)):
                        if not _dynamic(script) and not (root / script).exists():
                            self.warn(fix.path, f"'{found[0]}' runs `{script}`, which is not in the repository: "
                                      "evidence must run from HEAD as written")
                if _pinned(command):
                    self.warn(fix.path, f"'{found[0]}' runs `{first}`, which reads a fixed git revision: "
                              "it documents, never verifies — add a command over the working tree")
                body = _python_heredoc(command)
                if body is not None:
                    try:
                        compile(body, "<evidence>", "exec")
                    except SyntaxError as exc:
                        self.warn(fix.path, f"'{found[0]}' pipes into python a heredoc that is not Python "
                                  f"(line {exc.lineno}: {(exc.text or '').strip()[:60]!r}) — its output in "
                                  "place of its script?")

    def check_profile(self, cycle: Cycle) -> None:
        prof = cycle.profile_path
        if not prof.is_file():
            if not cycle.archived:
                self.warn(cycle.progress_path, f"profile {display(self.p.root, prof)} not found")
            return
        limit = int(self.p.cfg["profile"]["max_kb"]) * 1024
        size = prof.stat().st_size
        if limit and size > limit:
            self.err(prof, f"profile is {size // 1024} KB > [profile].max_kb {limit // 1024} KB; "
                     "move measured pitfalls to the pitfalls file (/rite:retro compacts)")
        text = prof.read_text(encoding="utf-8", errors="replace")
        self.check_links(prof)
        if not cycle.archived and markdown.first_section(text, self.p.section_titles("gates")) is None:
            self.warn(prof, "no section titled " + " / ".join(f"'{t}'" for t in self.p.section_titles("gates"))
                      + ": `rite.py gates` runs only [gates].global (set [sections].gates)")
        found = markdown.first_section(text, self.p.section_titles("phase_checks"))
        heading = found[0] if found else self.p.section_title("phase_checks")
        # template hints are not entries
        body = re.sub(r"<!--.*?-->", "", found[1], flags=re.DOTALL) if found else None
        phases = sorted({str(t.fields.get("phase")) for t in cycle.tasks if t.fields.get("phase") is not None})
        if body is None:
            if phases:
                self.err(prof, f"missing section '{heading}' (tasks use phases {', '.join(phases)})")
            return
        covered = covered_phases(body, self.p.section_titles("phase_label"))
        for ph in phases:
            if ph not in covered:
                self.err(prof, f"'{heading}' has no entry for phase {ph}")


def run(project: Project, cycles: list[Cycle], *, quick: bool = False) -> list[Finding]:
    return Checker(project, quick=quick).run(cycles)

