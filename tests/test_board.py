"""`rite serve`: port fallback, the board's API, and the change events it pushes."""

import json
import os
import queue
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from fixtures import Fixture, write
from rite_lib import board
from rite_lib.model import RiteError


def _listening(port: int = 0) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", port))
    s.listen()
    return s


class BindTest(unittest.TestCase):
    def test_taken_port_moves_to_the_next(self):
        taken = _listening()
        port = taken.getsockname()[1]
        try:
            server = board.bind("127.0.0.1", port, tries=20)
        except RiteError:
            self.skipTest("the ports after the taken one are busy too")
        try:
            self.assertGreater(server.server_address[1], port)
            self.assertEqual(board.url_of(server), f"http://127.0.0.1:{server.server_address[1]}/")
        finally:
            server.server_close()
            taken.close()

    def test_no_free_port_is_an_error(self):
        taken = _listening()
        try:
            with self.assertRaisesRegex(RiteError, "no free port"):
                board.bind("127.0.0.1", taken.getsockname()[1], tries=1)
        finally:
            taken.close()


class BoardTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture("subfolder")
        self.root = self.fx.root
        arch = self.root / "docs/rite/cycles/archive/old"
        write(arch / "progress.json", '{"schema": 1, "cycle": "old", "prefix": "OLD", "tasks": []}')
        self.board = board.Board(self.root, poll=0.05)
        self.server = board.bind("127.0.0.1", _free_port(), tries=50)
        self.server.board = self.board
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        threading.Thread(target=self.board.watch, daemon=True).start()
        self.assertTrue(self.board.watching.wait(5), "the watcher took no snapshot")
        self.url = board.url_of(self.server)

    def tearDown(self):
        self.board.close()
        self.server.shutdown()
        self.server.server_close()
        self.fx.cleanup()

    def get(self, path: str):
        with urllib.request.urlopen(self.url + path.lstrip("/"), timeout=5) as res:
            body = res.read().decode("utf-8")
            return json.loads(body) if res.headers.get_content_type() == "application/json" else body

    def status_of(self, path: str) -> int:
        try:
            urllib.request.urlopen(self.url + path.lstrip("/"), timeout=5).close()
        except urllib.error.HTTPError as exc:
            return exc.code
        return 200

    def test_page(self):
        page = self.get("/")
        self.assertIn('<div id="app"', page)
        self.assertIn("data-filters", page)

    def test_cycles_open_and_closed(self):
        data = self.get("/api/cycles")
        self.assertEqual([c["name"] for c in data["open"]], ["alpha", "beta"])
        self.assertEqual([c["folder"] for c in data["closed"]], ["docs/rite/cycles/archive/old"])
        alpha = data["open"][0]
        self.assertEqual((alpha["prefix"], alpha["tasks"]["total"], alpha["open_fixes"]), ("ALP", 3, 0))

    def test_cycle_has_the_columns_of_the_markdown_views(self):
        self.fx.rite("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "Broken", "--severity", "high")
        data = self.get("/api/cycle?folder=docs/rite/cycles/alpha")
        self.assertEqual([t["id"] for t in data["tasks"]], ["ALP-TASK-01", "ALP-TASK-02", "ALP-TASK-03"])
        self.assertEqual(list(data["tasks"][0]), list(board.TASK_COLUMNS))
        self.assertEqual(data["tasks"][1]["depends_on"], ["ALP-TASK-01"])
        self.assertEqual(list(data["fixes"][0]), list(board.FIX_COLUMNS))
        self.assertEqual((data["fixes"][0]["origin"], data["fixes"][0]["severity"]), ("ALP-TASK-01", "high"))

    def test_item_markdown(self):
        data = self.get("/api/item?folder=docs/rite/cycles/alpha&id=ALP-TASK-02")
        self.assertEqual((data["title"], data["kind"], data["path"]),
                         ("Report", "task", "docs/rite/cycles/alpha/02-report.md"))
        self.assertIn("# ALP-TASK-02 — Report", data["markdown"])

    def test_unknown_or_outside_is_404(self):
        self.assertEqual(self.status_of("/api/item?folder=docs/rite/cycles/alpha&id=ALP-TASK-99"), 404)
        self.assertEqual(self.status_of("/api/cycle?folder=../.."), 404)
        self.assertEqual(self.status_of("/api/item?folder=docs/plans&id=x"), 404)
        self.assertEqual(self.status_of("/nothing"), 404)

    def test_a_status_change_is_pushed(self):
        q = self.board.subscribe()
        self.fx.rite("mark", "ALP-TASK-01", "blocked", "--reason", "waiting")
        self.assertEqual(q.get(timeout=5), {"folders": ["docs/rite/cycles/alpha"], "cycles": False})

    def test_a_new_cycle_changes_the_list(self):
        q = self.board.subscribe()
        write(self.root / "docs/rite/cycles/gamma/progress.json",
              '{"schema": 1, "cycle": "gamma", "prefix": "GAM", "tasks": []}')
        self.assertEqual(q.get(timeout=5), {"folders": ["docs/rite/cycles/gamma"], "cycles": True})

    def test_the_watcher_outlives_a_broken_state_file(self):
        q = self.board.subscribe()
        progress = self.root / "docs/rite/cycles/beta/progress.json"
        good = progress.read_text(encoding="utf-8")
        progress.write_text("{", encoding="utf-8")
        q.get(timeout=5)
        self.assertEqual(self.status_of("/api/cycle?folder=docs/rite/cycles/beta"), 503)
        progress.write_text(good + "\n", encoding="utf-8")
        self.assertIn("docs/rite/cycles/beta", q.get(timeout=5)["folders"])
        self.assertEqual(self.get("/api/cycle?folder=docs/rite/cycles/beta")["name"], "beta")

    def test_event_stream(self):
        lines: queue.Queue = queue.Queue()

        def read():
            with urllib.request.urlopen(self.url + "api/events", timeout=10) as res:
                for raw in res:
                    lines.put(raw.decode("utf-8").rstrip("\n"))

        threading.Thread(target=read, daemon=True).start()
        self.assertEqual(lines.get(timeout=5), "retry: 2000")
        self.fx.rite("mark", "BET-TASK-01", "in-progress")
        got = [lines.get(timeout=5) for _ in range(3)]
        self.assertEqual(got[1:], ["event: change", 'data: {"folders": ["docs/rite/cycles/beta"], "cycles": false}'])

    def test_every_view_mounts_in_a_browser(self):
        """The page itself, in a real browser: needs Chrome and the CDN, so it runs only when asked."""
        chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
        if os.environ.get("RITE_BROWSER_TESTS") != "1" or not chrome:
            self.skipTest("set RITE_BROWSER_TESTS=1 with Chrome on PATH")
        folder = "docs%2Frite%2Fcycles%2Falpha"
        with tempfile.TemporaryDirectory() as profile:
            for view in ("#/", f"#/cycle/{folder}?tab=fixes", f"#/item/{folder}/ALP-TASK-01"):
                run = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                                      f"--user-data-dir={profile}", "--enable-logging=stderr", "--timeout=5000",
                                      "--dump-dom", self.url + view], capture_output=True, text=True, timeout=60)
                self.assertNotIn("Uncaught", run.stderr, view)
                self.assertIn('<div id="app"', run.stdout, view)
                self.assertNotIn('<div id="app" v-cloak', run.stdout, view)


def _free_port() -> int:
    s = _listening()
    port = s.getsockname()[1]
    s.close()
    return port


if __name__ == "__main__":
    unittest.main()
