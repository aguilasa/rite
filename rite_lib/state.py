"""The JSON state of a cycle: ``progress.json`` (cycle meta + tasks) and ``fixes.json`` (fixes).

These two files are the only state. Item markdown files hold prose and their ``id``; the progress and
fixes markdown files are views rendered from the JSON (``render_md``). Every write goes through here:
read-modify-write under a lock file, written to a temporary file and renamed, so a reader never sees
half a file and two writers never lose each other's change.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

SCHEMA = 1
TASKS, FIXES = "tasks", "fixes"
LOCK_TIMEOUT_S = 10.0


class StateError(ValueError):
    pass


def array_key(kind: str) -> str:
    return TASKS if kind == "task" else FIXES


# --- encoding --------------------------------------------------------------------
def _scalar(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _encode(value, indent: int) -> str:
    pad, inner = "  " * indent, "  " * (indent + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        body = ",\n".join(f"{inner}{_scalar(str(k))}: {_encode(v, indent + 1)}" for k, v in value.items())
        return "{\n" + body + "\n" + pad + "}"
    if isinstance(value, list):
        if all(not isinstance(v, (dict, list)) for v in value):
            # a list of scalars stays on one line: `depends_on`, `files`, `order` diff as one line
            return "[" + ", ".join(_scalar(v) for v in value) + "]"
        return "[\n" + ",\n".join(inner + _encode(v, indent + 1) for v in value) + "\n" + pad + "]"
    return _scalar(value)


def dumps(data: dict) -> str:
    """Deterministic text: two-space indent, keys in insertion order, scalar lists inline, final LF."""
    return _encode(data, 0) + "\n"


# --- files -----------------------------------------------------------------------
def read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise StateError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise StateError(f"{path}: expected a JSON object")
    if data.get("schema") != SCHEMA:
        raise StateError(f"{path}: schema {data.get('schema')!r}, this Rite reads schema {SCHEMA}")
    return data


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(dumps(data), encoding="utf-8", newline="\n")
    os.replace(tmp, path)


@contextlib.contextmanager
def locked(path: Path):
    lock = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise StateError(f"{lock} is held by another rite process; if none is running, delete it")
            time.sleep(0.05)
    try:
        os.close(fd)
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.remove(lock)


def edit(path: Path, change, default: dict | None = None) -> dict:
    """Apply ``change(data)`` to the file under its lock and write it back when it changed."""
    with locked(path):
        try:
            data = read(path)
            before = dumps(data)
        except FileNotFoundError:
            if default is None:
                raise StateError(f"{path} not found")
            data, before = json.loads(json.dumps(default)), None
        change(data)
        if dumps(data) != before:
            write(path, data)
        return data


def new_progress(meta: dict) -> dict:
    return {"schema": SCHEMA, **{k: v for k, v in meta.items() if k not in ("schema", TASKS)}, TASKS: []}


def new_fixes(cycle: str) -> dict:
    return {"schema": SCHEMA, "cycle": cycle, FIXES: []}


def meta_of(progress: dict) -> dict:
    return {k: v for k, v in progress.items() if k not in ("schema", TASKS)}


# --- items -----------------------------------------------------------------------
def find_entry(data: dict, kind: str, item_id: str) -> dict:
    for entry in data.get(array_key(kind)) or []:
        if entry.get("id") == item_id:
            return entry
    raise StateError(f"{item_id} is not in the {array_key(kind)} of this cycle's state")


def update_item(path: Path, kind: str, item_id: str, updates: dict) -> None:
    edit(path, lambda data: find_entry(data, kind, item_id).update(updates))


def add_item(path: Path, kind: str, entry: dict, default: dict) -> None:
    def change(data: dict) -> None:
        items = data.setdefault(array_key(kind), [])
        if any(e.get("id") == entry["id"] for e in items):
            raise StateError(f"{entry['id']} is already in {path.name}")
        items.append(entry)
    edit(path, change, default)


def update_meta(path: Path, updates: dict) -> None:
    def change(data: dict) -> None:
        tasks = data.pop(TASKS, [])
        data.update(updates)
        data[TASKS] = tasks  # the item array stays last
    edit(path, change)


def reorder(path: Path, kind: str, key) -> bool:
    """Sort the item array by ``key(entry)``; True when the order changed."""
    moved = []

    def change(data: dict) -> None:
        items = data.get(array_key(kind)) or []
        ordered = sorted(items, key=key)
        if [e.get("id") for e in ordered] != [e.get("id") for e in items]:
            data[array_key(kind)] = ordered
            moved.append(True)
    if path.is_file():
        edit(path, change)
    return bool(moved)
