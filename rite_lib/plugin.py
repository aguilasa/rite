"""`rite plugin-info` / `rite clear-cache` — the rite installed in Claude Code, and its cache.

Claude Code keeps one folder per installed version, `<plugins>/cache/<marketplace>/rite/<version>`,
and loads the commands from the folder of the version the session started with. An update installs
a new folder but the session keeps running the old one until `/reload-plugins` (a built-in command
no plugin can run) or a restart: that folder must stay. These measure and delete; the commands only
ask.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from . import __version__
from .model import RiteError

NAME = "rite"
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def _key(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def _cache_place(root: Path) -> tuple[Path, str] | None:
    """(plugins dir, marketplace) when ``root`` is `<plugins>/cache/<marketplace>/rite/<version>`."""
    root = root.resolve()
    if len(root.parents) >= 4 and root.parent.name == NAME and root.parents[2].name == "cache":
        return root.parents[3], root.parents[1].name
    return None


def _running_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_plugins_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path.home() / ".claude") / "plugins"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def info(plugins_dir: Path | None = None, running_root: Path | None = None) -> dict:
    running_root = (running_root or _running_root()).resolve()
    place = _cache_place(running_root)
    plugins_dir = Path(plugins_dir) if plugins_dir else (place[0] if place else _default_plugins_dir())
    manifest = _read_json(running_root / ".claude-plugin" / "plugin.json")
    running_version = str(manifest.get("version") or __version__)

    installed_all = _read_json(plugins_dir / "installed_plugins.json").get("plugins") or {}
    marketplace = place[1] if place else next(
        (k.split("@", 1)[1] for k in installed_all if k.startswith(f"{NAME}@")), None)
    plugin_id = f"{NAME}@{marketplace}" if marketplace else None
    entries = installed_all.get(plugin_id) or [] if plugin_id else []
    entry = entries[0] if entries else {}
    installed = str(entry["version"]) if entry.get("version") else None

    latest = None
    if marketplace:
        catalog = _read_json(plugins_dir / "marketplaces" / marketplace / ".claude-plugin" / "marketplace.json")
        latest = next((str(p.get("version")) for p in catalog.get("plugins") or []
                       if p.get("name") == NAME and p.get("version")), None)

    cache = []
    folder = plugins_dir / "cache" / marketplace / NAME if marketplace else None
    if folder and folder.is_dir():
        for path in sorted((p for p in folder.iterdir() if p.is_dir() and VERSION.match(p.name)),
                           key=lambda p: _key(p.name)):
            is_running = place is not None and path.resolve() == running_root
            cache.append({"version": path.name, "path": str(path), "bytes": _size(path),
                          "running": is_running, "installed": path.name == installed,
                          # from a checkout, which folder the session loaded is unknown: none is removable
                          "removable": place is not None and installed is not None and not is_running
                                       and path.name != installed})

    if place is None or installed is None:
        state = "not-installed"
    elif latest and _key(latest) > _key(installed):
        state = "update-available"
    elif installed != running_version:
        state = "reload-needed"
    else:
        state = "up-to-date"
    return {
        "running": {"version": running_version, "root": str(running_root), "from_cache": place is not None},
        "plugins_dir": str(plugins_dir), "marketplace": marketplace, "plugin_id": plugin_id,
        "installed": {"version": installed, "commit": entry.get("gitCommitSha")} if installed else None,
        "latest": latest, "state": state, "cache": cache,
        "commands": {"refresh": f"claude plugin marketplace update {marketplace}",
                     "update": f"claude plugin update {plugin_id}"} if marketplace else None,
    }


def clear(plugins_dir: Path | None = None, running_root: Path | None = None, *, dry_run: bool = False) -> dict:
    """Delete the cached versions that are neither the one running nor the one installed."""
    data = info(plugins_dir, running_root)
    if not data["running"]["from_cache"]:
        raise RiteError(f"this rite runs from {data['running']['root']}, not from the plugin cache: which "
                        "cached version the session loaded is unknown, so nothing is deleted")
    if not data["installed"]:
        raise RiteError("no installed rite found in installed_plugins.json: not knowing which version "
                        "to keep, nothing is deleted")
    gone = [c for c in data["cache"] if c["removable"]]
    kept = [{"version": c["version"], "why": "running" if c["running"] else "installed"}
            for c in data["cache"] if not c["removable"]]
    if not dry_run:
        for c in gone:
            shutil.rmtree(c["path"])
    rows = [{"version": c["version"], "bytes": c["bytes"], "path": c["path"]} for c in gone]
    return {"dry_run": dry_run, ("would_remove" if dry_run else "removed"): rows, "kept": kept,
            "freed_bytes": sum(c["bytes"] for c in gone), "state": data["state"],
            "running": data["running"]["version"], "installed": data["installed"]["version"]}


def _mb(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB"


def render_info(d: dict) -> str:
    lines = [f"running {d['running']['version']} ({'cache' if d['running']['from_cache'] else d['running']['root']})",
             f"installed {(d['installed'] or {}).get('version') or '—'} · latest {d['latest'] or '—'} · {d['state']}"]
    for c in d["cache"]:
        tags = [t for t in ("running", "installed") if c[t]]
        lines.append(f"  {'*' if c['removable'] else ' '} {c['version']}  {_mb(c['bytes'])}"
                     + (f"  ({', '.join(tags)})" if tags else ""))
    return "\n".join(lines)


def render_clear(d: dict) -> str:
    rows = d.get("would_remove", d.get("removed", []))
    verb = "would remove" if d["dry_run"] else "removed"
    lines = [f"{verb} {len(rows)} version(s), {_mb(d['freed_bytes'])}: "
             + (", ".join(r["version"] for r in rows) or "none")]
    lines += [f"  kept {k['version']} ({k['why']})" for k in d["kept"]]
    return "\n".join(lines)
