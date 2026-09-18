"""Thin wrappers over the git CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def run(root: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def is_repo(root: Path) -> bool:
    try:
        return run(root, "rev-parse", "--is-inside-work-tree", check=False).strip() == "true"
    except FileNotFoundError:
        return False


def resolve(root: Path, rev: str) -> str | None:
    out = run(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False).strip()
    return out or None


def short(root: Path, sha: str) -> str:
    return run(root, "rev-parse", "--short", sha).strip()


def commit_date(root: Path, sha: str) -> str:
    """Committer date as YYYY-MM-DD."""
    return run(root, "show", "-s", "--format=%cs", sha).strip()


def subject(root: Path, sha: str) -> str:
    return run(root, "show", "-s", "--format=%s", sha).strip()


def changed_files(root: Path, sha: str) -> list[tuple[str, str]]:
    """[(status, path)] touched by a commit; renames reported as 'R old -> new'."""
    out = run(root, "show", "--name-status", "--format=", "--no-color", sha)
    files = []
    for line in out.splitlines():
        if not line.strip():
            continue
        cols = line.split("\t")
        status = cols[0][0]
        path = f"{cols[1]} -> {cols[2]}" if status in "RC" and len(cols) == 3 else cols[-1]
        files.append((status, path))
    return files


def commit_paths(root: Path, paths: list[Path], message: str) -> str:
    """Commit exactly ``paths`` (nothing else that happens to be staged). Returns short SHA."""
    rel = [str(p.relative_to(root)) if p.is_absolute() else str(p) for p in paths]
    run(root, "add", "--", *rel)
    run(root, "commit", "-q", "-m", message, "--", *rel)
    return short(root, "HEAD")


def mv(root: Path, src: Path, dst: Path) -> None:
    run(root, "mv", str(src.relative_to(root)), str(dst.relative_to(root)))
