"""Path guards from ``[guards]``: read-only paths and generated artifacts."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .config import Config


@lru_cache(maxsize=512)
def glob_regex(pattern: str) -> re.Pattern:
    """Glob with ``**`` (any depth), ``*`` and ``?`` (within one segment), matched on posix paths."""
    pattern = pattern.strip().lstrip("/")
    if pattern.endswith("/"):
        pattern += "**"
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


def matches(rel: str, patterns) -> str | None:
    for pat in [patterns] if isinstance(patterns, str) else patterns:
        if glob_regex(pat).match(rel):
            return pat
    return None


def relative(root: Path, path: Path) -> str | None:
    path = path if path.is_absolute() else root / path
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def classify(cfg: Config, path: Path) -> dict:
    rel = relative(cfg.root, path)
    verdict = {"path": rel or str(path), "blocked": False, "kind": None, "pattern": None,
               "generator": None, "check": None, "message": ""}
    if rel is None:
        return verdict
    guards = cfg["guards"]
    pat = matches(rel, guards["read_only"])
    if pat:
        reason = guards.get("read_only_reason") or "declared read-only in rite.toml [guards].read_only"
        verdict.update(blocked=True, kind="read_only", pattern=pat,
                       message=f"rite guard: {rel} is read-only ({pat}): {reason}")
        return verdict
    for gen in guards["generated"]:
        pat = matches(rel, gen["paths"])
        if pat:
            check = gen.get("check")
            msg = (f"rite guard: {rel} is generated ({pat}). Edit the generator {gen['generator']} "
                   "and regenerate" + (f", then run `{check}`" if check else "") + " — never edit the output.")
            verdict.update(blocked=True, kind="generated", pattern=pat, generator=gen["generator"],
                           check=check, message=msg)
            return verdict
    return verdict
