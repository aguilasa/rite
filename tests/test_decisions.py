"""`[decisions].recommend`: the ranked next steps (`options`) the commands ask from, only when on."""

from __future__ import annotations

import json
import unittest

from fixtures import Fixture


class DecisionsTest(unittest.TestCase):
    """alpha: ALP-TASK-01 and -02 in phase 1, the closing ALP-TASK-03 (after -02) in phase 2."""

    def setUp(self):
        self.fx = Fixture("subfolder")
        self.root = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def js(self, *args) -> dict:
        code, out, err = self.fx.rite(*args, "--json")
        self.assertEqual(code, 0, err + out)
        return json.loads(out)

    def turn_on(self, value: str = "true") -> None:
        with (self.root / "rite.toml").open("a", encoding="utf-8") as fh:
            fh.write(f"\n[decisions]\nrecommend = {value}\n")
        self.fx.git("commit", "-q", "-am", "chore: decisions")

    def status(self) -> dict:
        return next(c for c in self.js("status", "--all")["cycles"] if c["cycle"] == "alpha")

    def close(self, *ids: str) -> None:
        for n, item_id in enumerate(ids):
            self.fx.work_commit(f"src/{item_id}.py", "x\n", f"feat: {item_id}")
            code, out, err = self.fx.rite("close", item_id)
            self.assertEqual(code, 0, err + out)

    def high_fix(self) -> str:
        return self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "t",
                       "--severity", "high")["id"]

    def test_off_by_default_nothing_new_in_the_output(self):
        self.assertEqual(self.js("resolve-cycle", "alpha")["decisions"], {"recommend": False})
        self.assertEqual(self.js("begin", "task", "--cycle", "alpha", "--no-claim")["decisions"],
                         {"recommend": False})
        self.assertNotIn("options", self.status())
        self.assertNotIn("options", self.js("next", "task", "--cycle", "alpha"))
        self.close("ALP-TASK-01")
        self.assertNotIn("options", self.js("phase", "alpha", "--phase", "1"))
        self.fx.work_commit("src/b.py", "y\n", "feat: b")
        self.assertNotIn("options", self.js("finish", "ALP-TASK-02")["next"])
        self.assertNotIn("options:", self.fx.rite("status", "--all")[1])

    def test_a_value_that_is_not_a_boolean_is_refused(self):
        self.turn_on('"yes"')
        code, _, err = self.fx.rite("status", "--all")
        self.assertEqual(code, 1)
        self.assertIn("[decisions].recommend must be true or false", err)

    def test_on_reports_the_flag_and_never_ranks_next_commands(self):
        # the next /rite: command is never a question: no `options` anywhere, flag on or off
        self.turn_on()
        self.assertEqual(self.js("resolve-cycle", "alpha")["decisions"], {"recommend": True})
        self.assertEqual(self.js("begin", "task", "--cycle", "alpha", "--no-claim")["decisions"],
                         {"recommend": True})
        self.close("ALP-TASK-01")
        self.high_fix()
        self.assertNotIn("options", self.status())
        self.assertNotIn("options", self.js("next", "review", "--cycle", "alpha"))
        self.assertNotIn("options", self.js("phase", "alpha", "--phase", "1"))
        self.fx.work_commit("src/b.py", "y\n", "feat: b")
        self.assertNotIn("options", self.js("finish", "ALP-TASK-02")["next"])
        self.assertNotIn("options:", self.fx.rite("status", "--all")[1])


class DecisionsDocTest(unittest.TestCase):
    """The rules live in docs/DECISIONS.md, read only with the flag on; each command points to it."""

    COMMANDS = ("execute", "execute-batch", "execute-phase", "review", "review-all", "review-phase",
                "fix", "fix-all")

    def test_every_covered_command_points_to_the_rules_and_they_name_it(self):
        from fixtures import ROOT
        doc = (ROOT / "docs/DECISIONS.md").read_text(encoding="utf-8")
        for name in self.COMMANDS:
            text = (ROOT / "commands" / f"{name}.md").read_text(encoding="utf-8")
            self.assertIn("${CLAUDE_PLUGIN_ROOT}/docs/DECISIONS.md", text, name)
            self.assertIn(f"`{name}`", doc, name)
        for rule in ("(Recommended)", "two or more", "--yes", "never one that deletes",
                     "command is never a\n  question"):
            self.assertIn(rule, doc, rule)
        self.assertNotIn("`options`", doc)


if __name__ == "__main__":
    unittest.main()
