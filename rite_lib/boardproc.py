"""The boards `rite serve` runs: who serves which repository, from which rite, and how to stop one.

Why: `/rite:board` started a server and never looked for one already there, so a second call opened
3001, and a board started before an update kept serving the old code. A board now announces itself
twice — a registry file in the temp folder and `GET /api/info` — and boards started before that
(they announce nothing) are found by their process on Linux and macOS.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from . import __version__
from .model import RiteError

# `…/rite/0.34.0/bin/rite.py serve`: the version an installed launcher runs
_VERSION_IN_PATH = re.compile(r"/rite/(\d+\.\d+\.\d+)/bin/rite(?:\.py)?(?:\s|$)")
_SERVE = re.compile(r"(?:^|\s)\S*bin/rite(?:\.py)?\s+serve(?:\s|$)")


def rite_root() -> Path:
    return Path(__file__).resolve().parent.parent


def registry_path(root: Path) -> Path:
    digest = hashlib.sha1(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"rite-board-{digest}.json"


def identity(root: Path, *, host: str, port: int, url: str) -> dict:
    """What a board says of itself: in its registry file and at `/api/info`."""
    return {"app": "rite-board", "pid": os.getpid(), "host": host, "port": port, "url": url,
            "version": __version__, "rite_root": str(rite_root()), "root": str(Path(root).resolve()),
            "started_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


def register(info: dict) -> Path:
    path = registry_path(Path(info["root"]))
    path.write_text(json.dumps(info), encoding="utf-8")
    return path


def unregister(root: Path, pid: int) -> None:
    path = registry_path(root)
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("pid") == pid:
            path.unlink()
    except (OSError, ValueError):
        pass


def alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _ask(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/info", timeout=2) as res:
            return json.loads(res.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


# --- boards found by their process (POSIX): those started before boards announced themselves -----
def parse_ps(text: str) -> list[dict]:
    """`ps -eo pid=,args=` lines that run `rite serve`: pid, args, the version in the launcher's path
    (None for a checkout) and the `--root` given, if any."""
    found = []
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit() or not _SERVE.search(parts[1]):
            continue
        args = parts[1]
        version = _VERSION_IN_PATH.search(args)
        root = re.search(r"--root[ =](\S+)", args)
        found.append({"pid": int(parts[0]), "args": args, "version": version.group(1) if version else None,
                      "root": root.group(1) if root else None,
                      "rite_root": args.split("/bin/rite")[0].split()[-1] if "/bin/rite" in args else None})
    return found


def _cwd(pid: int) -> str | None:
    link = Path(f"/proc/{pid}/cwd")
    try:
        return os.readlink(link)
    except OSError:
        pass
    try:  # macOS
        out = subprocess.run(["lsof", "-a", "-d", "cwd", "-p", str(pid), "-Fn"], capture_output=True, text=True)
    except OSError:
        return None
    return next((line[1:] for line in out.stdout.splitlines() if line.startswith("n")), None)


def _args(pid: int) -> str:
    try:
        return subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def _processes() -> list[dict]:
    if os.name == "nt":
        return []
    try:
        out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True).stdout
    except OSError:
        return []
    return [p for p in parse_ps(out) if p["pid"] != os.getpid()]


def running(root: Path) -> list[dict]:
    """The boards serving ``root``: from its registry (checked: pid alive, `/api/info` the same
    repository) and, on POSIX, from the processes running `rite serve` there. `current` = served by
    this rite's own install, so by this code."""
    root = Path(root).resolve()
    me = str(rite_root())
    boards: dict[int, dict] = {}
    path = registry_path(root)
    try:
        reg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reg = None
    if reg:
        said = _ask(reg.get("url", "")) if alive(int(reg.get("pid", 0))) else None
        if said and said.get("root") == str(root) and said.get("pid") == reg.get("pid"):
            boards[said["pid"]] = {**said, "source": "registry"}
        else:
            path.unlink(missing_ok=True)  # a board that died without cleaning up
    for proc in _processes():
        if proc["pid"] in boards:
            continue
        where = proc["root"] or _cwd(proc["pid"])
        if not where or Path(where).resolve() != root:
            continue
        boards[proc["pid"]] = {"pid": proc["pid"], "port": None, "url": None, "version": proc["version"],
                               "rite_root": proc["rite_root"], "root": str(root), "source": "process"}
    out = []
    for b in boards.values():
        out.append({**b, "current": bool(b.get("rite_root")) and
                    Path(b["rite_root"]).resolve() == Path(me).resolve()})
    return sorted(out, key=lambda b: b["pid"])


def stop(board: dict, *, wait: float = 5.0) -> None:
    """Stop one board: SIGTERM, then SIGKILL after ``wait`` seconds. A pid found by its process is
    checked again first: only a `rite serve` is ever signalled."""
    pid = int(board["pid"])
    if os.name == "nt":
        if board.get("source") != "registry":
            raise RiteError(f"a board started by an older rite runs as pid {pid}: stop it by hand "
                            "(its terminal or background task), then run this again")
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    if board.get("source") == "process" and not _SERVE.search(_args(pid)):
        raise RiteError(f"pid {pid} no longer runs `rite serve`: not stopped")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def status(root: Path) -> dict:
    return {"root": str(Path(root).resolve()), "current_version": __version__, "rite_root": str(rite_root()),
            "boards": running(root)}


def render_status(s: dict) -> str:
    if not s["boards"]:
        return f"no board serves {s['root']}"
    lines = []
    for b in s["boards"]:
        lines.append(f"pid {b['pid']}  {b.get('url') or 'port unknown'}  rite {b.get('version') or 'checkout'}"
                     f"  {'current' if b['current'] else 'stale'}  ({b['source']})")
    return "\n".join(lines)
