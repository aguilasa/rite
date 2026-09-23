import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import PROFILE, ROOT, Fixture, rite, task, write

from rite_lib import frontmatter


def fields(path: Path) -> dict:
    return frontmatter.parse(path.read_text(encoding="utf-8"))[0]


class FixtureCase(unittest.TestCase):
    layout = "subfolder"

    def setUp(self):
        self.fx = Fixture(self.layout)
        self.root = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def ok(self, *args) -> str:
        code, out, err = self.fx.rite(*args)
        self.assertEqual(code, 0, f"rite {' '.join(args)} failed: {err}{out}")
        return out

    def js(self, *args) -> dict:
        return json.loads(self.ok(*args, "--json"))

    def check_errors(self, *args) -> list[str]:
        code, out, _ = self.fx.rite("check", "--json", *args)
        data = json.loads(out)
        self.assertEqual(code, 1 if data["errors"] else 0)
        return [f"{f['path']}: {f['message']}" for f in data["findings"] if f["level"] == "error"]

    def log(self, n: int = 20) -> list[str]:
        return self.fx.git("log", f"-{n}", "--format=%s").splitlines()


class LoopTest(FixtureCase):
    """execute -> close -> review (with finding) -> fix -> close, all through the CLI."""

    def test_full_loop(self):
        cyc = self.root / "docs/rite/cycles/alpha"
        self.assertEqual(self.check_errors("--all"), [])

        pick = self.js("next", "task", "--cycle", "alpha")
        self.assertEqual(pick["id"], "ALP-TASK-01")

        self.ok("mark", "ALP-TASK-01", "in-progress")
        self.assertEqual(self.js("next", "task", "--cycle", "alpha")["reason"], "in-progress task resumes first")

        sha = self.fx.work_commit("src/harness.py", "x = 1\n", "feat: harness")
        res = self.js("close", "ALP-TASK-01")
        self.assertEqual(res["done_commit"], sha)
        self.assertEqual(self.log(2), ["chore(rite): close ALP-TASK-01", "feat: harness"])
        f = fields(cyc / "01-harness.md")
        self.assertEqual((f["status"], f["done_commit"], f["reviewed_on"]), ("done", sha, "pending"))
        self.assertEqual(f["done_on"], self.fx.git("show", "-s", "--format=%cs", sha).strip())
        body = (cyc / "01-harness.md").read_text(encoding="utf-8")
        self.assertIn("`A src/harness.py`", body)
        self.assertIn("| done |", (cyc / "progress.md").read_text(encoding="utf-8"))
        self.assertEqual(self.fx.git("status", "--porcelain"), "")

        # closing again, or closing from a bookkeeping commit, is refused
        self.assertEqual(self.fx.rite("close", "ALP-TASK-01")[0], 1)
        self.assertEqual(self.fx.rite("close", "ALP-TASK-02")[0], 1)  # HEAD is chore(rite)

        self.assertEqual(self.js("next", "review", "--cycle", "alpha")["id"], "ALP-TASK-01")
        new = self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "Off by one",
                      "--severity", "high")
        self.assertEqual(new["id"], "FIX-ALP-001")
        self.ok("mark-reviewed", "ALP-TASK-01", "--fixes", "FIX-ALP-001")
        self.assertEqual(self.log(1), ["chore(rite): review ALP-TASK-01 (1 fix: FIX-ALP-001)"])
        self.assertIn("FIX-ALP-001.md", self.fx.git("show", "--name-only", "--format=", "HEAD"))
        self.assertRegex(fields(cyc / "01-harness.md")["reviewed_on"], r"^\d{4}-\d{2}-\d{2}$")

        status = self.js("status", "--cycle", "alpha")["cycles"][0]
        self.assertEqual(status["suggestion"]["command"], "fix")
        self.assertEqual(status["open_fixes"]["high"], 1)

        self.assertEqual(self.js("next", "fix", "--cycle", "alpha")["id"], "FIX-ALP-001")
        self.fx.work_commit("src/harness.py", "x = 2\n", "fix: off by one")
        self.ok("close", "FIX-ALP-001")
        self.assertEqual(fields(cyc / "FIX-ALP-001.md")["status"], "done")

        # a second fix found later goes stale when its symptom is gone
        self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "Flaky", "--severity", "low")
        self.fx.git("add", "-A")
        self.fx.git("commit", "-q", "-m", "chore(rite): open FIX-ALP-002")
        self.assertEqual(self.fx.rite("mark-stale", "FIX-ALP-002", "--reason", " ")[0], 1)
        self.ok("mark-stale", "FIX-ALP-002", "--reason", "10/10 runs green at HEAD")
        self.assertEqual(fields(cyc / "FIX-ALP-002.md")["status"], "stale")

        self.assertEqual(self.check_errors("--all"), [])
        self.assertEqual(self.js("next", "task", "--cycle", "alpha")["id"], "ALP-TASK-02")

    def test_review_without_finding_commits(self):
        self.fx.work_commit("src/a.py", "a\n", "feat: a")
        self.ok("close", "ALP-TASK-01")
        self.ok("mark-reviewed", "ALP-TASK-01")
        self.assertEqual(self.log(1), ["chore(rite): review ALP-TASK-01 (no finding)"])

    def test_close_with_explicit_sha_and_no_commit(self):
        sha = self.fx.work_commit("src/a.py", "a\n", "feat: a")
        self.fx.work_commit("src/b.py", "b\n", "feat: b")
        res = self.js("close", "ALP-TASK-01", "--sha", sha, "--no-commit")
        self.assertEqual(res["done_commit"], sha)
        self.assertIsNone(res["commit"])
        self.assertEqual(self.log(1), ["feat: b"])

    def test_close_without_work_commit(self):
        self.fx.work_commit("src/a.py", "a\n", "feat: unrelated")
        code, _, err = self.fx.rite("close", "ALP-TASK-01", "--no-repo")
        self.assertEqual(code, 1)
        self.assertIn("needs --reason", err)
        code, _, err = self.fx.rite("close", "ALP-TASK-01", "--no-repo", "--sha", "HEAD", "--reason", "x")
        self.assertEqual(code, 1)
        self.assertIn("exclude each other", err)

        res = self.js("close", "ALP-TASK-01", "--no-repo", "--reason", "edited docs/notes.md outside git")
        self.assertEqual((res["done_commit"], res["work_subject"]), ("none", None))
        path = self.root / "docs/rite/cycles/alpha/01-harness.md"
        f = fields(path)
        self.assertEqual((f["status"], f["done_commit"], f["reviewed_on"]), ("done", "none", "pending"))
        self.assertIn("no work commit", path.read_text(encoding="utf-8"))
        self.assertEqual(self.log(1), ["chore(rite): close ALP-TASK-01"])
        self.assertEqual(self.check_errors("--all"), [])
        self.assertEqual(self.check_errors("--all", "--quick"), [])

        # a work commit found later can still be attached
        sha = self.fx.work_commit("src/b.py", "b\n", "feat: late work")
        self.assertEqual(self.js("rebind", "ALP-TASK-01", "--sha", sha)["done_commit"], sha)

    def test_order_overrides_id_order(self):
        # a task split late (04) must run before 02 and 03, without renumbering them
        write(self.root / "docs/rite/cycles/alpha/04-split.md",
              task("ALP-TASK-04", "Split", sot="/docs/plans/PLAN-alpha.md#1"))
        progress = self.root / "docs/rite/cycles/alpha/progress.md"
        progress.write_text(frontmatter.set_fields(progress.read_text(encoding="utf-8"),
                            {"order": ["ALP-TASK-01", "ALP-TASK-04", "ALP-TASK-02", "ALP-TASK-03"]}),
                            encoding="utf-8")
        self.ok("sync", "--all")
        table = progress.read_text(encoding="utf-8")
        self.assertLess(table.index("[ALP-TASK-04]"), table.index("[ALP-TASK-02]"))
        self.fx.work_commit("src/a.py", "a\n", "feat: a")
        self.ok("close", "ALP-TASK-01")
        self.assertEqual(self.js("next", "task", "--cycle", "alpha")["id"], "ALP-TASK-04")
        self.assertEqual([i["id"] for i in self.js("batch-plan", "2", "--cycle", "alpha")["items"]],
                         ["ALP-TASK-04", "ALP-TASK-02"])
        self.assertEqual(self.check_errors("--all"), [])

    def test_order_with_an_unknown_id_is_red(self):
        progress = self.root / "docs/rite/cycles/alpha/progress.md"
        progress.write_text(frontmatter.set_fields(progress.read_text(encoding="utf-8"),
                            {"order": ["ALP-TASK-02", "ALP-TASK-09", "ALP-TASK-02"]}), encoding="utf-8")
        errors = self.check_errors("--all")
        self.assertTrue(any("ALP-TASK-09, which is not a task" in e for e in errors), errors)
        self.assertTrue(any("lists ALP-TASK-02 twice" in e for e in errors), errors)

    def test_blocked_selection(self):
        self.ok("mark", "ALP-TASK-01", "blocked", "--reason", "waiting on hardware")
        pick = json.loads(self.fx.rite("next", "task", "--cycle", "alpha", "--json")[1])
        self.assertIsNone(pick["id"])
        self.assertEqual(pick["blocked_by"], {"ALP-TASK-02": ["ALP-TASK-01"], "ALP-TASK-03": ["ALP-TASK-02"]})

    def test_new_task_allocates_next_id(self):
        res = self.js("new-task", "--cycle", "alpha", "--title", "Extra report", "--type", "tool", "--phase", "2",
                      "--depends-on", "ALP-TASK-01", "--source-of-truth", "/docs/plans/PLAN-alpha.md#2.2")
        self.assertEqual(res["id"], "ALP-TASK-04")
        self.assertTrue(res["path"].endswith("04-extra-report.md"))
        # a stale file squatting on the next number must not be overwritten
        write(self.root / "docs/rite/cycles/alpha/05-squat.md", "squatter\n")
        res2 = self.js("new-task", "--cycle", "alpha", "--title", "Squat", "--type", "tool", "--phase", "2",
                       "--source-of-truth", "/docs/plans/PLAN-alpha.md#2.2", "--slug", "squat")
        self.assertEqual(res2["id"], "ALP-TASK-06")
        self.assertEqual((self.root / "docs/rite/cycles/alpha/05-squat.md").read_text(), "squatter\n")

    def test_fix_ids_are_per_prefix_across_archive(self):
        arch = self.root / "docs/rite/cycles/archive/old"
        write(arch / "progress.md", "---\ncycle: old\nprefix: ALP\n---\n")
        write(arch / "FIX-ALP-007.md", "---\nid: FIX-ALP-007\n---\n")
        res = self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "t", "--severity", "low")
        self.assertEqual(res["id"], "FIX-ALP-008")

    def test_sync_is_idempotent(self):
        progress = self.root / "docs/rite/cycles/alpha/progress.md"
        before = progress.read_bytes()
        self.ok("sync", "--all")
        self.ok("sync", "--all")
        self.assertEqual(progress.read_bytes(), before)
        self.assertIn("Plan: [PLAN-alpha]", progress.read_text(encoding="utf-8"))

    def test_resolve_cycle(self):
        code, _, err = self.fx.rite("resolve-cycle")
        self.assertEqual(code, 1)
        self.assertIn("several live cycles", err)
        data = self.js("resolve-cycle", "beta")
        self.assertEqual((data["prefix"], data["profile"]), ("BET", "docs/rite/profiles/beta.md"))

    def test_guard(self):
        self.assertEqual(self.fx.rite("guard", "vendor/x.js")[0], 1)
        code, out, _ = self.fx.rite("guard", "src/gen/a.py")
        self.assertEqual(code, 1)
        self.assertIn("tools/gen.py", out)
        self.assertEqual(self.fx.rite("guard", "src/app.py")[0], 0)


class CheckRedTest(FixtureCase):
    """Planted defects must turn `check` red."""

    def cyc(self, name: str = "alpha") -> Path:
        return self.root / "docs/rite/cycles" / name

    def assert_red(self, needle: str) -> None:
        errors = self.check_errors("--all")
        self.assertTrue(any(needle in e for e in errors), f"{needle!r} not in {errors}")

    def test_relative_link_in_root_absolute_repo(self):
        p = self.cyc() / "progress.md"
        p.write_text(p.read_text(encoding="utf-8") + "\n[plan](../../../plans/PLAN-alpha.md)\n", encoding="utf-8")
        self.assert_red("must be root-absolute")

    def test_missing_anchor(self):
        write(self.cyc() / "04-x.md", task("ALP-TASK-04", "X", sot="/docs/plans/PLAN-alpha.md#9.9"))
        self.ok("sync", "--all")
        self.assert_red("no heading/anchor '#9.9'")

    def test_depends_on_crosses_cycle(self):
        write(self.cyc() / "04-x.md", task("ALP-TASK-04", "X", depends_on="[BET-TASK-01]",
                                           sot="/docs/plans/PLAN-alpha.md#1"))
        self.ok("sync", "--all")
        self.assert_red("crosses into cycle beta")

    def test_view_out_of_sync(self):
        p = self.cyc() / "01-harness.md"
        p.write_text(frontmatter.set_fields(p.read_text(encoding="utf-8"), {"title": "Renamed"}), encoding="utf-8")
        self.assert_red("out of sync")

    def test_duplicate_id(self):
        write(self.cyc() / "04-dup.md", task("ALP-TASK-01", "Dup", sot="/docs/plans/PLAN-alpha.md#1"))
        self.ok("sync", "--all")
        self.assert_red("duplicate ID ALP-TASK-01")

    def test_done_by_hand(self):
        p = self.cyc() / "01-harness.md"
        p.write_text(frontmatter.set_fields(p.read_text(encoding="utf-8"), {"status": "done"}), encoding="utf-8")
        self.ok("sync", "--all")
        self.assert_red("done without done_commit")

    def test_unknown_commit(self):
        p = self.cyc() / "01-harness.md"
        p.write_text(frontmatter.set_fields(p.read_text(encoding="utf-8"), {
            "status": "done", "done_on": "2026-01-01", "done_commit": "deadbee", "reviewed_on": "pending"}),
            encoding="utf-8")
        self.ok("sync", "--all")
        self.assert_red("is not a commit")

    def test_bad_vocabulary(self):
        p = self.cyc() / "01-harness.md"
        p.write_text(frontmatter.set_fields(p.read_text(encoding="utf-8"), {"status": "finished"}), encoding="utf-8")
        self.ok("sync", "--all")
        self.assert_red("status 'finished' not in")

    def test_phase_without_profile_entry(self):
        write(self.cyc() / "04-x.md", task("ALP-TASK-04", "X", phase=7, sot="/docs/plans/PLAN-alpha.md#1"))
        self.ok("sync", "--all")
        self.assert_red("no entry for phase 7")

    def test_a_phase_range_covers_every_phase_in_it(self):
        # one entry often serves phases that share their checks ("Phase 6-7")
        prof = self.root / "docs/rite/profiles/alpha.md"
        prof.write_text(prof.read_text(encoding="utf-8") + "\n### Phase 6-8 — late\n- same checks\n",
                        encoding="utf-8")
        write(self.cyc() / "04-x.md", task("ALP-TASK-04", "X", phase=7, sot="/docs/plans/PLAN-alpha.md#1"))
        write(self.cyc() / "05-y.md", task("ALP-TASK-05", "Y", phase=9, sot="/docs/plans/PLAN-alpha.md#1"))
        self.ok("sync", "--all")
        errors = self.check_errors("--all")
        self.assertFalse([e for e in errors if "phase 7" in e], errors)
        self.assertTrue([e for e in errors if "phase 9" in e], errors)

    def test_profile_over_limit(self):
        p = self.root / "docs/rite/profiles/alpha.md"
        p.write_text(p.read_text(encoding="utf-8") + "\n" + ("pitfall line\n" * 1200), encoding="utf-8")
        self.assert_red("> [profile].max_kb")

    def test_dependency_cycle(self):
        p = self.cyc() / "01-harness.md"
        p.write_text(frontmatter.set_fields(p.read_text(encoding="utf-8"), {"depends_on": ["ALP-TASK-03"]}),
                     encoding="utf-8")
        self.ok("sync", "--all")
        self.assert_red("dependency cycle")


class FlatLayoutTest(FixtureCase):
    layout = "flat"

    def test_flat_cycle_resolves_without_argument(self):
        self.assertEqual(self.js("resolve-cycle")["path"], "docs/tasks")
        self.fx.work_commit("a.txt", "a\n", "feat: first")
        self.ok("close", "FLT-TASK-01")
        self.assertEqual(self.js("next", "task")["id"], "FLT-TASK-02")
        self.assertEqual(self.check_errors(), [])


class LegacyLayoutTest(FixtureCase):
    layout = "legacy"

    def test_legacy_names_and_relative_links(self):
        self.assertEqual(self.check_errors(), [])
        self.fx.work_commit("tools/extract.py", "x\n", "feat: extrair tabelas")
        self.ok("close", "WTE-TASK-01")
        cyc = self.root / "docs/tasks/wte"
        body = (cyc / "01-extrair-tabelas.md").read_text(encoding="utf-8")
        self.assertIn("## Log de Execução", body)
        res = self.js("new-fix", "--origin", "WTE-TASK-01", "--title", "Tabela truncada", "--severity", "critical")
        self.assertEqual(res["id"], "CORR-WTE-001")
        text = (cyc / "CORR-WTE-001.md").read_text(encoding="utf-8")
        self.assertIn("Origin: [WTE-TASK-01](01-extrair-tabelas.md)", text)
        self.assertIn("## Log de Execução", text)
        self.assertIn("(CORR-WTE-001.md)", (cyc / "correcoes-progresso.md").read_text(encoding="utf-8"))
        self.ok("mark-reviewed", "WTE-TASK-01", "--fixes", "CORR-WTE-001")
        self.assertEqual(self.check_errors(), [])
        code, out, _ = self.fx.rite("guard", "roms/original.bin")
        self.assertEqual(code, 1)
        self.assertIn("ROMs originais", out)


class BatchPlanTest(FixtureCase):
    def add(self, n: int, *, files: str, resources: str = "[]", deps: str = "[]", type_: str = "feature") -> str:
        item_id = f"BET-TASK-{n:02}"
        write(self.root / f"docs/rite/cycles/beta/{n:02}-t{n}.md",
              task(item_id, f"T{n}", depends_on=deps, type_=type_, sot="/docs/plans/PLAN-alpha.md#1",
                   extra=f"files: {files}\nresources: {resources}\n"))
        return item_id

    def setUp(self):
        super().setUp()
        cfg = self.root / "rite.toml"
        cfg.write_text(cfg.read_text(encoding="utf-8")
                       + '\n[resources]\nserialized = [{ name = "display", why = "one screen" }]\n', encoding="utf-8")
        self.fx.git("rm", "-q", "docs/rite/cycles/beta/01-other.md")

    def plan(self, *targets: str, kind: str = "task") -> dict:
        return self.js("batch-plan", *targets, "--kind", kind, "--cycle", "beta")

    def test_serialized_resource_splits_waves(self):
        a = self.add(1, files="[src/a.py]", resources="[display]")
        b = self.add(2, files="[src/b.py]", resources="[display]")
        c = self.add(3, files="[src/c.py]")
        data = self.plan("3")
        self.assertEqual(data["waves"], [[a, c], [b]])
        self.assertEqual(data["items"][0]["conflicts"], {b: ["resources: display"]})

    def test_file_overlap_dependency_and_closing(self):
        a = self.add(1, files="[src/lib/**]")
        b = self.add(2, files="[src/lib/x.py]")
        c = self.add(3, files="[docs/c.md]", deps="[BET-TASK-01]")
        d = self.add(4, files="[docs/d.md]", type_="closing")
        e = self.add(5, files="[docs/e.md]")
        data = self.plan(e, d, c, b, a)
        self.assertEqual(data["waves"], [[a, e], [b, c], [d]])
        conflicts = {i["id"]: i["conflicts"] for i in data["items"]}
        self.assertIn("files: src/lib/**", conflicts[a][b])
        self.assertIn("depends_on", conflicts[a][c])

    def test_default_two_and_unknown_files_run_alone(self):
        self.add(1, files="[]")
        self.add(2, files="[src/b.py]")
        self.add(3, files="[src/c.py]")
        data = self.plan()
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["waves"], [["BET-TASK-01"], ["BET-TASK-02"]])
        self.assertTrue(any("no predicted files" in w for w in data["warnings"]))

    def test_all_is_for_fixes_only(self):
        self.add(1, files="[src/a.py]")
        self.assertEqual(self.fx.rite("batch-plan", "all", "--cycle", "beta")[0], 1)
        for title in ("one", "two", "three"):
            self.js("new-fix", "--cycle", "beta", "--origin", "BET-TASK-01", "--title", title, "--severity", "low")
        self.assertEqual(len(self.plan("all", kind="fix")["items"]), 3)


class HookTest(FixtureCase):
    def hook(self, script: str, event: dict) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ROOT / "hooks" / script)], input=json.dumps(event),
                              capture_output=True, text=True, encoding="utf-8")

    def test_guard_blocks_read_only_and_generated(self):
        ev = {"cwd": str(self.root), "tool_name": "Write", "tool_input": {"file_path": "vendor/lib.js"}}
        res = self.hook("guard.py", ev)
        self.assertEqual(res.returncode, 2)
        self.assertIn("read-only", res.stderr)
        ev["tool_input"] = {"file_path": str(self.root / "src/gen/out.py")}
        res = self.hook("guard.py", ev)
        self.assertEqual(res.returncode, 2)
        self.assertIn("tools/gen.py", res.stderr)
        ev["tool_input"] = {"file_path": str(self.root / "src/app.py")}
        self.assertEqual(self.hook("guard.py", ev).returncode, 0)

    def test_guard_is_inert_without_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = {"cwd": tmp, "tool_name": "Write", "tool_input": {"file_path": "vendor/x"}}
            self.assertEqual(self.hook("guard.py", ev).returncode, 0)

    def test_stop_check_warns_only_when_enabled(self):
        p = self.root / "docs/rite/cycles/alpha/01-harness.md"
        p.write_text(frontmatter.set_fields(p.read_text(encoding="utf-8"), {"title": "Drift"}), encoding="utf-8")
        ev = {"cwd": str(self.root)}
        self.assertEqual(self.hook("stop_check.py", ev).stdout, "")
        cfg = self.root / "rite.toml"
        cfg.write_text(cfg.read_text(encoding="utf-8") + "\n[hooks]\nstop_check = true\n", encoding="utf-8")
        res = self.hook("stop_check.py", ev)
        self.assertEqual(res.returncode, 0)
        self.assertIn("out of sync", json.loads(res.stdout)["systemMessage"])

    def test_commit_new(self):
        res = self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "T", "--severity", "low")
        self.ok("commit-new", res["id"])
        self.assertEqual(self.log(1), [f"chore(rite): open {res['id']}"])
        self.assertEqual(self.fx.git("status", "--porcelain"), "")


class ComposeTest(FixtureCase):
    """begin / gates / sweep / finish: one call where the rite used to spend several turns."""

    def test_begin_takes_the_item_and_answers_the_first_turn(self):
        data = self.js("begin", "task", "--cycle", "alpha")
        self.assertEqual(data["item"]["id"], "ALP-TASK-01")
        self.assertEqual(data["item"]["status"], "in-progress")
        self.assertTrue(data["taken"])
        self.assertEqual(data["item"]["source_of_truth"], "/docs/plans/PLAN-alpha.md#2.1")
        self.assertEqual(data["paths"]["profile"], "docs/rite/profiles/alpha.md")
        self.assertEqual(data["commit"]["trailers"], ["Refs: ALP-TASK-01"])
        self.assertEqual(data["config"]["read_only"], ["vendor/**"])
        self.assertTrue(data["config"]["generated"][0]["generator"])
        self.assertIsInstance(data["repo_kb"], int)

        again = self.js("begin", "task", "--cycle", "alpha")  # idempotent
        self.assertEqual(again["item"]["id"], "ALP-TASK-01")
        self.assertFalse(again["taken"])
        self.assertEqual(self.fx.git("status", "--porcelain").count("01-harness"), 1)

    def test_begin_named_item_and_refusals(self):
        data = self.js("begin", "task", "--cycle", "alpha", "--id", "ALP-TASK-01")
        self.assertEqual(data["reason"], "named explicitly")
        code, _, err = self.fx.rite("begin", "task", "--cycle", "alpha", "--id", "ALP-TASK-02")
        self.assertEqual(code, 1)
        self.assertIn("waits for ALP-TASK-01", err)
        code, _, err = self.fx.rite("begin", "fix", "--cycle", "alpha", "--id", "ALP-TASK-01")
        self.assertEqual(code, 1)
        self.assertIn("is a task", err)
        code, out, _ = self.fx.rite("begin", "review", "--cycle", "alpha", "--json")
        self.assertEqual(code, 1)  # nothing to review yet
        self.assertIsNone(json.loads(out)["item"])

    def test_gates_pass_fail_and_truncation(self):
        gates_section = '## Gates\n\n- `python -c "print(7)"`\n\n## Confirmed decisions'
        write(self.root / "docs/rite/profiles/alpha.md",
              PROFILE.format(cycle="alpha").replace("## Confirmed decisions", gates_section))
        data = self.js("gates", "--cycle", "alpha")
        self.assertTrue(data["passed"])
        self.assertEqual(data["gates"][0]["command"], 'python -c "print(7)"')
        self.assertIn("7", data["gates"][0]["output"])

        cfg = self.root / "rite.toml"
        red = '\n[gates]\nglobal = ["python -c \\"import sys; sys.exit(\'boom\')\\""]\n'
        cfg.write_text(cfg.read_text(encoding="utf-8") + red, encoding="utf-8", newline="\n")
        code, out, _ = self.fx.rite("gates", "--cycle", "alpha", "--json")
        self.assertEqual(code, 1)
        failing = json.loads(out)["gates"][0]
        self.assertFalse(failing["passed"])
        self.assertIn("boom", failing["output"])  # a red gate keeps its whole output

    def test_sweep_finds_mentions_outside_the_item(self):
        write(self.root / "docs/rite/cycles/alpha/03-close-phase.md",
              (self.root / "docs/rite/cycles/alpha/03-close-phase.md").read_text(encoding="utf-8")
              + "\nMentions card_diff() here.\n")
        data = self.js("sweep", "--terms", "card_diff,absent_term", "--cycle", "alpha",
                       "--id", "ALP-TASK-01")
        hits = data["results"]["card_diff"]["hits"]
        self.assertTrue(any(h["file"].endswith("03-close-phase.md") for h in hits), hits)
        self.assertEqual(data["results"]["absent_term"]["hits"], [])

    def test_finish_closes_checks_and_names_the_next_item(self):
        self.js("begin", "task", "--cycle", "alpha")
        self.fx.work_commit("src/a.py", "a\n", "feat: harness")
        data = self.js("finish", "ALP-TASK-01", "--cycle", "alpha")
        self.assertEqual(data["closed"]["done_commit"], self.fx.git("rev-parse", "--short", "HEAD~1").strip())
        self.assertEqual(data["check"]["errors"], [])
        self.assertEqual((data["next"]["kind"], data["next"]["id"]), ("review", "ALP-TASK-01"))
        self.assertEqual(self.log(1), ["chore(rite): close ALP-TASK-01"])


class NoConfigTest(unittest.TestCase):
    def test_exit_code_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = rite(Path(tmp), "status")
        self.assertEqual(code, 3)
        self.assertIn("no rite.toml", err)

    def test_bad_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp) / "rite.toml", "[paths]\nlink_style = \"weird\"\n[bogus]\n")
            code, _, err = rite(Path(tmp), "status")
        self.assertEqual(code, 1)
        self.assertIn("link_style", err)
        self.assertIn("unknown section [bogus]", err)


if __name__ == "__main__":
    unittest.main()
