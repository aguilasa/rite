"""Cycles from before the JSON state: state in the frontmatter of each item and of the progress file.

Read only by the migrations (`rite migrate --from frontmatter`, and `--from we2002`, which goes
through this layout on its way to the JSON). Nothing else reads frontmatter state any more.
"""

from __future__ import annotations

from pathlib import Path

from . import frontmatter, render_md
from .model import Cycle, Item, Project


class LegacyProject(Project):
    """A Project whose cycles are read from frontmatter, the way Rite read them up to 0.13."""

    def is_cycle_dir(self, path: Path) -> bool:
        return (path / self.progress_name).is_file()

    def is_legacy_dir(self, path: Path) -> bool:
        return False

    def load_cycle(self, path: Path, archived: bool | None = None) -> Cycle:
        path = path.resolve()
        progress = path / self.progress_name
        meta, _ = frontmatter.parse(progress.read_text(encoding="utf-8"))
        if archived is None:
            archived = self.archive_dir in path.parents
        profile, pitfalls = self.cycle_paths(path, meta)
        cycle = Cycle(
            name=str(meta.get("cycle") or path.name), path=path,
            progress_path=progress, fixes_path=path / self.fixes_name,
            progress_state_path=path / self.progress_state, fixes_state_path=path / self.fixes_state,
            meta=meta, archived=archived, profile_path=profile, pitfalls_path=pitfalls,
            workspace=self.workspace,
        )
        cycle.items = [self.load_item(kind, file, n, path) for kind, file, n in self.item_files(path)]
        return cycle

    @staticmethod
    def load_item(kind: str, file: Path, n: int, cycle_dir: Path) -> Item:
        item = Item(kind=kind, path=file, n=n, file=file.relative_to(cycle_dir).as_posix())
        try:
            item.fields, body = frontmatter.parse(file.read_text(encoding="utf-8"))
            item._md = (dict(item.fields), body, None)
        except (frontmatter.FrontmatterError, UnicodeDecodeError) as exc:
            item.parse_error = str(exc)
        return item


def entries(cycle: Cycle, kind: str) -> list[dict]:
    """The JSON entries of a legacy cycle's items, in the order the views list them."""
    items = cycle.tasks if kind == "task" else cycle.fixes
    return [{"id": i.id, "file": i.file, **{k: v for k, v in i.fields.items() if k not in ("id", "file")}}
            for i in items]


def sync(project: Project, cycle: Cycle) -> list[Path]:
    """Regenerate a legacy cycle's views from its frontmatter (used mid-migration)."""
    opts = {"cycle_dir": cycle.path, "root": project.root, "link_style": project.cfg.link_style}
    changed = []
    for path, region, table in (
            (cycle.progress_path, render_md.TASKS_REGION,
             render_md.tasks_table(entries(cycle, "task"), md_path=cycle.progress_path, **opts)),
            (cycle.fixes_path, render_md.FIXES_REGION,
             render_md.fixes_table(entries(cycle, "fix"), md_path=cycle.fixes_path, **opts))):
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if not current:
            current = f"# {'Fixes' if region == render_md.FIXES_REGION else 'Progress'} — {cycle.name}\n"
        new = render_md.replace_region(current, region, table)
        if new != current:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed.append(path)
    return changed
