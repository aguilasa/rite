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


def is_ancestor(root: Path, sha: str, of: str) -> bool:
    proc = subprocess.run(["git", "merge-base", "--is-ancestor", sha, of], cwd=root, capture_output=True)
    return proc.returncode == 0


def is_ignored(root: Path, path: Path) -> bool:
    rel = str(path.relative_to(root)) if path.is_absolute() else str(path)
    proc = subprocess.run(["git", "check-ignore", "-q", "--", rel], cwd=root, capture_output=True)
    return proc.returncode == 0


def is_tracked(root: Path, path: Path) -> bool:
    """Whether git tracks ``path`` or, for a folder, anything under it."""
    rel = str(path.relative_to(root)) if path.is_absolute() else str(path)
    return bool(run(root, "ls-files", "--", rel, check=False).strip())


def mv(root: Path, src: Path, dst: Path) -> None:
    run(root, "mv", str(src.relative_to(root)), str(dst.relative_to(root)))
