"""Markdown helpers: headings, anchors, links, sections — code blocks are ignored."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_LINK_RE = re.compile(r"(?<!!)\[(?:[^\]\\]|\\.)*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_INLINE_CODE_RE = re.compile(r"`+[^`]*`+")
_EXPLICIT_ID_RE = re.compile(r"""(?:<a\s+(?:name|id)=["']([^"']+)["']|\{#([^}\s]+)\})""")
_SECTION_NO_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?(?:\s|$)")


def prose_lines(text: str):
    """Yield (line_no, line) outside fenced code blocks, with inline code blanked."""
    fence = None
    for n, line in enumerate(text.splitlines(), start=1):
        m = _FENCE_RE.match(line)
        if m:
            if fence is None:
                fence = m.group(1)
            elif m.group(1) == fence:
                fence = None
            continue
        if fence is None:
            yield n, _INLINE_CODE_RE.sub("", line)


def headings(text: str) -> list[tuple[int, str]]:
    out = []
    for _, line in prose_lines(text):
        m = _HEADING_RE.match(line)
        if m:
            out.append((len(m.group(1)), m.group(2)))
    return out


def heading_anchors(text: str) -> list[tuple[int, str, str, str | None]]:
    """[(level, title, unique slug, section number or None)] in document order."""
    out, counts = [], {}
    for level, title in headings(text):
        slug = github_slug(title)
        dup = counts.get(slug, 0)
        counts[slug] = dup + 1
        num = _SECTION_NO_RE.match(title.strip())
        out.append((level, title, slug if dup == 0 else f"{slug}-{dup}", num.group(1) if num else None))
    return out


def github_slug(heading: str) -> str:
    text = re.sub(r"[`*_\[\]()]", "", heading).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


@lru_cache(maxsize=256)
def _anchors_cached(path: str, mtime: float) -> frozenset[str]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for _, title in headings(text):
        slug = github_slug(title)
        dup = counts.get(slug, 0)
        counts[slug] = dup + 1
        anchors.add(slug if dup == 0 else f"{slug}-{dup}")
        num = _SECTION_NO_RE.match(title.strip())
        if num:
            anchors.add(num.group(1))  # "#4.2" style section numbers
    for m in _EXPLICIT_ID_RE.finditer(text):
        anchors.add(m.group(1) or m.group(2))
    return frozenset(anchors)


def anchors(path: Path) -> frozenset[str]:
    return _anchors_cached(str(path), path.stat().st_mtime)


def has_anchor(path: Path, anchor: str) -> bool:
    if not anchor:
        return True
    return anchor in anchors(path) or anchor.lower() in anchors(path)


def links(text: str) -> list[tuple[int, str]]:
    out = []
    for n, line in prose_lines(text):
        for m in _LINK_RE.finditer(line):
            out.append((n, m.group(1)))
    return out


def is_external(target: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target)) or target.startswith("//")


def section(text: str, title: str) -> str | None:
    """Body of the first heading whose text equals ``title`` (case-insensitive), up to the next heading
    of the same or higher level."""
    lines = text.splitlines()
    fence = None
    start = level = None
    for i, line in enumerate(lines):
        m = _FENCE_RE.match(line)
        if m:
            fence = m.group(1) if fence is None else (None if m.group(1) == fence else fence)
            continue
        if fence:
            continue
        h = _HEADING_RE.match(line)
        if not h:
            continue
        if start is None:
            if h.group(2).strip().lower() == title.strip().lower():
                start, level = i + 1, len(h.group(1))
        elif len(h.group(1)) <= level:
            return "\n".join(lines[start:i])
    return "\n".join(lines[start:]) if start is not None else None


def first_section(text: str, titles) -> tuple[str, str] | None:
    """(title, body) of the first of ``titles`` that has a section in ``text``, tried in order."""
    for title in ([titles] if isinstance(titles, str) else titles):
        body = section(text, title)
        if body is not None:
            return title, body
    return None


def append_to_section(text: str, title, addition: str, level: int = 2) -> str:
    """Append ``addition`` at the end of section ``title``; create the section if missing.

    ``title`` may be a list: the first one present is appended to, and a missing section is created
    with the first of the list."""
    if not isinstance(title, str):
        found = first_section(text, title)
        title = found[0] if found else title[0]
    lines = text.splitlines()
    fence = None
    start = sec_level = None
    end = len(lines)
    for i, line in enumerate(lines):
        m = _FENCE_RE.match(line)
        if m:
            fence = m.group(1) if fence is None else (None if m.group(1) == fence else fence)
            continue
        if fence:
            continue
        h = _HEADING_RE.match(line)
        if not h:
            continue
        if start is None:
            if h.group(2).strip().lower() == title.strip().lower():
                start, sec_level = i, len(h.group(1))
        elif len(h.group(1)) <= sec_level:
            end = i
            break
    add = addition.rstrip("\n").splitlines()
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "#" * level + " " + title, "", *add]
        return "\n".join(lines) + "\n"
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    block = add if insert_at > start + 1 else ["", *add]
    trailer = [""] if end < len(lines) else []
    lines[insert_at:end] = [*block, *trailer]
    return "\n".join(lines) + "\n"
