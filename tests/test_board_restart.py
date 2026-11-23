"""`rite serve --restart` / `--if-stale` and `rite board-status`: a board knows what it runs."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import unittest
import urllib.request

from fixtures import ROOT, Fixture
from rite_lib import boardproc

CLI = str(ROOT / "bin" / "rite.py")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ParsePsTest(unittest.TestCase):
    def test_only_rite_serve_lines_with_their_version_and_root(self):
        text = "\n".join([
            " 101 python3 /h/.claude/plugins/cache/rite/rite/0.34.0/bin/rite.py serve",
            " 102 python3 /src/rite/bin/rite.py serve --root /work/repo --port 3001",
            " 103 python3 /h/.claude/plugins/cache/rite/rite/0.34.0/bin/rite.py status",
            " 104 vim serve.txt",
        ])
        found = boardproc.parse_ps(text)
        self.assertEqual([(p["pid"], p["version"], p["root"]) for p in found],
                         [(101, "0.34.0", None), (102, None, "/work/repo")])
        self.assertEqual(found[0]["rite_root"], "/h/.claude/plugins/cache/rite/rite/0.34.0")


@unittest.skipUnless(os.name == "posix", "boards are stopped by signal on POSIX")
class RestartTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture("subfolder")
        self.root = self.fx.root
        self.procs: list[subprocess.Popen] = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()
        boardproc.registry_path(self.root).unlink(missing_ok=True)
        self.fx.cleanup()

    def serve(self, *args: str) -> tuple[subprocess.Popen, str]:
        proc = subprocess.Popen([sys.executable, CLI, "serve", "--root", str(self.root), "--no-browser", *args],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.procs.append(proc)
        return proc, proc.stdout.readline().strip()

    def status(self) -> dict:
        out = subprocess.run([sys.executable, CLI, "board-status", "--root", str(self.root), "--json"],
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_a_board_announces_itself_and_a_second_call_reuses_it(self):
        port = _free_port()
        first, line = self.serve("--port", str(port))
        self.assertIn(f":{port}/", line)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/info", timeout=5) as res:
            info = json.loads(res.read())
        self.assertEqual((info["pid"], info["root"]), (first.pid, str(self.root.resolve())))
        [b] = self.status()["boards"]
        self.assertEqual((b["pid"], b["current"], b["source"]), (first.pid, True, "registry"))
        again, line = self.serve("--if-stale")
        self.assertEqual(again.wait(10), 0)
        self.assertIn(f"already running, pid {first.pid}", line)
        self.assertIsNone(first.poll())

    def test_restart_stops_the_board_and_takes_its_port(self):
        port = _free_port()
        first, _ = self.serve("--port", str(port))
        self.status()
        second, line = self.serve("--restart")
        self.assertEqual(first.wait(10), 0)  # SIGTERM ends it as Ctrl+C does
        self.assertIn(f":{port}/", line)
        self.assertIn(f"stopped pid {first.pid}", line)
        [b] = self.status()["boards"]
        self.assertEqual(b["pid"], second.pid)

    def test_a_board_of_another_install_is_stale_and_if_stale_replaces_it(self):
        # another install of rite (an older version in the plugin cache, here a copy) serves the repo
        other = self.root.parent / f"{self.root.name}-other-rite"
        for part in ("bin", "rite_lib", ".claude-plugin"):
            shutil.copytree(ROOT / part, other / part, ignore=shutil.ignore_patterns("__pycache__"))
        port = _free_port()
        old = subprocess.Popen([sys.executable, str(other / "bin/rite.py"), "serve", "--root", str(self.root),
                                "--no-browser", "--port", str(port)],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.procs.append(old)
        old.stdout.readline()
        [b] = self.status()["boards"]
        self.assertEqual((b["pid"], b["current"]), (old.pid, False))
        new, line = self.serve("--if-stale")
        self.assertEqual(old.wait(10), 0)
        self.assertIn(f":{port}/", line)
        [b] = self.status()["boards"]
        self.assertEqual((b["pid"], b["current"]), (new.pid, True))
        shutil.rmtree(other)

    def test_a_registry_left_by_a_dead_board_is_dropped(self):
        path = boardproc.registry_path(self.root)
        path.write_text(json.dumps({"pid": 999999, "url": "http://127.0.0.1:1/", "root": str(self.root)}))
        self.assertEqual(self.status()["boards"], [])
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
