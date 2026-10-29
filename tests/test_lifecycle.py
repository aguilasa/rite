import json
import tempfile
import unittest
from pathlib import Path

from fixtures import set_fields, write

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


class CycleSeqTest(FixtureCase):
    """Cycles keep their order in `seq`; listings follow it, not folder names."""

    def seq(self, cycle: str) -> int | None:
        return fields(self.root / f"docs/rite/cycles/{cycle}/progress.md").get("seq")

    def test_new_cycles_are_numbered_after_every_cycle_archived_included(self):
        arch = self.root / "docs/rite/cycles/archive/old"
        write(arch / "progress.json", '{"schema": 1, "cycle": "old", "prefix": "OLD", "seq": 4, "tasks": []}')
        self.assertEqual(self.js("new-cycle", "gamma", "--prefix", "GAM")["seq"], 5)
        self.assertEqual(self.js("new-cycle", "aaa", "--prefix", "AAA")["seq"], 6)
        self.assertEqual(self.seq("gamma"), 5)
        # without seq last, by name; then by seq whatever the name
        self.assertEqual([c["cycle"] for c in self.js("status", "--all")["cycles"]], ["gamma", "aaa", "alpha", "beta"])
        self.assertEqual(self.js("resolve-cycle", "aaa")["seq"], 6)

    def test_set_cycle_seq_reorders_and_check_warns_missing_and_duplicate(self):
        self.ok("set-cycle", "--cycle", "beta", "--seq", "1")
        self.ok("set-cycle", "--cycle", "alpha", "--seq", "2")
        self.assertEqual([c["cycle"] for c in self.js("status", "--all")["cycles"]], ["beta", "alpha"])
        for bad in ("0", "x"):
            self.assertNotEqual(self.fx.rite("set-cycle", "--cycle", "beta", "--seq", bad)[0], 0)
        self.ok("set-cycle", "--cycle", "alpha", "--seq", "1")
        warnings = [f["message"] for f in self.js("check", "--all")["findings"] if f["level"] == "warn"]
        self.assertIn("seq 1 is also cycle beta's (rite set-cycle --seq N)", warnings)
        self.ok("set-cycle", "--cycle", "alpha", "--seq", "2")
        write(self.root / "docs/rite/cycles/archive/old/progress.json",
              '{"schema": 1, "cycle": "old", "prefix": "OLD", "tasks": []}')
        out = json.loads(self.fx.rite("check", "--all", "--include-archived", "--json")[1])
        warnings = [f["message"] for f in out["findings"] if f["level"] == "warn"]
        self.assertTrue(any(w.startswith("no seq") for w in warnings), warnings)

    def test_retro_suggest_previous_follows_seq(self):
        self.ok("set-cycle", "--cycle", "beta", "--seq", "1")
        self.ok("set-cycle", "--cycle", "alpha", "--seq", "2")
        self.assertEqual(self.js("retro-suggest", "alpha")["previous"], "beta")
        self.assertIsNone(self.js("retro-suggest", "beta")["previous"])


class NewCycleCopyPlanTest(FixtureCase):
    def setUp(self):
        super().setUp()
        self.outside = tempfile.TemporaryDirectory()
        self.addCleanup(self.outside.cleanup)
        self.source = Path(self.outside.name) / "draft.md"
        self.source.write_bytes(b"# Draft\n\n## 1. Scope\n")

    def test_outside_plan_without_the_flag_is_refused(self):
        code, _, err = self.fx.rite("new-cycle", "gamma", "--prefix", "GAM", "--plan", str(self.source))
        self.assertEqual(code, 1)
        self.assertIn("--copy-plan", err)
        self.assertFalse((self.root / "docs/rite/cycles/gamma").exists())
        self.assertEqual(self.fx.git("status", "--porcelain"), "")

    def test_outside_plan_is_copied_and_committed(self):
        res = self.js("new-cycle", "gamma", "--prefix", "GAM", "--plan", str(self.source), "--copy-plan", "--commit")
        target = self.root / "docs/plans/draft.md"
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        self.assertEqual((res["plan"], res["plan_copied_from"]), ("docs/plans/draft.md", str(self.source)))
        self.assertEqual(fields(self.root / "docs/rite/cycles/gamma/progress.md")["plan"], "/docs/plans/draft.md")
        self.assertEqual(self.log(1), ["chore(rite): new cycle gamma"])
        self.assertIn("docs/plans/draft.md", self.fx.git("show", "--name-only", "--format=", "HEAD").splitlines())
        self.assertEqual(self.fx.git("status", "--porcelain"), "")

    def test_identical_target_is_reused(self):
        write(self.root / "docs/plans/draft.md", self.source.read_text(encoding="utf-8"))
        self.fx.git("add", "docs/plans/draft.md")
        self.fx.git("commit", "-q", "-m", "docs: draft")
        res = self.js("new-cycle", "gamma", "--prefix", "GAM", "--plan", str(self.source), "--copy-plan", "--commit")
        self.assertEqual(res["plan_copied_from"], str(self.source))
        self.assertNotIn("docs/plans/draft.md", res["created"])
        self.assertNotIn("docs/plans/draft.md", self.fx.git("show", "--name-only", "--format=", "HEAD").splitlines())

    def test_different_target_is_never_overwritten(self):
        target = self.root / "docs/plans/draft.md"
        write(target, "# Another draft\n")
        before = target.read_bytes()
        code, _, err = self.fx.rite("new-cycle", "gamma", "--prefix", "GAM", "--plan", str(self.source), "--copy-plan")
        self.assertEqual(code, 1)
        self.assertIn("already exists and differs", err)
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse((self.root / "docs/rite/cycles/gamma").exists())

    def test_plan_already_in_plans_dir_is_not_copied(self):
        res = self.js("new-cycle", "gamma", "--prefix", "GAM", "--plan", "docs/plans/PLAN-alpha.md", "--copy-plan")
        self.assertIsNone(res["plan_copied_from"])
        self.assertEqual(res["plan"], "docs/plans/PLAN-alpha.md")

    def test_copy_plan_needs_a_plan(self):
        code, _, err = self.fx.rite("new-cycle", "gamma", "--prefix", "GAM", "--copy-plan")
        self.assertEqual(code, 1)
        self.assertIn("--plan", err)
        self.assertFalse((self.root / "docs/rite/cycles/gamma").exists())

    def test_local_cycle_copies_without_committing(self):
        write(self.root / ".gitignore", "docs/rite/cycles/gamma/\ndocs/rite/profiles/gamma*\n")
        self.fx.git("add", ".gitignore")
        self.fx.git("commit", "-q", "-m", "chore: ignore gamma")
        before = self.log()
        res = self.js("new-cycle", "gamma", "--prefix", "GAM", "--local", "--plan", str(self.source),
                      "--copy-plan", "--commit")
        self.assertIsNone(res["commit"])
        self.assertTrue((self.root / "docs/plans/draft.md").is_file())
        self.assertIn("docs/plans/draft.md", res["ignored"])
        self.assertFalse(res["ignored"]["docs/plans/draft.md"])
        self.assertEqual(self.log(), before)

    def test_inside_plan_outside_plans_dir_is_linked_in_place(self):
        write(self.root / "notes/p.md", "# Notes\n")
        res = self.js("new-cycle", "gamma", "--prefix", "GAM", "--plan", "notes/p.md")
        self.assertIsNone(res["plan_copied_from"])
        self.assertEqual(fields(self.root / "docs/rite/cycles/gamma/progress.md")["plan"], "/notes/p.md")


class NewCycleCopyPlanRelativeTest(FixtureCase):
    layout = "legacy"

    def test_relative_link_points_at_the_copy(self):
        with tempfile.TemporaryDirectory() as outside:
            source = Path(outside) / "draft.md"
            source.write_text("# Draft\n", encoding="utf-8")
            self.js("new-cycle", "gamma", "--prefix", "GAM", "--plan", str(source), "--copy-plan")
        progress = self.root / "docs/tasks/gamma/progresso.md"
        link = fields(progress)["plan"]
        self.assertEqual(link, "../../draft.md")
        self.assertEqual((progress.parent / link).resolve(), (self.root / "docs/draft.md").resolve())


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
        # mentions that are not links: reported by archive, never rewritten
        self.fx.work_commit("src/tool.py", "x = 1\n# see docs/rite/cycles/alpha/01-harness.md\n", "feat: tool")
        self.fx.work_commit("docs/notes.md", "# Notes\n\n<!-- from docs/rite/cycles/alpha -->\n"
                                             "docs/rite/cycles/alpha-2 is another folder\n", "docs: notes")
        finish_cycle(self, "alpha", ["ALP-TASK-01", "ALP-TASK-02", "ALP-TASK-03"])
        self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-02", "--title", "late", "--severity", "low")
        self.assertIn("is open", " ".join(json.loads(self.fx.rite("archive", "alpha", "--json")[1])["blockers"]))
        self.fx.work_commit("src/late.py", "y\n", "fix: late")
        self.ok("close", "FIX-ALP-001")

        preview = self.js("archive", "alpha", "--dry-run")["unrewritten"]
        self.assertEqual(sorted((h["path"], h["line"]) for h in preview),
                         [("docs/index.md", 6), ("docs/notes.md", 3), ("src/tool.py", 2)])
        res = self.js("archive", "alpha")
        self.assertEqual(res["to"], "docs/rite/cycles/archive/alpha")
        self.assertEqual(sorted((h["path"], h["line"]) for h in res["unrewritten"]),
                         [("docs/index.md", 6), ("docs/notes.md", 3), ("src/tool.py", 2)])
        self.assertIn("# see docs/rite/cycles/alpha/01-harness.md", [h["text"] for h in res["unrewritten"]])
        self.assertEqual(res["bare_rewritten"], [])
        self.assertEqual(self.log(1), ["chore(rite): archive alpha"])
        index = (self.root / "docs/index.md").read_text(encoding="utf-8")
        self.assertIn("[alpha](/docs/rite/cycles/archive/alpha/progress.md)", index)
        self.assertIn("[code](/docs/rite/cycles/alpha/progress.md)", index)  # code blocks untouched
        self.assertFalse((self.root / "docs/rite/cycles/alpha").exists())
        self.assertEqual(self.fx.git("status", "--porcelain"), "")
        self.assertEqual(self.check_errors("--all"), [])
        status = self.js("status", "--all")
        self.assertEqual([c["cycle"] for c in status["cycles"]], ["beta"])


    def test_archive_rewrites_bare_paths_in_own_files_and_with_the_flag_elsewhere(self):
        profiles = self.root / "docs/rite/profiles"
        with (profiles / "alpha.md").open("a", encoding="utf-8", newline="") as fh:
            fh.write("\r\n<!-- retro: /docs/rite/cycles/alpha/retro.md -->\r\n")
        write(profiles / "alpha.pitfalls.md", "# Pitfalls\n\n<!-- new in alpha (docs/rite/cycles/alpha/retro.md) -->\n")
        write(self.root / "docs/rite/cycles/alpha/retro.md",
              "# Retro\n\n```\npython3 -c \"open('docs/rite/cycles/alpha/fixes.json')\"\n```\n")
        write(self.root / "docs/rite/cycles/alpha/01-harness.md",
              (self.root / "docs/rite/cycles/alpha/01-harness.md").read_text() + "\nran in docs/rite/cycles/alpha\n")
        self.fx.work_commit("src/tool.py", "# see docs/rite/cycles/alpha/01-harness.md\n", "feat: tool")
        self.fx.work_commit("docs/notes.md", "docs/rite/cycles/alpha-2 and ./docs/rite/cycles/alpha/\n", "docs: notes")
        self.fx.git("add", "-A")
        self.fx.git("commit", "-q", "-m", "docs: retro")
        finish_cycle(self, "alpha", ["ALP-TASK-01", "ALP-TASK-02", "ALP-TASK-03"])
        preview = self.js("archive", "alpha", "--dry-run")["unrewritten"]
        self.assertEqual(sorted(h["path"] for h in preview), ["docs/notes.md", "src/tool.py"])  # own files: always

        res = self.js("archive", "alpha", "--rewrite-bare")
        new = "docs/rite/cycles/archive/alpha"
        self.assertEqual(sorted(b["path"] for b in res["bare_rewritten"]),
                         ["docs/notes.md", f"{new}/retro.md", "docs/rite/profiles/alpha.md",
                          "docs/rite/profiles/alpha.pitfalls.md", "src/tool.py"])
        self.assertEqual(res["unrewritten"], [])
        self.assertIn(f"\r\n<!-- retro: /{new}/retro.md -->\r\n", (profiles / "alpha.md").read_bytes().decode("utf-8"))
        self.assertIn(f"open('{new}/fixes.json')", (self.root / new / "retro.md").read_text())
        self.assertEqual((self.root / "docs/notes.md").read_text(),
                         f"docs/rite/cycles/alpha-2 and ./{new}/\n")
        self.assertIn("ran in docs/rite/cycles/alpha\n", (self.root / new / "01-harness.md").read_text())  # history
        self.assertEqual(self.log(1), ["chore(rite): archive alpha"])
        self.assertEqual(self.fx.git("status", "--porcelain"), "")


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

    def test_check_resolves_the_links_of_the_plan(self):
        write(self.root / "docs/emu.md", "# Emu\n\n## I. Escritas em `$2007`\n")
        plan = self.root / "docs/plans/PLAN-alpha.md"
        base = plan.read_text(encoding="utf-8")
        write(plan, base + "\n[ok](/docs/emu.md#i-escritas-em-2007)\n")
        self.assertEqual(self.check_errors("--cycle", "alpha"), [])
        write(plan, base + "\n[broken](/docs/emu.md#i-escritas-em)\n")
        errors = self.check_errors("--cycle", "alpha")
        self.assertTrue(any("no heading/anchor '#i-escritas-em' in emu.md" in e for e in errors), errors)
        plan.unlink()
        errors = self.check_errors("--cycle", "alpha")
        self.assertTrue(any("plan '/docs/plans/PLAN-alpha.md' points to a missing file" in e for e in errors),
                        errors)

    def test_stats(self):
        finish_cycle(self, "alpha", ["ALP-TASK-01"])
        self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "a", "--severity", "high")
        s = self.js("stats", "alpha")
        self.assertEqual(s["tasks"]["total"], 3)
        self.assertEqual(s["fixes"]["by_severity"]["high"], 1)
        self.assertEqual({k: s["fixes"][k] for k in ("pending", "done", "stale")},
                         {"pending": 1, "done": 0, "stale": 0})
        self.assertEqual(s["tasks"]["blocked"], 0)
        self.assertEqual(s["fixes_by_origin"], {"ALP-TASK-01": 1})
        self.assertEqual(s["review_latency_days"]["reviewed"], 1)
        self.assertEqual(s["by_phase"]["1"], {"tasks": 2, "fixes": 1})


class PitfallsCarryOverTest(FixtureCase):
    """What a retro kept reaches the next cycle, and a pointer to nothing is reported (#6)."""

    KEPT = "# Pitfalls — alpha\n\n### Literal floor from an f-string\n\nMeasured in ALP-FIX-01.\n"

    def test_new_cycle_starts_from_the_pitfalls_of_another(self):
        write(self.root / "docs/rite/profiles/alpha.pitfalls.md", self.KEPT)
        res = self.js("new-cycle", "gamma", "--prefix", "GAM", "--pitfalls-from", "alpha", "--commit")
        self.assertEqual(res["pitfalls_copied_from"], "docs/rite/profiles/alpha.pitfalls.md")
        # the entries carry over under the new cycle's title, not the old one (#19)
        self.assertEqual((self.root / "docs/rite/profiles/gamma.pitfalls.md").read_text(encoding="utf-8"),
                         self.KEPT.replace("# Pitfalls — alpha", "# Measured pitfalls — gamma"))
        self.assertIn("docs/rite/profiles/gamma.pitfalls.md", res["created"])
        res = self.js("new-cycle", "delta", "--prefix", "DEL", "--pitfalls-from",
                      "docs/rite/profiles/alpha.pitfalls.md")
        self.assertEqual(res["pitfalls_copied_from"], "docs/rite/profiles/alpha.pitfalls.md")
        code, _, err = self.fx.rite("new-cycle", "eps", "--prefix", "EPS", "--pitfalls-from", "nope")
        self.assertEqual(code, 1)
        self.assertIn("--pitfalls-from: nope not found", err)
        self.assertFalse((self.root / "docs/rite/cycles/eps").exists())

    def test_a_source_without_a_title_or_with_one_in_code_gets_the_new_title(self):
        fenced = "```\n# not a title\n```\n\n### Kept\n"
        write(self.root / "docs/rite/profiles/alpha.pitfalls.md", fenced)
        self.js("new-cycle", "gamma", "--prefix", "GAM", "--pitfalls-from", "alpha")
        self.assertEqual((self.root / "docs/rite/profiles/gamma.pitfalls.md").read_text(encoding="utf-8"),
                         "# Measured pitfalls — gamma\n\n" + fenced)

    def test_set_cycle_points_at_a_pitfalls_file(self):
        write(self.root / "docs/rite/shared.pitfalls.md", self.KEPT)
        self.ok("set-cycle", "--cycle", "alpha", "--pitfalls", "docs/rite/shared.pitfalls.md")
        self.assertEqual(self.js("resolve-cycle", "alpha")["pitfalls"], "docs/rite/shared.pitfalls.md")
        self.assertEqual(fields(self.root / "docs/rite/cycles/alpha/progress.md")["pitfalls"],
                         "/docs/rite/shared.pitfalls.md")
        self.assertEqual(self.check_errors("--all"), [])
        code, _, err = self.fx.rite("set-cycle", "--cycle", "alpha", "--pitfalls", "docs/nope.md")
        self.assertEqual(code, 1)
        self.assertIn("pitfalls file docs/nope.md not found", err)
        self.ok("set-cycle", "--cycle", "alpha", "--pitfalls", "")
        self.assertEqual(self.js("resolve-cycle", "alpha")["pitfalls"],
                         "docs/rite/profiles/alpha.pitfalls.md")

    def test_check_warns_about_a_pitfalls_pointer_to_nothing(self):
        set_fields(self.root / "docs/rite/cycles/alpha/progress.md", {"pitfalls": "/docs/rite/profiles/nope.md"})
        _, out, _ = self.fx.rite("check", "--all", "--json")
        self.assertIn("pitfalls file docs/rite/profiles/nope.md not found",
                      " ".join(f["message"] for f in json.loads(out)["findings"] if f["level"] == "warn"))


class AnchorsRelativeTest(FixtureCase):
    layout = "legacy"

    def test_relative_anchor_from_cycle_folder(self):
        data = self.js("anchors", "docs/PLAN-WTE.md", "--cycle", "wte")
        self.assertIn("../../PLAN-WTE.md#2.1", [h["source_of_truth"] for h in data["headings"]])


if __name__ == "__main__":
    unittest.main()
