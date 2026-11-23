"""`rite plugin-info` / `rite clear-cache`: the installed rite and its cache, on a fake plugins folder."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fixtures import ROOT, rite  # noqa: F401  (fixtures puts the repository on sys.path)

from rite_lib import plugin
from rite_lib.model import RiteError


class PluginTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rite-plugins-")
        self.dir = Path(self._tmp.name) / "plugins"

    def tearDown(self):
        self._tmp.cleanup()

    def layout(self, *, cached=("0.30.0", "0.31.0", "0.32.0", "0.33.0"), installed="0.33.0", latest="0.33.0",
               running="0.32.0") -> Path:
        for v in cached:
            folder = self.dir / "cache/m/rite" / v
            (folder / ".claude-plugin").mkdir(parents=True)
            (folder / ".claude-plugin/plugin.json").write_text(json.dumps({"version": v}))
            (folder / "payload.txt").write_text("x" * 1000)
        (self.dir / "cache/m/rite/notes").mkdir()  # not a version: never touched
        if installed:
            (self.dir / "installed_plugins.json").write_text(json.dumps(
                {"version": 2, "plugins": {"rite@m": [{"version": installed, "gitCommitSha": "abc"}]}}))
        catalog = self.dir / "marketplaces/m/.claude-plugin"
        catalog.mkdir(parents=True)
        (catalog / "marketplace.json").write_text(json.dumps({"plugins": [{"name": "rite", "version": latest}]}))
        return self.dir / "cache/m/rite" / running

    def test_states(self):
        self.assertEqual(plugin.info(running_root=self.layout(latest="0.34.0"))["state"], "update-available")
        self.tearDown(); self.setUp()
        self.assertEqual(plugin.info(running_root=self.layout())["state"], "reload-needed")
        self.tearDown(); self.setUp()
        self.assertEqual(plugin.info(running_root=self.layout(running="0.33.0"))["state"], "up-to-date")
        self.tearDown(); self.setUp()
        self.layout()
        outside = plugin.info(plugins_dir=self.dir, running_root=ROOT)
        self.assertEqual((outside["state"], outside["running"]["from_cache"]), ("not-installed", False))
        self.assertFalse(any(c["removable"] for c in outside["cache"]))

    def test_info_names_the_commands_and_what_may_go(self):
        d = plugin.info(running_root=self.layout())
        self.assertEqual((d["marketplace"], d["plugin_id"], d["installed"]["version"]), ("m", "rite@m", "0.33.0"))
        self.assertEqual(d["commands"], {"refresh": "claude plugin marketplace update m",
                                         "update": "claude plugin update rite@m"})
        self.assertEqual([(c["version"], c["removable"]) for c in d["cache"]],
                         [("0.30.0", True), ("0.31.0", True), ("0.32.0", False), ("0.33.0", False)])

    def test_clear_keeps_the_running_and_the_installed(self):
        running = self.layout()
        dry = plugin.clear(running_root=running, dry_run=True)
        self.assertEqual([r["version"] for r in dry["would_remove"]], ["0.30.0", "0.31.0"])
        self.assertTrue((self.dir / "cache/m/rite/0.30.0").is_dir())
        done = plugin.clear(running_root=running)
        self.assertEqual([r["version"] for r in done["removed"]], ["0.30.0", "0.31.0"])
        self.assertEqual(done["freed_bytes"], dry["freed_bytes"])
        self.assertGreater(done["freed_bytes"], 0)
        left = sorted(p.name for p in (self.dir / "cache/m/rite").iterdir())
        self.assertEqual(left, ["0.32.0", "0.33.0", "notes"])
        self.assertEqual(done["kept"], [{"version": "0.32.0", "why": "running"},
                                        {"version": "0.33.0", "why": "installed"}])

    def test_clear_refuses_without_knowing_what_to_keep(self):
        running = self.layout(installed=None)
        with self.assertRaises(RiteError):
            plugin.clear(running_root=running)
        self.assertEqual(len(list((self.dir / "cache/m/rite").iterdir())), 5)
        self.tearDown(); self.setUp()
        self.layout()
        with self.assertRaises(RiteError):  # from a checkout: the folder the session loaded is unknown
            plugin.clear(plugins_dir=self.dir, running_root=ROOT)

    def test_the_cli_needs_no_rite_toml(self):
        self.layout()
        empty = Path(self._tmp.name) / "no-repo"
        empty.mkdir()
        from rite_lib import cli
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["plugin-info", "--plugins-dir", str(self.dir), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["marketplace"], "m")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["clear-cache", "--dry-run", "--plugins-dir", str(self.dir)]), 1)


if __name__ == "__main__":
    unittest.main()
