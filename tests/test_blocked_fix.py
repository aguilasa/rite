"""A blocked fix waits on the environment, which Rite does not know: it names the command that
unblocks it, and Rite runs that command to re-evaluate the block."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import git, rite, write
from test_cli import FixtureCase, fields
from test_migrate import FIXES, PLAN, PROGRESS, legacy_fix, legacy_task
from test_reproduce import fix_body

from rite_lib import frontmatter

PY = f'"{sys.executable}"'
PASSES = f"{PY} -c \"print('emulator up')\""
FAILS = f"{PY} -c \"import sys; print('no emulator'); sys.exit(3)\""


class BlockedFixTest(FixtureCase):
    def setUp(self):
        super().setUp()
        self.fix = self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "Needs emulator",
                           "--severity", "high")["id"]
        self.other = self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "Plain",
                             "--severity", "low")["id"]
        self.path = self.root / "docs/rite/cycles/alpha" / f"{self.fix}.md"

    def block(self, command: str = FAILS) -> dict:
        return self.js("mark", self.fix, "blocked", "--reason", "slot-1 lines need the tool; partial work in abc1234",
                       "--unblocked-by", command)

    def test_blocked_without_unblocked_by_is_refused(self):
        code, out, err = self.fx.rite("mark", self.fix, "blocked", "--reason", "needs the emulator")
        self.assertNotEqual(code, 0)
        self.assertIn("--unblocked-by", err + out)
        self.assertIn("lost item", err + out)
        self.assertEqual(fields(self.path)["status"], "pending")

    def test_unblocked_by_applies_only_to_a_blocked_fix(self):
        for args in (("ALP-TASK-01", "blocked"), (self.fix, "in-progress")):
            code, out, err = self.fx.rite("mark", *args, "--reason", "x", "--unblocked-by", "true")
            self.assertNotEqual(code, 0, out)
            self.assertIn("applies to a fix marked blocked", err + out)

    def test_blocked_records_status_command_and_log(self):
        res = self.block()
        self.assertEqual(res["status"], "blocked")
        f = fields(self.path)
        self.assertEqual((f["status"], f["unblocked_by"]), ("blocked", FAILS))
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("partial work in abc1234", text)
        self.assertIn(f"unblocked by `{FAILS}`", text)
        self.assertEqual(self.check_errors("--all"), [])

    def test_next_fix_skips_it_and_names_the_command(self):
        self.block()
        pick = self.js("next", "fix", "--cycle", "alpha")
        self.assertEqual(pick["id"], self.other)
        self.assertEqual(pick["unblocked_by"], {self.fix: FAILS})
        out = self.ok("next", "fix", "--cycle", "alpha")
        self.assertIn(f"{self.fix} until `{FAILS}` passes", out)
        self.ok("mark", self.other, "blocked", "--reason", "same", "--unblocked-by", PASSES)
        code, out, _ = self.fx.rite("next", "fix", "--cycle", "alpha", "--json")
        pick = json.loads(out)
        self.assertEqual((code, pick["id"]), (1, None))
        self.assertIn("status=blocked", pick["reason"])
        self.assertIn(FAILS, pick["reason"])

    def test_reproduce_all_runs_the_unblock_command_not_the_evidence(self):
        self.block()
        code, out, err = self.fx.rite("reproduce", "--all", "--cycle", "alpha", "--json")
        self.assertEqual(code, 0, err)
        by_id = {f["id"]: f for f in json.loads(out)["fixes"]}
        self.assertEqual(set(by_id), {self.fix, self.other})
        blocked = by_id[self.fix]
        self.assertEqual((blocked["blocked"], blocked["unblocked_by"], blocked["runnable"], blocked["why"]),
                         (True, FAILS, False, "blocked"))
        self.assertEqual(blocked["commands"], [])
        self.assertEqual(blocked["unblock"]["exit_code"], 3)
        self.assertIn("no emulator", blocked["unblock"]["output"])
        self.assertFalse(by_id[self.other]["blocked"])
        text = self.ok("reproduce", "--all", "--cycle", "alpha")
        self.assertIn(f"blocked; unblocked by `{FAILS}` -> exit 3", text)

    def test_check_errors_without_unblocked_by_and_warns_on_unversioned_script(self):
        self.block()
        self.path.write_text(frontmatter.set_fields(self.path.read_text(encoding="utf-8"), {"unblocked_by": None}),
                             encoding="utf-8")
        self.assertEqual(fields(self.path)["unblocked_by"], None)
        errors = self.check_errors("--all")
        self.assertTrue(any("blocked without unblocked_by" in e for e in errors), errors)

        self.ok("mark", self.fix, "blocked", "--reason", "x", "--unblocked-by", "python tools/nope.py --flag")
        code, out, _ = self.fx.rite("check", "--json", "--all")
        warns = [f["message"] for f in json.loads(out)["findings"] if f["level"] == "warn"]
        self.assertTrue(any("unblocked_by" in w and "tools/nope.py" in w for w in warns), warns)

    def test_a_passing_unblock_command_returns_the_fix_to_the_queue(self):
        self.block(PASSES)
        run = self.js("reproduce", self.fix, "--cycle", "alpha")["fixes"][0]
        self.assertEqual(run["unblock"]["exit_code"], 0)
        # what /rite:fix-all does on green
        self.ok("mark", self.fix, "pending", "--reason", f"{PASSES} now passes")
        f = fields(self.path)
        self.assertEqual((f["status"], f["unblocked_by"]), ("pending", None))
        self.assertIn(f"**pending** ", self.path.read_text(encoding="utf-8"))
        self.assertIn("now passes", self.path.read_text(encoding="utf-8"))
        self.assertEqual(self.js("next", "fix", "--cycle", "alpha")["id"], self.fix)
        self.assertEqual(self.check_errors("--all"), [])

    def test_views_status_and_archive_know_the_state(self):
        self.block()
        table = (self.root / "docs/rite/cycles/alpha/fixes.md").read_text(encoding="utf-8")
        self.assertRegex(table, rf"\[{self.fix}\].*\| blocked \|")
        self.assertEqual(self.check_errors("--all"), [])
        cyc = self.js("status", "--cycle", "alpha")["cycles"][0]
        self.assertEqual(cyc["blocked_fixes"], {self.fix: FAILS})
        code, out, _ = self.fx.rite("archive", "alpha", "--dry-run", "--json")
        self.assertEqual(code, 1)
        self.assertTrue(any(b.startswith(f"{self.fix} is blocked") for b in json.loads(out)["blockers"]), out)


class BlockedFixIsOpenTest(FixtureCase):
    """Open is pending, in-progress or blocked; closed is done or stale. A blocked fix is still debt:
    `check` verifies it and `status` counts it — only the pickers leave it out."""

    def new_fix(self, severity: str) -> str:
        return self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "t",
                       "--severity", severity)["id"]

    def block(self, fix_id: str) -> None:
        self.ok("mark", fix_id, "blocked", "--reason", "needs the live oracle", "--unblocked-by", FAILS)

    def run_py_warnings(self) -> list[str]:
        code, out, err = self.fx.rite("check", "--cycle", "alpha", "--json")
        return [f"{f['path']}: {f['message']}" for f in json.loads(out)["findings"]
                if f["level"] == "warn" and "run.py" in f["message"]]

    def test_check_verifies_the_evidence_of_a_blocked_fix_not_of_a_closed_one(self):
        fix_id = self.new_fix("low")
        path = self.root / "docs/rite/cycles/alpha" / f"{fix_id}.md"
        body = fix_body("```text\n$ python run.py\n316 of 520\n```").replace("{id}", fix_id)
        path.write_text(body.replace("{resources}", "[]"), encoding="utf-8")
        self.assertEqual(len(self.run_py_warnings()), 1)
        self.block(fix_id)
        warnings = self.run_py_warnings()
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn(fix_id, warnings[0])
        for closed in ("done", "stale"):
            text = frontmatter.set_fields(path.read_text(encoding="utf-8"),
                                          {"status": closed, "unblocked_by": None})
            path.write_text(text, encoding="utf-8")
            self.assertEqual(self.run_py_warnings(), [], closed)

    def test_status_counts_blocked_fixes_by_severity_and_apart(self):
        fixes = [self.new_fix(s) for s in ("high", "medium", "low")]
        for fix_id in fixes:
            self.block(fix_id)
        cyc = self.js("status", "--cycle", "alpha")["cycles"][0]
        self.assertEqual(cyc["open_fixes"], {"critical": 0, "high": 1, "medium": 1, "low": 1})
        self.assertEqual(cyc["open_fixes_blocked"], 3)
        self.assertEqual(list(cyc["blocked_fixes"]), fixes)
        self.assertNotEqual(cyc["suggestion"]["command"], "fix")  # a blocked high is nothing to pick
        self.assertIsNone(cyc["next_fix"]["id"])
        text = self.ok("status", "--cycle", "alpha")
        self.assertIn("high 1, medium 1, low 1; blocked: 3 — ", text)
        self.assertIn(f"{fixes[0]} until `{FAILS}` passes", text)

    def test_the_pickers_leave_blocked_fixes_out(self):
        high, low = self.new_fix("high"), self.new_fix("low")
        self.block(high)
        pick = self.js("next", "fix", "--cycle", "alpha")
        self.assertEqual((pick["id"], pick["unblocked_by"]), (low, {high: FAILS}))
        for targets in (("all",), ("5",)):
            items = self.js("batch-plan", *targets, "--kind", "fix", "--cycle", "alpha")["items"]
            self.assertEqual([i["id"] for i in items], [low], targets)
        self.block(low)
        code, out, _ = self.fx.rite("next", "fix", "--cycle", "alpha", "--json")
        self.assertEqual((code, json.loads(out)["id"]), (1, None))

    def test_a_blocked_fix_neither_goes_stale_nor_lets_the_cycle_archive(self):
        fix_id = self.new_fix("medium")
        self.block(fix_id)
        code, out, err = self.fx.rite("mark-stale", fix_id, "--reason", "gone")
        self.assertNotEqual(code, 0)
        self.assertIn("mark it pending", err + out)
        code, out, _ = self.fx.rite("archive", "alpha", "--dry-run", "--json")
        self.assertEqual(code, 1)
        self.assertTrue(any(b.startswith(f"{fix_id} is blocked") for b in json.loads(out)["blockers"]), out)


class MigrateBlockedFixTest(unittest.TestCase):
    """A legacy fix marked blocked has no command to carry: migrate does not invent one."""

    def test_a_legacy_blocked_fix_migrates_to_pending_with_a_warning(self):
        with tempfile.TemporaryDirectory(prefix="rite-migrate-") as tmp:
            r = Path(tmp).resolve()
            git(r, "init", "-q")
            git(r, "config", "user.name", "T")
            git(r, "config", "user.email", "t@example.invalid")
            git(r, "config", "core.autocrlf", "false")
            write(r / "docs/PLAN-LEG.md", PLAN)
            write(r / "docs/prompts/perfil-leg.md", "# Perfil\n\n## Gates deste ciclo\n\n- `echo ok`\n\n"
                                                    "## Verificações específicas por fase\n\n**Fase 1:** medir\n")
            t = r / "docs/tasks"
            write(t / "progresso.md", PROGRESS)
            write(t / "correcoes-progresso.md", FIXES.replace("[ ] pendente", "❌ bloqueada"))
            write(t / "01-primeira.md", legacy_task("LEG-TASK-01", "Primeira", "/docs/PLAN-LEG.md §4.2", "concluído"))
            write(t / "02-segunda.md", legacy_task("LEG-TASK-02", "Segunda", "/docs/PLAN-LEG.md §1", "concluído",
                                                   deps='["LEG-TASK-01"]'))
            write(t / "03-fechamento.md", legacy_task("LEG-TASK-03", "Fechamento", "/docs/PLAN-LEG.md §1",
                                                      "pendente", type_="fechamento", deps='["LEG-TASK-02"]'))
            write(t / "PAR-TASK-01.md", legacy_task("PAR-TASK-01", "Paridade", "/docs/PLAN-LEG.md §1", "concluído",
                                                     phase=""))
            for n, status in ((1, "concluída"), (2, "bloqueada"), (3, "concluída")):
                write(t / f"CORR-LEG-00{n}.md", legacy_fix(f"CORR-LEG-00{n}", status))
            git(r, "add", "-A")
            git(r, "commit", "-q", "-m", "chore: legacy")
            code, out, err = rite(r, "migrate", "--from", "we2002", "--write", "--json")
            self.assertEqual(code, 0, err)
            report = json.loads(out)
            self.assertTrue(any("CORR-LEG-002" in w and "unblocked-by" in w for w in report["warnings"]),
                            report["warnings"])
            c2 = frontmatter.parse((t / "CORR-LEG-002.md").read_text(encoding="utf-8"))[0]
            self.assertEqual(c2["status"], "pending")
            code, out, _ = rite(r, "check", "--json")
            self.assertEqual(json.loads(out)["errors"], 0, out)


if __name__ == "__main__":
    unittest.main()
