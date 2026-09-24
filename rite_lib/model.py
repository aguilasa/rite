"""Cycles and items (tasks, fixes) as read from disk. Frontmatter is the only state."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter, gitutil
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
    body: str = ""
    parse_error: str | None = None

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
        return (path / self.progress_name).is_file()

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

    def archived_cycles(self) -> list[Cycle]:
        if not self.archive_dir.is_dir():
            return []
        # a legacy archive folder may itself be one closed cycle
        dirs = [self.archive_dir] if self.is_cycle_dir(self.archive_dir) else []
        dirs += [p for p in sorted(self.archive_dir.iterdir()) if p.is_dir() and self.is_cycle_dir(p)]
        return [self.load_cycle(p, archived=True) for p in dirs]

    def all_cycles(self) -> list[Cycle]:
        return self.live_cycles() + self.archived_cycles()

    def load_cycle(self, path: Path, archived: bool | None = None) -> Cycle:
        path = path.resolve()
        progress = path / self.progress_name
        meta, _ = frontmatter.parse(progress.read_text(encoding="utf-8"))
        name = str(meta.get("cycle") or path.name)
        if archived is None:
            archived = self.archive_dir in path.parents
        profiles_dir = self.cfg.path("profiles_dir")
        naming = self.cfg["naming"]
        if meta.get("profile"):
            profile, _ = resolve_link(self.root, progress, str(meta["profile"]))
        else:
            profile = profiles_dir / naming["profile_file"].format(cycle=name)
        pitfalls = profile.with_name(naming["pitfalls_file"].format(cycle=name)) \
            if not meta.get("pitfalls") else resolve_link(self.root, progress, str(meta["pitfalls"]))[0]
        cycle = Cycle(
            name=name, path=path, progress_path=progress, fixes_path=path / self.fixes_name,
            meta=meta, archived=archived, profile_path=profile, pitfalls_path=pitfalls,
            workspace=self.workspace,
        )
        cycle.items = self._load_items(path)
        return cycle

    def _load_items(self, cycle_dir: Path) -> list[Item]:
        items = []
        skip = {self.progress_name, self.fixes_name}
        for dirpath, dirnames, filenames in os.walk(cycle_dir):
            current = Path(dirpath)
            # nested cycles (and the archive) are not part of this cycle
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
                        items.append(self._load_item(kind, file, int(m.group("n"))))
                        break
        return items

    def _load_item(self, kind: str, file: Path, n: int) -> Item:
        item = Item(kind=kind, path=file, n=n)
        try:
            item.fields, item.body = frontmatter.parse(file.read_text(encoding="utf-8"))
        except (frontmatter.FrontmatterError, UnicodeDecodeError) as exc:
            item.parse_error = str(exc)
        return item

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
