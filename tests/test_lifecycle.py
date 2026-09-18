import json
import unittest

from fixtures import write

from test_cli import FixtureCase, fields


def finish_cycle(case: FixtureCase, cycle: str, ids: list[str]) -> None:
    """Close and review every task of a cycle through the CLI."""
    for n, item_id in enumerate(ids):
        case.fx.work_commit(f"src/{cycle}_{n}.py", f"x = {n}\n", f"feat: {item_id}")
        case.ok("close", item_id)
        case.ok("mark-reviewed", item_id)


class NewCycleTest(FixtureCase):
    def test_new_cycle_creates_views_profile_and_pitfalls(self):
        res = self.js("new-cycle", "gamma", "--prefix", "GAM", "--plan", "docs/plans/PLAN-alpha.md", "--commit")
        self.assertEqual(res["path"], "docs/rite/cycles/gamma")
        self.assertIn("docs/rite/profiles/gamma.md", res["created"])
        self.assertIn("docs/rite/profiles/gamma.pitfalls.md", res["created"])
        self.assertEqual(self.log(1), ["chore(rite): new cycle gamma"])
        meta = fields(self.root / "docs/rite/cycles/gamma/progress.md")
        self.assertEqual((meta["prefix"], meta["plan"]), ("GAM", "/docs/plans/PLAN-alpha.md"))
        new = self.js("new-task", "--cycle", "gamma", "--title", "First", "--type", "feature", "--phase", "1",
                      "--source-of-truth", "/docs/plans/PLAN-alpha.md#1")
        self.assertEqual(new["id"], "GAM-TASK-01")
        # the skeleton profile has no entry for phase 1 yet: check must say so
        errors = self.check_errors("--cycle", "gamma")
        self.assertTrue(any("no entry for phase 1" in e for e in errors), errors)

    def test_refusals(self):
        self.assertEqual(self.fx.rite("new-cycle", "alpha", "--prefix", "ZZZ")[0], 1)
        code, _, err = self.fx.rite("new-cycle", "delta", "--prefix", "ALP")
        self.assertEqual(code, 1)
        self.assertIn("used by live cycle alpha", err)
        self.assertEqual(self.fx.rite("new-cycle", "bad name", "--prefix", "X")[0], 1)


class ArchiveTest(FixtureCase):
    def test_blockers_then_archive_with_link_rewrite(self):
        code, out, _ = self.fx.rite("archive", "alpha", "--dry-run", "--json")
        self.assertEqual(code, 1)
        self.assertIn("ALP-TASK-01 is pending", json.loads(out)["blockers"])

        # an outside doc links into the cycle; the cycle links out to the plan
        write(self.root / "docs/index.md", "# Index\n\n[alpha](/docs/rite/cycles/alpha/progress.md)\n"
                                           "\n```\n[code](/docs/rite/cycles/alpha/progress.md)\n```\n")
        self.fx.git("add", "docs/index.md")
        self.fx.git("commit", "-q", "-m", "docs: index")
        finish_cycle(self, "alpha", ["ALP-TASK-01", "ALP-TASK-02", "ALP-TASK-03"])
        self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-02", "--title", "late", "--severity", "low")
        self.assertIn("is open", " ".join(json.loads(self.fx.rite("archive", "alpha", "--json")[1])["blockers"]))
        self.fx.work_commit("src/late.py", "y\n", "fix: late")
        self.ok("close", "FIX-ALP-001")

        res = self.js("archive", "alpha")
        self.assertEqual(res["to"], "docs/rite/cycles/archive/alpha")
        self.assertEqual(self.log(1), ["chore(rite): archive alpha"])
        index = (self.root / "docs/index.md").read_text(encoding="utf-8")
        self.assertIn("[alpha](/docs/rite/cycles/archive/alpha/progress.md)", index)
        self.assertIn("[code](/docs/rite/cycles/alpha/progress.md)", index)  # code blocks untouched
        self.assertFalse((self.root / "docs/rite/cycles/alpha").exists())
        self.assertEqual(self.fx.git("status", "--porcelain"), "")
        self.assertEqual(self.check_errors("--all"), [])
        status = self.js("status", "--all")
        self.assertEqual([c["cycle"] for c in status["cycles"]], ["beta"])


class ArchiveRelativeTest(FixtureCase):
    layout = "legacy"

    def test_relative_links_follow_the_move(self):
        write(self.root / "docs/README.md", "[wte](tasks/wte/progresso.md)\n")
        self.fx.git("add", "docs/README.md")
        self.fx.git("commit", "-q", "-m", "docs: readme")
        finish_cycle(self, "wte", ["WTE-TASK-01", "WTE-TASK-02"])
        self.ok("archive", "wte")
        moved = self.root / "docs/tasks/concluidos/wte/01-extrair-tabelas.md"
        self.assertEqual(fields(moved)["source_of_truth"], "../../../PLAN-WTE.md#2.1")
        self.assertEqual((self.root / "docs/README.md").read_text(encoding="utf-8"),
                         "[wte](tasks/concluidos/wte/progresso.md)\n")
        self.assertEqual(self.check_errors("--all"), [])


class AnchorsAndStatsTest(FixtureCase):
    def test_anchors_are_valid_source_of_truth(self):
        data = self.js("anchors", "docs/plans/PLAN-alpha.md")
        sots = [h["source_of_truth"] for h in data["headings"]]
        self.assertIn("/docs/plans/PLAN-alpha.md#2.1", sots)
        self.assertIn("/docs/plans/PLAN-alpha.md#plan--alpha", sots)
        for sot in sots:  # every anchor it proposes must pass check
            self.js("new-task", "--cycle", "alpha", "--title", "t", "--type", "tool", "--phase", "1",
                    "--source-of-truth", sot)
        self.assertEqual(self.check_errors("--all"), [])

    def test_stats(self):
        finish_cycle(self, "alpha", ["ALP-TASK-01"])
        self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "a", "--severity", "high")
        s = self.js("stats", "alpha")
        self.assertEqual(s["tasks"]["total"], 3)
        self.assertEqual(s["fixes"]["by_severity"]["high"], 1)
        self.assertEqual(s["fixes_by_origin"], {"ALP-TASK-01": 1})
        self.assertEqual(s["review_latency_days"]["reviewed"], 1)
        self.assertEqual(s["by_phase"]["1"], {"tasks": 2, "fixes": 1})


class AnchorsRelativeTest(FixtureCase):
    layout = "legacy"

    def test_relative_anchor_from_cycle_folder(self):
        data = self.js("anchors", "docs/PLAN-WTE.md", "--cycle", "wte")
        self.assertIn("../../PLAN-WTE.md#2.1", [h["source_of_truth"] for h in data["headings"]])


if __name__ == "__main__":
    unittest.main()
