"""Minimal YAML-subset frontmatter reader/writer.

Supported values: null/~, true/false, integers, quoted or bare strings,
inline lists ``[a, b]`` and block lists (``- a`` lines). Anything richer is
out of scope on purpose: frontmatter is the single source of state and must
stay trivially diffable.

Writes are surgical: only the touched ``key:`` lines change, so comments and
key order written by humans survive.
"""

from __future__ import annotations

import json
import re

DELIM = "---"
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(.*)$")
_BARE_SAFE = re.compile(r"^[A-Za-z0-9_./@+-][A-Za-z0-9_./@+ -]*$")
_INT_RE = re.compile(r"^-?\d+$")
_KEYWORDS = {"null", "~", "true", "false", "yes", "no", "on", "off"}


class FrontmatterError(ValueError):
    pass


def split(text: str) -> tuple[list[str] | None, str]:
    """Return (frontmatter lines, body). Lines exclude the delimiters."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != DELIM:
        return None, text
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == DELIM:
            fm = [ln.rstrip("\r\n") for ln in lines[1:i]]
            return fm, "".join(lines[i + 1:])
    raise FrontmatterError("frontmatter opened with '---' but never closed")


def _strip_comment(raw: str) -> tuple[str, str]:
    """Split ``value  # comment`` respecting quotes. Returns (value, comment)."""
    quote = None
    for i, ch in enumerate(raw):
        if quote:
            if ch == "\\" and quote == '"':
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i].rstrip(), raw[i:]
    return raw.strip(), ""


def _parse_scalar(raw: str):
    raw = raw.strip()
    if raw == "" or raw in ("null", "~"):
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    if _INT_RE.match(raw):
        return int(raw)
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FrontmatterError(f"bad double-quoted string: {raw}") from exc
    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
        return raw[1:-1].replace("''", "'")
    return raw


def _split_inline_list(inner: str) -> list[str]:
    parts, cur, quote = [], [], None
    for ch in inner:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch == ",":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [_parse_scalar(p) for p in _split_inline_list(raw[1:-1])]
    return _parse_scalar(raw)


def parse(text: str) -> tuple[dict, str]:
    """Parse a markdown file. Returns (fields, body). Missing frontmatter -> ({}, text)."""
    fm, body = split(text)
    if fm is None:
        return {}, text
    data: dict = {}
    current_list_key = None
    for n, line in enumerate(fm, start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) and current_list_key:
            item = line.strip()
            if not item.startswith("- ") and item != "-":
                raise FrontmatterError(f"line {n}: nested mappings are not supported")
            value, _ = _strip_comment(item[1:])
            data[current_list_key].append(_parse_scalar(value))
            continue
        m = _KEY_RE.match(line)
        if not m:
            raise FrontmatterError(f"line {n}: expected 'key: value', got {line!r}")
        key, rest = m.group(1), m.group(2)
        value, _ = _strip_comment(rest)
        if key in data:
            raise FrontmatterError(f"line {n}: duplicate key {key!r}")
        if value == "":
            data[key] = []
            current_list_key = key
            continue
        current_list_key = None
        data[key] = _parse_value(value)
    # an empty block list ("key:" with no items) means null, not []
    for key, value in list(data.items()):
        if value == [] and not _has_inline_brackets(fm, key):
            data[key] = None
    return data, body


def _has_inline_brackets(fm: list[str], key: str) -> bool:
    for line in fm:
        m = _KEY_RE.match(line)
        if m and m.group(1) == key:
            return _strip_comment(m.group(2))[0].startswith("[")
    return False


def dump_value(value) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(dump_value(v) for v in value) + "]"
    s = str(value)
    if _BARE_SAFE.match(s) and s.lower() not in _KEYWORDS and not _INT_RE.match(s) and s == s.strip():
        return s
    return json.dumps(s, ensure_ascii=False)


def remove_fields(text: str, keys: set[str]) -> str:
    """Return ``text`` without the given top-level frontmatter keys (and their block-list lines)."""
    fm, _ = split(text)
    if fm is None:
        return text
    lines = text.splitlines(keepends=True)
    end = len(fm) + 1
    out, i = [lines[0]], 1
    while i < end:
        m = _KEY_RE.match(lines[i].rstrip("\r\n"))
        if m and m.group(1) in keys:
            i += 1
            while i < end and lines[i].startswith((" ", "\t")):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "".join(out + lines[end:])


def set_fields(text: str, updates: dict) -> str:
    """Return ``text`` with the given frontmatter keys set, preserving everything else."""
    lines = text.splitlines(keepends=True)
    fm, _ = split(text)
    if fm is None:
        header = [DELIM + "\n"] + [f"{k}: {dump_value(v)}\n" for k, v in updates.items()] + [DELIM + "\n"]
        return "".join(header) + text
    end = len(fm) + 1  # index of closing delimiter in `lines`
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    pending = dict(updates)
    i = 1
    while i < end:
        m = _KEY_RE.match(lines[i].rstrip("\r\n"))
        if m and m.group(1) in pending:
            key = m.group(1)
            _, comment = _strip_comment(m.group(2))
            # drop block-list continuation lines owned by this key
            j = i + 1
            while j < end and lines[j].startswith((" ", "\t")) and lines[j].strip().startswith("-"):
                j += 1
            new_line = f"{key}: {dump_value(pending.pop(key))}"
            if comment:
                new_line += f"  {comment}"
            lines[i:j] = [new_line + newline]
            end -= (j - i) - 1
        i += 1
    for key, value in pending.items():
        lines.insert(end, f"{key}: {dump_value(value)}{newline}")
        end += 1
    return "".join(lines)
