#!/usr/bin/env python3
"""Cut a release: bump the version everywhere it is written and date the changelog's Unreleased section.

The changelog is written by hand under `## [Unreleased]`; a release only renames that heading to
`## [X.Y.Z] — YYYY-MM-DD`, so the notes are the curated text, never regenerated from commits.

    python tools/release.py current                  # print the current version
    python tools/release.py bump patch|minor|major   # bump, rename Unreleased, print the new version
    python tools/release.py bump 1.2.3               # same, to an explicit version
    python tools/release.py notes [X.Y.Z]            # print the changelog section of a version

Used by .github/workflows/release.yml; it runs the same way locally.
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
SEMVER = r"\d+\.\d+\.\d+"

# Each place the version is written: (file, pattern with one group around the version).
VERSION_SITES = [
    ("rite_lib/__init__.py", rf'^__version__ = "({SEMVER})"$'),
    (".claude-plugin/plugin.json", rf'^  "version": "({SEMVER})",$'),
    (".claude-plugin/marketplace.json", rf'^      "version": "({SEMVER})",$'),
    ("README.md", rf"^> Status: \*\*({SEMVER}) released\.\*\*"),
    (".github/ISSUE_TEMPLATE/1-bug.yml", rf'^      placeholder: "({SEMVER})"$'),
    (".github/ISSUE_TEMPLATE/2-design-gap.yml", rf'^      placeholder: "({SEMVER})"$'),
]


def fail(message: str) -> None:
    sys.exit(f"release: {message}")


def current() -> str:
    text = (ROOT / VERSION_SITES[0][0]).read_text(encoding="utf-8")
    match = re.search(VERSION_SITES[0][1], text, re.M)
    if not match:
        fail(f"no version in {VERSION_SITES[0][0]}")
    return match.group(1)


def next_version(old: str, bump: str) -> str:
    if re.fullmatch(SEMVER, bump):
        new = bump
    elif bump in ("major", "minor", "patch"):
        major, minor, patch = (int(n) for n in old.split("."))
        new = {
            "major": f"{major + 1}.0.0",
            "minor": f"{major}.{minor + 1}.0",
            "patch": f"{major}.{minor}.{patch + 1}",
        }[bump]
    else:
        fail(f"bump must be patch, minor, major or X.Y.Z, not {bump!r}")
    if tuple(map(int, new.split("."))) <= tuple(map(int, old.split("."))):
        fail(f"{new} is not after {old}")
    return new


def set_versions(old: str, new: str) -> None:
    for name, pattern in VERSION_SITES:
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        matches = list(re.finditer(pattern, text, re.M))
        if len(matches) != 1:
            fail(f"{name}: expected one version line, found {len(matches)}")
        if matches[0].group(1) != old:
            fail(f"{name} says {matches[0].group(1)}, {VERSION_SITES[0][0]} says {old}")
        start, end = matches[0].span(1)
        path.write_text(text[:start] + new + text[end:], encoding="utf-8")


def date_unreleased(new: str, date: str) -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    if f"## [{new}]" in text:
        fail(f"CHANGELOG.md already has a [{new}] section")
    body = section(text, "Unreleased")
    if body is None:
        fail("CHANGELOG.md has no ## [Unreleased] section")
    if not body.strip():
        fail("the [Unreleased] section of CHANGELOG.md is empty: nothing to release")
    CHANGELOG.write_text(text.replace("## [Unreleased]", f"## [{new}] — {date}", 1), encoding="utf-8")


def section(text: str, version: str) -> str | None:
    """The body of `## [version]…` up to the next `## ` heading, or None when there is none."""
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1) if match else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("current")
    bump = sub.add_parser("bump")
    bump.add_argument("to", help="patch, minor, major or an explicit X.Y.Z")
    bump.add_argument("--date", default=datetime.date.today().isoformat())
    notes = sub.add_parser("notes")
    notes.add_argument("version", nargs="?")
    args = parser.parse_args()

    if args.command == "current":
        print(current())
    elif args.command == "bump":
        old = current()
        new = next_version(old, args.to)
        date_unreleased(new, args.date)
        set_versions(old, new)
        print(new)
    else:
        version = args.version or current()
        body = section(CHANGELOG.read_text(encoding="utf-8"), version)
        if body is None or not body.strip():
            fail(f"CHANGELOG.md has no notes for {version}")
        print(body.strip())


if __name__ == "__main__":
    main()
