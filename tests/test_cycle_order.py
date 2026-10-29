"""`rite migrate --from cycle-order`: number the cycles of a project made before `seq`."""

from __future__ import annotations

import json
import os
import subprocess
import unittest

from fixtures import Fixture, fields, write


class CycleOrderMigrationTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture("subfolder")
        self.root = self.fx.root
        # the fixture commits alpha and beta together (a tie, by name); zeta, archived since, is older
        cyc = self.root / "docs/rite/cycles"
        write(cyc / "zeta/progress.md", "# Progress — zeta\n")
        write(cyc / "zeta/progress.json", '{"schema": 1, "cycle": "zeta", "prefix": "ZET", "tasks": []}')
        self.commit_at("2020-01-01T10:00:00", "chore: zeta")
        (cyc / "archive").mkdir(exist_ok=True)
        self.fx.git("mv", "docs/rite/cycles/zeta", "docs/rite/cycles/archive/zeta")
        self.commit_at("2030-01-01T10:00:00", "chore: archive zeta")

    def tearDown(self):
        self.fx.cleanup()

    def commit_at(self, when: str, message: str) -> None:
        self.fx.git("add", "-A")
        env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=self.root, check=True, env=env)

    def js(self, *args) -> dict:
        code, out, err = self.fx.rite("migrate", "--from", "cycle-order", *args, "--json")
        self.assertEqual(code, 0, err + out)
        return json.loads(out)

    def seqs(self) -> dict:
        cyc = self.root / "docs/rite/cycles"
        return {n: fields(p / "progress.md").get("seq") if (p / "progress.json").is_file() else None
                for n, p in (("alpha", cyc / "alpha"), ("beta", cyc / "beta"), ("zeta", cyc / "archive/zeta"))}

    def test_dry_run_proposes_by_first_commit_and_writes_nothing(self):
        data = self.js()
        self.assertEqual([c.split(":")[0] for c in data["cycles"]], ["zeta", "alpha", "beta"])
        self.assertIn("first commit of docs/rite/cycles/archive/zeta/progress.md (2020-01-01)", data["cycles"][0])
        self.assertEqual(self.seqs(), {"alpha": None, "beta": None, "zeta": None})

    def test_write_commit_then_rerun_is_a_no_op(self):
        data = self.js("--write", "--commit")
        self.assertEqual(self.seqs(), {"zeta": 1, "alpha": 2, "beta": 3})
        self.assertTrue(data["commit"])
        self.assertEqual(self.fx.git("log", "-1", "--format=%s").strip(), "chore(rite): number the cycles in seq")
        again = self.js("--write")
        self.assertEqual((again["changed"], sorted(again["skipped"])), ([], ["alpha", "beta", "zeta"]))
        code, out, _ = self.fx.rite("check", "--all", "--include-archived", "--json")
        self.assertFalse([f for f in json.loads(out)["findings"] if f["message"].startswith("no seq")])

    def test_missing_ones_follow_the_numbered(self):
        self.fx.rite("set-cycle", "--cycle", "beta", "--seq", "7")
        self.js("--write")
        self.assertEqual(self.seqs(), {"zeta": 8, "alpha": 9, "beta": 7})

    def test_order_renumbers_every_cycle_and_must_name_them_all(self):
        self.js("--write", "--order", "beta,zeta,alpha")
        self.assertEqual(self.seqs(), {"beta": 1, "zeta": 2, "alpha": 3})
        code, out, err = self.fx.rite("migrate", "--from", "cycle-order", "--order", "beta,alpha")
        self.assertNotEqual(code, 0)
        self.assertIn("missing: zeta", err + out)


if __name__ == "__main__":
    unittest.main()
