"""Cycles and items (tasks, fixes) as read from disk. The cycle's JSON files are the only state."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter, gitutil, state
from .config import Config, SEVERITIES
from .naming import Naming, as_list


class RiteError(Exception):
    """User-facing error; the CLI prints it and exits non-zero."""


@dataclass
class Item:
    kind: str  # "task" | "fix"
    path: Path
    n: int
    fields: dict = field(default_factory=dict)
    parse_error: str | None = None
    state_path: Path | None = None  # the JSON file holding this item's fields
    file: str = ""  # path of the markdown file, relative to the cycle folder, as the JSON names it
    _md: tuple | None = field(default=None, repr=False)

    def read_md(self) -> tuple[dict, str, str | None]:
        """(frontmatter, body, error) of the item's markdown file, read once."""
        if self._md is None:
            try:
                fields, body = frontmatter.parse(self.path.read_text(encoding="utf-8"))
                self._md = (fields, body, None)
            except FileNotFoundError:
                self._md = ({}, "", "file not found")
            except (frontmatter.FrontmatterError, UnicodeDecodeError) as exc:
                self._md = ({}, "", str(exc))
        return self._md

    @property
    def body(self) -> str:
        return self.read_md()[1]

    @property
    def id(self) -> str:
        return str(self.fields.get("id") or f"<{self.path.name}>")

    @property
    def title(self) -> str:
        return str(self.fields.get("title") or "")

    @property
    def status(self) -> str:
        return str(self.fields.get("status") or "")

    @property
    def depends_on(self) -> list[str]:
        deps = self.fields.get("depends_on") or []
        return [str(d) for d in deps] if isinstance(deps, list) else [str(deps)]

    @property
    def repo(self) -> str | None:
        """Folder (under the root) of the git repository this item's work lands in."""
        value = self.fields.get("repo")
        return str(value).strip().strip("/") or None if value is not None else None

    @property
    def severity_rank(self) -> int:
        sev = self.fields.get("severity")
        return SEVERITIES.index(sev) if sev in SEVERITIES else len(SEVERITIES)


@dataclass
class Cycle:
    name: str
    path: Path
    progress_path: Path
    fixes_path: Path
    progress_state_path: Path
    fixes_state_path: Path
    meta: dict
    archived: bool
    profile_path: Path
    pitfalls_path: Path
    items: list[Item] = field(default_factory=list)
    workspace: bool = False  # rite.toml lives outside git; every cycle is then local

    @property
    def prefix(self) -> str:
        return str(self.meta.get("prefix") or "")

    @property
    def tasks(self) -> list[Item]:
        """Tasks in execution order: IDs listed in the progress file's `order:` first, in that order;
        the rest by number. Why a list: a task split late gets a new, higher ID but must run before
        tasks numbered below it, and renumbering would break every link to them."""
        pos = {item_id: k for k, item_id in enumerate(self.order)}
        return sorted((i for i in self.items if i.kind == "task"),
                      key=lambda i: (0, pos[i.id], 0) if i.id in pos else (1, i.n, 0))

    @property
    def order(self) -> list[str]:
        value = self.meta.get("order") or []
        return [str(v) for v in value] if isinstance(value, list) else []

    @property
    def ticket(self) -> str | None:
        """External tracker key (e.g. a JIRA issue) the cycle's commits carry."""
        value = self.meta.get("ticket")
        return str(value).strip() or None if value is not None else None

    @property
    def local(self) -> bool:
        """A local cycle keeps its documents out of git: no bookkeeping commits, no item refs.
        In a workspace there is no repository to hold them, so every cycle is local."""
        return self.workspace or self.meta.get("local") is True

    @property
    def fixes(self) -> list[Item]:
        return sorted((i for i in self.items if i.kind == "fix"), key=lambda i: i.n)

    def by_id(self) -> dict[str, Item]:
        return {i.id: i for i in self.items}


def resolve_link(root: Path, from_file: Path, target: str) -> tuple[Path, str]:
    """Resolve a markdown link target to (path, anchor)."""
    target, _, anchor = target.partition("#")
    if not target:
        return from_file, anchor
    if target.startswith("/"):
        return (root / target.lstrip("/")).resolve(), anchor
    return (from_file.parent / target).resolve(), anchor


def make_link(root: Path, from_file: Path, target: Path, style: str) -> str:
    if style == "root-absolute":
        return "/" + target.resolve().relative_to(root).as_posix()
    return Path(os.path.relpath(target.resolve(), from_file.resolve().parent)).as_posix()


def display(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


class Project:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.root = cfg.root
        self.naming = Naming(cfg["naming"])
        self.cycles_root = cfg.path("cycles_root")
        self.archive_dir = cfg.path("archive_dir")
        self.progress_name = cfg["naming"]["progress_file"]
        self.fixes_name = cfg["naming"]["fixes_file"]
        self.progress_state = cfg["naming"]["progress_state"]
        self.fixes_state = cfg["naming"]["fixes_state"]
        # a workspace: rite.toml in a plain folder whose sub-folders are git repositories
        self.workspace = not gitutil.is_repo(self.root)
        self._git_ok: dict[Path, bool] = {}

    # --- section titles ----------------------------------------------------
    def section_titles(self, key: str) -> list[str]:
        """Every title `[sections].<key>` accepts, the one Rite writes first."""
        return as_list(self.cfg["sections"][key])

    def section_title(self, key: str) -> str:
        """The title Rite writes for `[sections].<key>`."""
        return self.section_titles(key)[0]

    # --- repositories ------------------------------------------------------
    def repos(self) -> list[str]:
        """Immediate sub-folders that are git repositories (the projects of a workspace)."""
        if not self.root.is_dir():
            return []
        return [p.name for p in sorted(self.root.iterdir()) if p.is_dir() and (p / ".git").exists()]

    def is_git(self, path: Path) -> bool:
        if path not in self._git_ok:
            self._git_ok[path] = path.is_dir() and gitutil.is_repo(path)
        return self._git_ok[path]

    def git_root(self, item: Item) -> Path:
        """The repository an item's work commits live in: its `repo:` folder, or the root itself."""
        if item.repo:
            path = (self.root / item.repo).resolve()
            if not self.is_git(path):
                raise RiteError(f"{item.id}: repo {item.repo!r} is not a git repository under "
                                f"{self.root} (repositories here: {', '.join(self.repos()) or 'none'})")
            return path
        if self.workspace:
            raise RiteError(f"{item.id} has no 'repo:'. rite.toml is outside git (a workspace), so each item "
                            f"names the repository its work lands in: {', '.join(self.repos()) or 'none found'}")
        return self.root

    # --- discovery -------------------------------------------------------
    def is_cycle_dir(self, path: Path) -> bool:
        """A cycle is a folder holding its JSON state — or, not yet migrated, its progress markdown."""
        return (path / self.progress_state).is_file() or (path / self.progress_name).is_file()

    def is_legacy_dir(self, path: Path) -> bool:
        """A cycle from before the JSON state: progress markdown with frontmatter, no progress JSON."""
        return (path / self.progress_name).is_file() and not (path / self.progress_state).is_file()

    def _cycle_dirs(self, base: Path) -> list[Path]:
        if not base.is_dir():
            return []
        found = []
        if self.is_cycle_dir(base) and base != self.archive_dir:
            found.append(base)
        for child in sorted(base.iterdir()):
            if child.is_dir() and child.resolve() != self.archive_dir and self.is_cycle_dir(child):
                found.append(child)
        return found

    def live_cycles(self) -> list[Cycle]:
        return [self.load_cycle(p) for p in self._cycle_dirs(self.cycles_root)]

    def archived_dirs(self) -> list[Path]:
        if not self.archive_dir.is_dir():
            return []
        # a legacy archive folder may itself be one closed cycle
        dirs = [self.archive_dir] if self.is_cycle_dir(self.archive_dir) else []
        return dirs + [p for p in sorted(self.archive_dir.iterdir()) if p.is_dir() and self.is_cycle_dir(p)]

    def archived_cycles(self) -> list[Cycle]:
        return [self.load_cycle(p, archived=True) for p in self.archived_dirs()]

    def all_cycles(self) -> list[Cycle]:
        return self.live_cycles() + self.archived_cycles()

    def cycle_paths(self, path: Path, meta: dict) -> tuple[Path, Path]:
        """(profile, pitfalls) of the cycle in ``path``: named by its meta, else by [naming]."""
        progress = path / self.progress_name
        name = str(meta.get("cycle") or path.name)
        naming = self.cfg["naming"]
        if meta.get("profile"):
            profile, _ = resolve_link(self.root, progress, str(meta["profile"]))
        else:
            profile = self.cfg.path("profiles_dir") / naming["profile_file"].format(cycle=name)
        pitfalls = profile.with_name(naming["pitfalls_file"].format(cycle=name)) \
            if not meta.get("pitfalls") else resolve_link(self.root, progress, str(meta["pitfalls"]))[0]
        return profile, pitfalls

    def load_cycle(self, path: Path, archived: bool | None = None) -> Cycle:
        path = path.resolve()
        if self.is_legacy_dir(path):
            raise RiteError(f"{display(self.root, path)} is a cycle from before the JSON state (no "
                            f"{self.progress_state}): run `rite migrate --from frontmatter`, then again with --write")
        try:
            progress = state.read(path / self.progress_state)
        except state.StateError as exc:
            raise RiteError(str(exc)) from exc
        try:
            fixes = state.read(path / self.fixes_state)
        except FileNotFoundError:
            fixes = state.new_fixes(str(progress.get("cycle") or path.name))
        except state.StateError as exc:
            raise RiteError(str(exc)) from exc
        return self.cycle_from_state(path, progress, fixes, archived=archived)

    def cycle_from_state(self, path: Path, progress: dict, fixes: dict, archived: bool | None = None) -> Cycle:
        """A cycle built from its two JSON documents (read from disk, or about to be written)."""
        path = path.resolve()
        meta = state.meta_of(progress)
        if archived is None:
            archived = self.archive_dir in path.parents
        profile, pitfalls = self.cycle_paths(path, meta)
        cycle = Cycle(
            name=str(meta.get("cycle") or path.name), path=path,
            progress_path=path / self.progress_name, fixes_path=path / self.fixes_name,
            progress_state_path=path / self.progress_state, fixes_state_path=path / self.fixes_state,
            meta=meta, archived=archived, profile_path=profile, pitfalls_path=pitfalls,
            workspace=self.workspace,
        )
        cycle.items = [self._item_from_entry(cycle, "task", e) for e in progress.get(state.TASKS) or []] \
            + [self._item_from_entry(cycle, "fix", e) for e in fixes.get(state.FIXES) or []]
        return cycle

    def _item_from_entry(self, cycle: Cycle, kind: str, entry) -> Item:
        state_path = cycle.progress_state_path if kind == "task" else cycle.fixes_state_path
        if not isinstance(entry, dict):
            return Item(kind=kind, path=state_path, n=0, parse_error=f"entry {entry!r} is not an object",
                        state_path=state_path)
        rel = str(entry.get("file") or "")
        fields = {k: v for k, v in entry.items() if k != "file"}
        item = Item(kind=kind, path=cycle.path / rel if rel else state_path, n=0, fields=fields,
                    state_path=state_path, file=rel)
        m = self.naming.match_file(kind, rel) if rel else None
        if not rel:
            item.parse_error = "entry has no 'file'"
        elif not m:
            item.parse_error = f"file {rel!r} does not match [naming].{kind}_file"
        else:
            item.n = int(m.group("n"))
        return item

    def item_files(self, cycle_dir: Path) -> list[tuple[str, Path, int]]:
        """Markdown files under ``cycle_dir`` that [naming] recognizes as items: [(kind, path, n)].
        Nested cycles (and the archive) are not part of this cycle."""
        found = []
        skip = {self.progress_name, self.fixes_name}
        for dirpath, dirnames, filenames in os.walk(cycle_dir):
            current = Path(dirpath)
            dirnames[:] = sorted(
                d for d in dirnames
                if (current / d).resolve() != self.archive_dir and not self.is_cycle_dir(current / d)
            )
            for fname in sorted(filenames):
                if fname in skip or not fname.endswith(".md"):
                    continue
                file = current / fname
                rel = file.relative_to(cycle_dir).as_posix()
                for kind in ("fix", "task"):
                    m = self.naming.match_file(kind, rel)
                    if m:
                        found.append((kind, file, int(m.group("n"))))
                        break
        return found

    def entry_n(self, kind: str, entry: dict) -> int:
        m = self.naming.match_file(kind, str(entry.get("file") or ""))
        return int(m.group("n")) if m else 0

    def execution_key(self, order: list[str]):
        """Sort key of task entries: the IDs `order:` lists first, in that order; the rest by number.
        The same rule as `Cycle.tasks`, applied to the JSON array so it reads in execution order."""
        pos = {item_id: k for k, item_id in enumerate(order)}

        def key(entry: dict):
            item_id = entry.get("id")
            return (0, pos[item_id]) if item_id in pos else (1, self.entry_n("task", entry))
        return key

    # --- resolution ------------------------------------------------------
    def resolve_cycle(self, arg: str | None = None) -> Cycle:
        """The old "Step 0": argument > default_cycle > flat layout > single live cycle."""
        live = self._cycle_dirs(self.cycles_root)
        if arg:
            candidates = [Path(arg), self.root / arg, self.cycles_root / arg, self.archive_dir / arg]
            for cand in candidates:
                if cand.is_dir() and self.is_cycle_dir(cand):
                    return self.load_cycle(cand)
            # by the name its progress file declares — live first, then archived (a legacy archive
            # folder can itself be one closed cycle whose name is not its folder's)
            for cycle in [*(self.load_cycle(p) for p in live), *self.archived_cycles()]:
                if cycle.name == arg:
                    return cycle
            names = ", ".join(self.load_cycle(p).name for p in live) or "none"
            raise RiteError(f"no cycle named {arg!r} (a cycle is a folder with {self.progress_name}); "
                            f"live cycles: {names}")
        default = self.cfg["paths"]["default_cycle"]
        if default:
            return self.resolve_cycle(default)
        if self.is_cycle_dir(self.cycles_root):
            return self.load_cycle(self.cycles_root)
        if len(live) == 1:
            return self.load_cycle(live[0])
        if not live:
            raise RiteError(f"no live cycle under {display(self.root, self.cycles_root)} (run /rite:new-cycle)")
        raise RiteError("several live cycles, pass one explicitly: "
                        + ", ".join(self.load_cycle(p).name for p in live))

    def find_item(self, item_id: str, cycle: Cycle | None = None) -> tuple[Cycle, Item]:
        cycles = [cycle] if cycle else self.all_cycles()
        hits = [(c, i) for c in cycles for i in c.items if i.id == item_id]
        if not hits:
            raise RiteError(f"item {item_id} not found")
        if len(hits) > 1:
            raise RiteError(f"item {item_id} is ambiguous: " +
                            ", ".join(display(self.root, i.path) for _, i in hits))
        return hits[0]
