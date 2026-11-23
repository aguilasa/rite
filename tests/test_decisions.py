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

    def test_one_path_is_one_option(self):
        self.turn_on()
        self.assertEqual(self.js("resolve-cycle", "alpha")["decisions"], {"recommend": True})
        s = self.status()
        self.assertEqual(s["options"], [{"command": "execute", "reason": "next task ALP-TASK-01 is ready",
                                         "recommended": True}])

    def test_options_rank_the_suggestion_first_and_skip_repeats(self):
        self.turn_on()
        self.close("ALP-TASK-01")
        s = self.status()
        self.assertEqual([(o["command"], o["recommended"]) for o in s["options"]],
                         [("execute", True), ("review", False)])
        self.high_fix()
        s = self.status()
        self.assertEqual(s["options"][0]["command"], s["suggestion"]["command"])
        self.assertEqual([(o["command"], o["recommended"]) for o in s["options"]],
                         [("fix", True), ("execute", False), ("review", False)])
        self.assertIn("*/rite:fix", self.fx.rite("status", "--all")[1])

    def test_two_pressures_are_two_recommended_options(self):
        self.turn_on()
        self.close("ALP-TASK-01", "ALP-TASK-02", "ALP-TASK-03")
        self.high_fix()
        s = self.status()
        self.assertEqual([(o["command"], o["recommended"]) for o in s["options"]],
                         [("fix", True), ("review", True)])

    def test_finish_next_and_phase_carry_the_options(self):
        self.turn_on()
        self.close("ALP-TASK-01")
        self.fx.work_commit("src/b.py", "y\n", "feat: b")
        nxt = self.js("finish", "ALP-TASK-02")["next"]
        self.assertEqual(nxt["options"][0]["command"], "execute")  # ALP-TASK-03 is ready now
        self.assertIn("options", self.js("next", "review", "--cycle", "alpha"))
        self.assertIn("options", self.js("phase", "alpha", "--phase", "1"))
        self.assertEqual(self.js("begin", "task", "--cycle", "alpha", "--no-claim")["decisions"],
                         {"recommend": True})


if __name__ == "__main__":
    unittest.main()
