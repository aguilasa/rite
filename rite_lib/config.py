"""Load and validate ``rite.toml`` (the repo-config layer)."""

from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "rite.toml"

DEFAULTS: dict = {
    "project": {
        "name": "",
        "docs_language": "en-US",
        "code_language": "en-US",
        "commit_language": "en-US",
    },
    "paths": {
        "cycles_root": "docs/rite/cycles",
        "archive_dir": "docs/rite/cycles/archive",
        "profiles_dir": "docs/rite/profiles",
        "plans_dir": "docs/plans",
        "templates_dir": "",
        "link_style": "root-absolute",
        "default_cycle": "",
    },
    "naming": {
        "task_id": "{prefix}-TASK-{n:02}",
        "fix_id": "FIX-{prefix}-{n:03}",
        "task_file": "{n:02}-{slug}.md",
        "fix_file": "{id}.md",
        "progress_file": "progress.md",
        "fixes_file": "fixes.md",
        "profile_file": "{cycle}.md",
        "pitfalls_file": "{cycle}.pitfalls.md",
    },
    "sections": {
        "execution_log": "Execution Log",
        "phase_checks": "Phase-specific checks",
        "phase_label": "Phase",
    },
    "commit": {
        "style": "conventional",
        "co_author_footer": True,
        "bookkeeping": "separate-commit",
        "push": "on-request",
        "never_stage": [],
    },
    "guards": {
        "read_only": [],
        "read_only_reason": "",
        "generated": [],
    },
    "gates": {"global": []},
    "resources": {"serialized": []},
    "vocab": {"task_types": ["feature", "tool", "research", "verification", "closing"]},
    "profile": {"max_kb": 12},
    "status": {"review_age_days": 7},
    "hooks": {"stop_check": False},
}

ENUMS = {
    ("paths", "link_style"): {"root-absolute", "relative"},
    ("commit", "style"): {"conventional", "free"},
    ("commit", "bookkeeping"): {"separate-commit"},
    ("commit", "push"): {"never", "on-request"},
}

TASK_STATUSES = ("pending", "in-progress", "done", "blocked", "skipped")
FIX_STATUSES = ("pending", "in-progress", "done", "stale")
SEVERITIES = ("critical", "high", "medium", "low")


class ConfigError(Exception):
    pass


class NoConfig(ConfigError):
    pass


@dataclass
class Config:
    root: Path
    data: dict

    def __getitem__(self, section: str) -> dict:
        return self.data[section]

    def path(self, key: str) -> Path:
        value = self.data["paths"][key]
        return (self.root / value).resolve() if value else self.root

    @property
    def link_style(self) -> str:
        return self.data["paths"]["link_style"]


def find_root(start: Path) -> Path:
    start = start.resolve()
    for candidate in [start, *start.parents]:
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    raise NoConfig(f"no {CONFIG_NAME} found in {start} or any parent (run /rite:init)")


def _merge(defaults: dict, user: dict, where: str, errors: list[str]) -> dict:
    out = copy.deepcopy(defaults)
    for key, value in user.items():
        if key not in defaults:
            errors.append(f"unknown key [{where}].{key}" if where else f"unknown section [{key}]")
            continue
        if isinstance(defaults[key], dict):
            if not isinstance(value, dict):
                errors.append(f"[{key}] must be a table")
                continue
            out[key] = _merge(defaults[key], value, key, errors)
        else:
            out[key] = value
    return out


def load(root: Path | None = None, *, start: Path | None = None) -> Config:
    if root is None:
        root = find_root(start or Path.cwd())
    root = Path(root).resolve()
    file = root / CONFIG_NAME
    if not file.is_file():
        raise NoConfig(f"no {CONFIG_NAME} in {root} (run /rite:init)")
    return parse(root, file.read_text(encoding="utf-8"))


def parse(root: Path, text: str) -> Config:
    """Build a Config from TOML text (used by load, and by migrations before rite.toml exists)."""
    try:
        user = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{CONFIG_NAME}: {exc}") from exc
    errors: list[str] = []
    data = _merge(DEFAULTS, user, "", errors)
    for (section, key), allowed in ENUMS.items():
        if data[section][key] not in allowed:
            errors.append(f"[{section}].{key} = {data[section][key]!r}; expected one of {sorted(allowed)}")
    for gen in data["guards"]["generated"]:
        if not isinstance(gen, dict) or "paths" not in gen or "generator" not in gen:
            errors.append("[[guards.generated]] entries need 'paths' and 'generator'")
    for res in data["resources"]["serialized"]:
        if not isinstance(res, dict) or "name" not in res:
            errors.append("[resources].serialized entries need a 'name'")
    if errors:
        raise ConfigError(f"{CONFIG_NAME}: " + "; ".join(errors))
    return Config(root=root, data=data)
