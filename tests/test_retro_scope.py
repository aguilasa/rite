"""A retro of some phases: `rite retro-scope`, and `stats` / `retro-suggest` with `--phase`."""

from __future__ import annotations

import json
import unittest

from fixtures import Fixture, write

CYCLE = "docs/rite/cycles/alpha"


class RetroScopeTest(unittest.TestCase):
    """alpha: phase 1 is ALP-TASK-01 and -02, phase 2 the closing ALP-TASK-03."""

    def setUp(self):
        self.fx = Fixture("subfolder")
        self.root = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def run_rite(self, *args) -> tuple[int, dict | None, str]:
        code, out, err = self.fx.rite(*args, "--json")
        return code, (json.loads(out) if out.strip() else None), err

    def js(self, *args) -> dict:
        code, data, err = self.run_rite(*args)
        self.assertEqual(code, 0, err)
        return data

    def ok(self, *args) -> None:
        code, out, err = self.fx.rite(*args)
        self.assertEqual(code, 0, err + out)

    def finish_phase_one(self) -> None:
        """Both tasks done and reviewed; a fix of ALP-TASK-02 and a fix of that fix, both closed."""
        for n, item_id in enumerate(("ALP-TASK-01", "ALP-TASK-02")):
            self.fx.work_commit(f"src/{n}.py", "x\n", f"feat: {item_id}")
            self.ok("close", item_id)
        self.ok("mark-reviewed", "ALP-TASK-01")
        first = self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-02", "--title", "a", "--severity", "low")
        self.ok("mark-reviewed", "ALP-TASK-02", "--fixes", first["id"])
        second = self.js("new-fix", "--cycle", "alpha", "--origin", first["id"], "--title", "b", "--severity", "low")
        for k, fix in enumerate((first["id"], second["id"])):
            self.fx.work_commit(f"src/fix{k}.py", "y\n", f"fix: {fix}")
            self.ok("close", fix)
        self.fixes = [first["id"], second["id"]]

    def test_a_finished_phase_is_ready_and_named_after_it(self):
        self.finish_phase_one()
        data = self.js("retro-scope", "alpha", "--phase", "1")
        self.assertEqual((data["phases"], data["ready"], data["exists"]), (["1"], True, False))
        self.assertEqual(data["file"], f"{CYCLE}/retro-phase-1.md")
        self.assertIsNone(data["detail"][0]["phase_review"])  # a warning, not a blocker
        write(self.root / CYCLE / "phase-1-review.md", "# Phase 1 review\n")
        self.assertEqual(self.js("retro-scope", "alpha", "--phase", "1")["detail"][0]["phase_review"],
                         f"{CYCLE}/phase-1-review.md")

    def test_a_phase_not_reviewable_blocks_with_what_is_left(self):
        self.fx.work_commit("src/0.py", "x\n", "feat: one")
        self.ok("close", "ALP-TASK-01")
        code, data, _ = self.run_rite("retro-scope", "alpha", "--phase", "1")
        self.assertEqual((code, data["ready"]), (1, False))
        row = data["detail"][0]
        self.assertEqual((row["pending"], row["unreviewed"]), (["ALP-TASK-02"], ["ALP-TASK-01"]))

    def test_several_phases_in_the_cycle_order_one_file(self):
        self.finish_phase_one()
        code, data, _ = self.run_rite("retro-scope", "alpha", "--phase", "2", "--phase", "1,2")
        self.assertEqual((code, data["phases"], data["ready"]), (1, ["1", "2"], False))
        self.assertEqual(data["file"], f"{CYCLE}/retro-phases-1-2.md")

    def test_unknown_phase_and_no_phase_are_refused(self):
        code, _, err = self.fx.rite("retro-scope", "alpha", "--phase", "9")
        self.assertEqual(code, 1)
        self.assertIn("phases: 1, 2", err)
        code, _, err = self.fx.rite("retro-scope", "alpha")
        self.assertEqual(code, 1)
        self.assertIn("--since-last", err)
        code, _, err = self.fx.rite("retro-scope", "alpha", "--phase", "1", "--since-last")
        self.assertEqual(code, 1)
        self.assertIn("exclude", err)

    def test_since_last_takes_ready_phases_no_partial_retro_covered(self):
        code, _, err = self.fx.rite("retro-scope", "alpha", "--since-last")
        self.assertEqual(code, 1)  # nothing ready yet
        self.finish_phase_one()
        data = self.js("retro-scope", "alpha", "--since-last")
        self.assertEqual((data["phases"], data["partials"]), (["1"], []))
        write(self.root / CYCLE / "retro-phase-1.md", "# Retro — alpha\n\nDate: 2026-11-23\nPhases: 1\n")
        code, _, err = self.fx.rite("retro-scope", "alpha", "--since-last")
        self.assertEqual(code, 1)  # phase 1 covered, phase 2 not reviewable
        self.assertIn("covered: 1", err)
        again = self.js("retro-scope", "alpha", "--phase", "1")
        self.assertEqual((again["exists"], again["detail"][0]["covered_by"]), (True, f"{CYCLE}/retro-phase-1.md"))
        self.assertEqual(self.js("retro-suggest", "alpha")["partials"],
                         [{"file": f"{CYCLE}/retro-phase-1.md", "phases": ["1"]}])

    def test_stats_and_suggest_count_only_the_phases_named(self):
        self.finish_phase_one()
        whole = self.js("stats", "alpha")
        self.assertIsNone(whole["scope"])
        one = self.js("stats", "alpha", "--phase", "1")
        self.assertEqual((one["scope"], one["tasks"]["total"], one["fixes"]["total"]),
                         ({"phases": ["1"]}, 2, 2))
        two = self.js("stats", "alpha", "--phase", "2")
        self.assertEqual((two["tasks"]["total"], two["fixes"]["total"], two["items_without_log"]), (1, 0, []))
        # a fix of a fix counts against the root task's phase
        self.assertEqual([k["fix"] for k in self.js("retro-suggest", "alpha", "--phase", "1")["keep"]], self.fixes)
        self.assertEqual(self.js("retro-suggest", "alpha", "--phase", "2")["keep"], [])
        code, _, err = self.fx.rite("stats", "alpha", "--phase", "7")
        self.assertEqual(code, 1)
        self.assertIn("no phase '7'", err)


if __name__ == "__main__":
    unittest.main()
