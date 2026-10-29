"""`rite serve`: a read-only board of the cycles, served over HTTP to a single-page app (board.html).

Open (live) and closed (archived) cycles, each with its tasks and fixes in the columns of the markdown
views, and each item's markdown. Nothing is written and nothing touches git: every request reads the
state from disk again. A watcher polls the state files and pushes a Server-Sent Event when they change,
so an open page follows `rite finish`, `mark`, `archive`… run elsewhere. Polling by `os.stat`, not
inotify: stdlib only, the same on every system, and a few dozen stats a second cost nothing.
"""

from __future__ import annotations

import errno
import json
import queue
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import config, render_md
from .config import OPEN_FIX_STATUSES
from .model import Cycle, Project, RiteError, display

PAGE = Path(__file__).resolve().parent / "board.html"
PING_SECONDS = 15
# a port taken (or refused) means "try the next one"; 10048/10013 are their Windows codes
_PORT_TAKEN = {errno.EADDRINUSE, errno.EACCES, 10048, 10013}

TASK_COLUMNS = ("id", "title", "phase", "type", "depends_on", "status", "done_on", "reviewed_on", "review")
FIX_COLUMNS = ("id", "title", "origin", "severity", "status", "done_on")


class Board:
    """What the handler serves and the watcher compares: cycles read from ``root`` on each call."""

    def __init__(self, root: Path, poll: float = 1.0):
        self.root = root
        self.poll = poll
        self.stopped = threading.Event()
        self.watching = threading.Event()  # set once the watcher holds its first snapshot
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def project(self) -> Project:
        return Project(config.load(self.root))

    def cycle_dirs(self, project: Project) -> list[tuple[Path, bool]]:
        """[(folder, archived)]: live cycles first, then the archive."""
        return ([(p, False) for p in project._cycle_dirs(project.cycles_root)]
                + [(p, True) for p in project.archived_dirs()])

    # --- what the API returns ------------------------------------------------
    def cycles(self) -> dict:
        project = self.project()
        out: dict = {"open": [], "closed": []}
        for path, archived in self.cycle_dirs(project):
            entry: dict = {"folder": display(project.root, path), "name": path.name, "archived": archived}
            try:
                cycle = project.load_cycle(path, archived=archived)
            except RiteError as exc:
                entry["error"] = str(exc)
            else:
                counts = {s: 0 for s in ("pending", "in-progress", "done", "blocked", "skipped")}
                for t in cycle.tasks:
                    counts[t.status] = counts.get(t.status, 0) + 1
                entry |= {"name": cycle.name, "prefix": cycle.prefix, "seq": cycle.seq, "tasks": counts | {"total": len(cycle.tasks)},
                          "open_fixes": sum(1 for f in cycle.fixes if f.status in OPEN_FIX_STATUSES)}
            out["closed" if archived else "open"].append(entry)
        return out

    def find(self, folder: str) -> tuple[Project, Cycle]:
        """The cycle whose folder is ``folder`` — only among the listed ones, never a free path."""
        project = self.project()
        for path, archived in self.cycle_dirs(project):
            if display(project.root, path) == folder:
                return project, project.load_cycle(path, archived=archived)
        raise LookupError(f"no cycle at {folder!r}")

    def cycle(self, folder: str) -> dict:
        project, cycle = self.find(folder)
        fix_fields = [f.fields for f in cycle.fixes]
        derived = {"depends_on": lambda t: t.depends_on,
                   "review": lambda t: render_md.review_status(t.fields, fix_fields)}
        tasks = [{k: derived[k](t) if k in derived else t.fields.get(k) for k in TASK_COLUMNS}
                 for t in cycle.tasks]
        fixes = [{k: f.fields.get(k) for k in FIX_COLUMNS} for f in cycle.fixes]
        return {"name": cycle.name, "prefix": cycle.prefix, "folder": folder, "archived": cycle.archived,
                "tasks": tasks, "fixes": fixes}

    def item(self, folder: str, item_id: str) -> dict:
        project, cycle = self.find(folder)
        item = cycle.by_id().get(item_id)
        if item is None:
            raise LookupError(f"no item {item_id!r} in {folder!r}")
        _, body, error = item.read_md()
        return {"id": item.id, "title": item.title, "kind": item.kind, "status": item.status,
                "severity": item.fields.get("severity"), "folder": folder, "cycle": cycle.name,
                "path": display(project.root, item.path), "markdown": body, "error": error}

    # --- live updates ----------------------------------------------------------
    def snapshot(self) -> dict[str, tuple]:
        """{folder: fingerprint} — (mtime, size) of the state files and the item files of each cycle."""
        project = self.project()
        out = {}
        for path, _ in self.cycle_dirs(project):
            files = [path / project.progress_state, path / project.fixes_state]
            files += [file for _, file, _ in project.item_files(path)]
            out[display(project.root, path)] = tuple((f.name, *_stat(f)) for f in files)
        return out

    def watch(self) -> None:
        """Compare snapshots every ``poll`` seconds and tell the subscribers what changed. Never dies:
        a file caught mid-write or a broken rite.toml is reported and tried again on the next round."""
        previous, delay = None, 0.0
        while not self.stopped.wait(delay):
            delay = self.poll
            try:
                current = self.snapshot()
            except Exception as exc:  # noqa: BLE001 — the watcher must outlive any bad read
                print(f"rite serve: watcher: {exc}", file=sys.stderr)
                continue
            if previous is not None:
                folders = sorted(f for f in current.keys() | previous.keys() if current.get(f) != previous.get(f))
                if folders:
                    self.publish({"folders": folders, "cycles": current.keys() != previous.keys()})
            previous = current
            self.watching.set()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, event: dict | None) -> None:
        with self._lock:
            for q in self._subscribers:
                q.put(event)

    def close(self) -> None:
        self.stopped.set()
        self.publish(None)  # wakes every open event stream so its thread ends


def _stat(path: Path) -> tuple:
    try:
        st = path.stat()
    except OSError:
        return (None, None)
    return (st.st_mtime_ns, st.st_size)


class _Handler(BaseHTTPRequestHandler):
    server: "_Server"

    def log_message(self, format, *args) -> None:  # noqa: A002 — the base class names it so
        pass

    def do_GET(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        board = self.server.board
        try:
            if url.path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/cycles":
                self._json(200, board.cycles())
            elif url.path == "/api/cycle":
                self._json(200, board.cycle(query.get("folder", "")))
            elif url.path == "/api/item":
                self._json(200, board.item(query.get("folder", ""), query.get("id", "")))
            elif url.path == "/api/events":
                self._events()
            else:
                self._json(404, {"error": f"not found: {url.path}"})
        except LookupError as exc:
            self._json(404, {"error": str(exc.args[0])})
        except (RiteError, config.ConfigError, OSError, ValueError) as exc:
            # a state file caught mid-write: the page retries
            self._json(503, {"error": str(exc)})

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _events(self) -> None:
        board = self.server.board
        q = board.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()
            while not board.stopped.is_set():
                try:
                    event = q.get(timeout=PING_SECONDS)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")  # keeps the connection open; a closed tab fails here
                else:
                    if event is None:
                        break
                    self.wfile.write(f"event: change\ndata: {json.dumps(event)}\n\n".encode("utf-8"))
                self.wfile.flush()
        except OSError:
            pass  # the tab went away
        finally:
            board.unsubscribe(q)


class _Server(ThreadingHTTPServer):
    # Linux only: there SO_REUSEADDR still refuses a port something listens on and only skips the
    # TIME_WAIT left by closed connections (a restart would otherwise land on 3001). On Windows it lets
    # a second server take a listening port, and on BSD/macOS bind 127.0.0.1 under someone's wildcard.
    allow_reuse_address = sys.platform.startswith("linux")
    daemon_threads = True
    board: Board


def bind(host: str, port: int, tries: int = 100) -> _Server:
    """A server on the first free port from ``port`` on: 3000 taken → 3001, 3002…"""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    server_class = type("_BoundServer", (_Server,), {"address_family": family})
    last = min(port + max(tries, 1), 65536)
    for candidate in range(port, last):
        try:
            return server_class((host, candidate), _Handler)
        except OSError as exc:
            if exc.errno not in _PORT_TAKEN:
                raise
    raise RiteError(f"no free port in {port}–{last - 1} on {host}")


def url_of(server: _Server) -> str:
    host, port = server.server_address[:2]
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    return f"http://{f'[{host}]' if ':' in host else host}:{port}/"


def serve(root: Path, *, host: str = "127.0.0.1", port: int = 3000, tries: int = 100, poll: float = 1.0,
          open_browser: bool = True, as_json: bool = False) -> int:
    """Serve until Ctrl+C. The socket listens once ``bind`` returns, so the browser opens on a ready
    server; the URL is printed first, for whoever runs this in the background."""
    board = Board(root, poll)
    server = bind(host, port, tries)
    server.board = board
    url = url_of(server)
    print(json.dumps({"url": url, "port": server.server_address[1]}) if as_json
          else f"rite board: {url}  (Ctrl+C to stop)", flush=True)
    threading.Thread(target=board.watch, name="rite-board-watch", daemon=True).start()
    if open_browser:
        try:
            opened = webbrowser.open(url)
        except Exception:  # noqa: BLE001 — no browser is not a reason to stop serving
            opened = False
        if not opened:
            print(f"rite serve: could not open a browser; open {url}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        board.close()
        server.server_close()
    return 0
