#!/usr/bin/env python3
"""Render a cycle's markdown views from its JSON state: the tasks table of the progress file and the
fixes table of the fixes file.

Standalone on purpose: stdlib only, no import of the rest of rite_lib, so the markdown can be rebuilt
without Rite (and this file dropped once nobody reads the markdown). Rite calls the same functions
after every state change (`rite sync`).

Only the generated region between ``<!-- rite:begin <region> -->`` and ``<!-- rite:end -->`` is
rewritten; the rest of each file is free text and is kept. Rows come in the order of the JSON arrays,
which Rite keeps in execution order.

    python render_md.py <cycle_dir> [--root DIR] [--link-style root-absolute|relative] [--check]

Without ``--root`` the root is the nearest folder above the cycle holding ``rite.toml``; link style
and file names are read from it (``[paths].link_style``, ``[naming]``) unless given.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

TASKS_REGION = "tasks"
FIXES_REGION = "fixes"
END_MARKER = "<!-- rite:end -->"
DEFAULT_NAMES = {"progress_file": "progress.md", "fixes_file": "fixes.md",
                 "progress_state": "progress.json", "fixes_state": "fixes.json"}


def begin_marker(region: str) -> str:
    return f"<!-- rite:begin {region} -->"


def cell(value) -> str:
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return str(value).replace("|", "\\|").replace("\n", " ")


def make_link(root: Path, from_file: Path, target: Path, style: str) -> str:
    if style == "root-absolute":
        return "/" + target.resolve().relative_to(root.resolve()).as_posix()
    return Path(os.path.relpath(target.resolve(), from_file.resolve().parent)).as_posix()


def _deps(entry: dict) -> list:
    deps = entry.get("depends_on") or []
    return [str(d) for d in deps] if isinstance(deps, list) else [str(deps)]


def tasks_table(tasks: list[dict], *, md_path: Path, cycle_dir: Path, root: Path, link_style: str) -> str:
    rows = ["| ID | Title | Phase | Type | Depends on | Status | Done on | Reviewed on |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in tasks:
        link = make_link(root, md_path, cycle_dir / t["file"], link_style)
        rows.append(f"| [{t.get('id')}]({link}) | {cell(t.get('title') or '')} | {cell(t.get('phase'))} "
                    f"| {cell(t.get('type'))} | {cell(_deps(t))} | {cell(t.get('status') or '')} "
                    f"| {cell(t.get('done_on'))} | {cell(t.get('reviewed_on'))} |")
    if not tasks:
        rows.append("| — | *(no tasks yet)* | | | | | | |")
    return "\n".join(rows)


def fixes_table(fixes: list[dict], *, md_path: Path, cycle_dir: Path, root: Path, link_style: str) -> str:
    rows = ["| ID | Title | Origin | Severity | Status | Done on |",
            "| --- | --- | --- | --- | --- | --- |"]
    for fx in fixes:
        link = make_link(root, md_path, cycle_dir / fx["file"], link_style)
        rows.append(f"| [{fx.get('id')}]({link}) | {cell(fx.get('title') or '')} | {cell(fx.get('origin'))} "
                    f"| {cell(fx.get('severity'))} | {cell(fx.get('status') or '')} | {cell(fx.get('done_on'))} |")
    if not fixes:
        rows.append("| — | *(no fixes)* | | | | |")
    return "\n".join(rows)


def replace_region(text: str, region: str, content: str) -> str:
    begin = begin_marker(region)
    block = f"{begin}\n{content}\n{END_MARKER}"
    start = text.find(begin)
    if start == -1:
        sep = "" if text.endswith("\n\n") or not text else ("\n" if text.endswith("\n") else "\n\n")
        return f"{text}{sep}{block}\n"
    end = text.find(END_MARKER, start)
    if end == -1:
        raise ValueError(f"'{begin}' without '{END_MARKER}'")
    return text[:start] + block + text[end + len(END_MARKER):]


def extract_region(text: str, region: str) -> str | None:
    begin = begin_marker(region)
    start = text.find(begin)
    if start == -1:
        return None
    end = text.find(END_MARKER, start)
    if end == -1:
        return None
    return text[start + len(begin):end].strip("\n")


def read_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def views(cycle_dir: Path, *, root: Path, link_style: str, names: dict | None = None) -> dict[Path, tuple[str, str]]:
    """{markdown file: (region, generated content)} for one cycle, from its JSON files."""
    names = {**DEFAULT_NAMES, **(names or {})}
    progress = read_state(cycle_dir / names["progress_state"])
    fixes = read_state(cycle_dir / names["fixes_state"])
    progress_md, fixes_md = cycle_dir / names["progress_file"], cycle_dir / names["fixes_file"]
    opts = {"cycle_dir": cycle_dir, "root": root, "link_style": link_style}
    return {
        progress_md: (TASKS_REGION, tasks_table(progress.get("tasks") or [], md_path=progress_md, **opts)),
        fixes_md: (FIXES_REGION, fixes_table(fixes.get("fixes") or [], md_path=fixes_md, **opts)),
    }


def out_of_sync(cycle_dir: Path, *, root: Path, link_style: str, names: dict | None = None) -> list[Path]:
    stale = []
    for path, (region, content) in views(cycle_dir, root=root, link_style=link_style, names=names).items():
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if extract_region(current, region) != content:
            stale.append(path)
    return stale


def render(cycle_dir: Path, *, root: Path, link_style: str, names: dict | None = None) -> list[Path]:
    """Rewrite only the generated regions. Idempotent. Returns the files that changed."""
    name = read_state(cycle_dir / {**DEFAULT_NAMES, **(names or {})}["progress_state"]).get("cycle") \
        or cycle_dir.name
    changed = []
    for path, (region, content) in views(cycle_dir, root=root, link_style=link_style, names=names).items():
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if not current:
            current = f"# {'Fixes' if region == FIXES_REGION else 'Progress'} — {name}\n"
        new = replace_region(current, region, content)
        if new != current:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed.append(path)
    return changed


# --- standalone ------------------------------------------------------------------
def _find_root(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        if (candidate / "rite.toml").is_file():
            return candidate
    return None


def _config(root: Path | None) -> dict:
    if root is None or not (root / "rite.toml").is_file():
        return {}
    try:
        import tomllib
    except ImportError:  # Python < 3.11: fall back to the defaults
        return {}
    return tomllib.loads((root / "rite.toml").read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render a Rite cycle's markdown views from its JSON state.")
    p.add_argument("cycle_dir", nargs="+", help="cycle folder(s) holding the JSON state")
    p.add_argument("--root", help="repository root (default: nearest folder with rite.toml)")
    p.add_argument("--link-style", choices=("root-absolute", "relative"))
    p.add_argument("--check", action="store_true", help="write nothing; exit 1 when a view is stale")
    args = p.parse_args(argv)
    code = 0
    for raw in args.cycle_dir:
        cycle_dir = Path(raw).resolve()
        root = Path(args.root).resolve() if args.root else _find_root(cycle_dir)
        cfg = _config(root)
        root = root or cycle_dir
        style = args.link_style or cfg.get("paths", {}).get("link_style", "root-absolute")
        names = {k: v for k, v in cfg.get("naming", {}).items() if k in DEFAULT_NAMES}
        if args.check:
            for path in out_of_sync(cycle_dir, root=root, link_style=style, names=names):
                print(f"stale: {path}")
                code = 1
        else:
            for path in render(cycle_dir, root=root, link_style=style, names=names):
                print(f"rendered: {path}")
    return code


if __name__ == "__main__":
    sys.exit(main())
