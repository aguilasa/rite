"""ID and file-name templates from ``[naming]`` — formatting and parsing."""

from __future__ import annotations

import re
import string
import unicodedata

_FIELD_RE = {
    "prefix": r"[A-Za-z0-9]+",
    "n": r"\d+",
    "slug": r"[^/]+?",
    "cycle": r"[^/]+?",
}


def template_regex(template: str, *, id_template: str | None = None) -> re.Pattern:
    """Compile a naming template into an anchored regex with named groups."""
    parts = []
    seen: set[str] = set()
    for literal, field, _spec, _conv in string.Formatter().parse(template):
        parts.append(re.escape(literal))
        if field is None:
            continue
        if field == "id":
            if id_template is None:
                raise ValueError(f"template {template!r} uses {{id}} but no id template given")
            inner = template_regex(id_template).pattern[1:-1]
            parts.append(f"(?P<id>{inner})")
            seen.update(re.findall(r"\(\?P<(\w+)>", inner))
            continue
        if field not in _FIELD_RE:
            raise ValueError(f"unknown field {{{field}}} in template {template!r}")
        if field in seen:
            parts.append(f"(?P={field})")
        else:
            parts.append(f"(?P<{field}>{_FIELD_RE[field]})")
            seen.add(field)
    return re.compile("^" + "".join(parts) + "$")


def fmt(template: str, **fields) -> str:
    return template.format(**fields)


def as_list(value) -> list[str]:
    """A naming template is a string or a list of them (first = canonical)."""
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]


def slugify(title: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0] or text[:max_len]
    return text or "item"


class Naming:
    """ID and file-name templates.

    Each template may be a string or a list. The first entry is canonical — it is what new items are
    named with; the rest are only accepted when reading, which is how a repository keeps items that
    an earlier convention named differently.
    """

    def __init__(self, naming: dict):
        self.task_id_tpls = as_list(naming["task_id"])
        self.fix_id_tpls = as_list(naming["fix_id"])
        self.task_file_tpls = as_list(naming["task_file"])
        self.fix_file_tpls = as_list(naming["fix_file"])
        self.task_id_res = [template_regex(t) for t in self.task_id_tpls]
        self.fix_id_res = [template_regex(t) for t in self.fix_id_tpls]
        self.task_file_res = [template_regex(f, id_template=i)
                              for f in self.task_file_tpls for i in self.task_id_tpls]
        self.fix_file_res = [template_regex(f, id_template=i)
                             for f in self.fix_file_tpls for i in self.fix_id_tpls]

    # the canonical template of each kind
    @property
    def task_id_tpl(self) -> str:
        return self.task_id_tpls[0]

    @property
    def fix_id_tpl(self) -> str:
        return self.fix_id_tpls[0]

    @property
    def task_file_tpl(self) -> str:
        return self.task_file_tpls[0]

    @property
    def fix_file_tpl(self) -> str:
        return self.fix_file_tpls[0]

    def task_id(self, prefix: str, n: int) -> str:
        return fmt(self.task_id_tpl, prefix=prefix, n=n)

    def fix_id(self, prefix: str, n: int) -> str:
        return fmt(self.fix_id_tpl, prefix=prefix, n=n)

    def task_file(self, prefix: str, n: int, slug: str) -> str:
        return fmt(self.task_file_tpl, prefix=prefix, n=n, slug=slug, id=self.task_id(prefix, n))

    def fix_file(self, prefix: str, n: int, slug: str) -> str:
        return fmt(self.fix_file_tpl, prefix=prefix, n=n, slug=slug, id=self.fix_id(prefix, n))

    def match_file(self, kind: str, rel: str):
        """First file-template match for ``rel`` (posix, relative to the cycle), else None."""
        for rx in (self.task_file_res if kind == "task" else self.fix_file_res):
            m = rx.match(rel)
            if m:
                return m
        return None

    def parse_id(self, item_id: str) -> tuple[str, dict] | None:
        """Return ("task"|"fix", groups) for a well-formed ID, else None. Canonical pattern first."""
        for kind, patterns in (("task", self.task_id_res), ("fix", self.fix_id_res)):
            for index, rx in enumerate(patterns):
                m = rx.match(item_id)
                if m:
                    return kind, {**m.groupdict(), "pattern": index}
        return None
