"""`rite.py migrate --from we2002` on a miniature legacy repository."""

import json
import tempfile
import unittest
from pathlib import Path

from fixtures import git, rite, write

from rite_lib import frontmatter

PLAN = "# Plano\n\n## 1. Contexto\n\n## 4. Harness\n\n### 4.2 Cartão\n"

PROGRESS = """\
# Progresso — legado

**Perfil deste ciclo:** [`/docs/prompts/perfil-leg.md`](/docs/prompts/perfil-leg.md).

## Resumo

| ID | Tarefa | Fase | Dependências | Status | Concluída em | Revisado em |
| -- | ------ | ---- | ------------ | ------ | ------------ | ----------- |
| [LEG-TASK-01](/docs/tasks/01-primeira.md) | Primeira | 1 | — | ✅ Concluído | 2026-01-02 | 2026-01-03 |
| [LEG-TASK-02](/docs/tasks/02-segunda.md) | Segunda | 1 | 01 | ✅ Concluído | 2026-01-04 | ⬜ pendente |
| [LEG-TASK-03](/docs/tasks/03-fechamento.md) | Fechamento | 1 | 02 | ⬜ Pendente | — | — |

Notas humanas ficam.

# Anexo — paridade

## Resumo

| ID | Tarefa | §  | Itens | Dependências | Status | Concluída em | Revisado em |
| -- | ------ | -- | ----- | ------------ | ------ | ------------ | ----------- |
| [PAR-TASK-01](/docs/tasks/PAR-TASK-01.md) | Paridade | 8.1 | 5 | — | ✅ Concluído | 2026-01-05 | 2026-01-06 |
"""

FIXES = """\
# Correções

| ID | ID Task Origem | Título | Criticidade | Status | Concluída em |
|---|---|---|---|---|---|
| [CORR-LEG-001](/docs/tasks/CORR-LEG-001.md) | [LEG-TASK-01](/docs/tasks/01-primeira.md) | Um erro | Alta | [x] concluída | 2026-01-03 |
| [CORR-LEG-002](/docs/tasks/CORR-LEG-002.md) | [LEG-TASK-02](/docs/tasks/02-segunda.md) | Outro | Baixa | [ ] pendente | — |
| [CORR-LEG-003](/docs/tasks/CORR-LEG-003.md) | [LEG-TASK-01](/docs/tasks/01-primeira.md) | O ramo `cor|grade` morto | Média | [x] concluída | 2026-01-07 |
"""


def legacy_task(item_id, title, sot, status, type_="implementação", deps="[]", phase="phase: 1\n"):
    return (f"---\nid: {item_id}\ntitle: \"{title}\"\ntype: {type_}\ncategory: x\n{phase}"
            f"depends_on: {deps}\nfonte_de_verdade: \"{sot}\"\nstatus: {status}\n---\n\n# {item_id}\n\n"
            "## Log de Execução\n\n- feito\n")


def legacy_fix(item_id, status):
    return (f"---\nid: {item_id}\ntitle: \"x\"\ntype: correção\nstatus: {status}\ndepends_on: []\n---\n\n# {item_id}\n\n"
            "## Evidência\n\n```text\n$ echo quebrado\nquebrado\n```\n")


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rite-migrate-")
        r = self.root = Path(self._tmp.name).resolve()
        git(r, "init", "-q")
        git(r, "config", "user.name", "T")
        git(r, "config", "user.email", "t@example.invalid")
        git(r, "config", "core.autocrlf", "false")
        write(r / "docs/PLAN-LEG.md", PLAN)
        write(r / "docs/prompts/perfil-leg.md", "# Perfil\n\n## Gates deste ciclo\n\n- `echo ok`\n\n"
                                                "## Verificações específicas por fase\n\n**Fase 1:** medir\n")
        t = r / "docs/tasks"
        write(t / "progresso.md", PROGRESS)
        write(t / "correcoes-progresso.md", FIXES)
        write(t / "01-primeira.md", legacy_task("LEG-TASK-01", "Primeira", "/docs/PLAN-LEG.md §4.2", "pendente"))
        write(t / "02-segunda.md", legacy_task("LEG-TASK-02", "Segunda", "/docs/PLAN-LEG.md §9.9 (x)",
                                               "concluído", deps='["LEG-TASK-01"]'))
        write(t / "03-fechamento.md", legacy_task("LEG-TASK-03", "Fechamento", "/docs/PLAN-LEG.md §1",
                                                  "pendente", type_="fechamento", deps='["LEG-TASK-02"]'))
        write(t / "CORR-LEG-001.md", legacy_fix("CORR-LEG-001", "concluída"))
        write(t / "CORR-LEG-002.md", legacy_fix("CORR-LEG-002", "pendente"))
        # an item an earlier convention named by ID, with another prefix, in the same folder
        write(t / "PAR-TASK-01.md", legacy_task("PAR-TASK-01", "Paridade", "/docs/PLAN-LEG.md §1", "concluído",
                                                 phase=""))  # its table has a § column, not a phase
        write(t / "CORR-LEG-003.md", legacy_fix("CORR-LEG-003", "concluída"))
        write(t / "concluidos/.keep", "")
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "chore: legacy")
        write(r / "src/a.py", "a\n")
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "feat: primeira (LEG-TASK-01)")
        self.work_sha = git(r, "rev-parse", "--short", "HEAD").strip()

    def tearDown(self):
        self._tmp.cleanup()

    def fields(self, name):
        return frontmatter.parse((self.root / "docs/tasks" / name).read_text(encoding="utf-8"))[0]

    def test_dry_run_writes_nothing(self):
        code, out, err = rite(self.root, "migrate", "--from", "we2002", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["items"], 7)
        self.assertFalse((self.root / "rite.toml").exists())
        self.assertEqual(git(self.root, "status", "--porcelain"), "")

    def test_write_then_check_is_green(self):
        code, out, err = rite(self.root, "migrate", "--from", "we2002", "--write", "--json")
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertTrue(any("9.9" in w for w in report["warnings"]))

        t1, t2, t3 = self.fields("01-primeira.md"), self.fields("02-segunda.md"), self.fields("03-fechamento.md")
        self.assertEqual((t1["status"], t1["done_on"], t1["reviewed_on"]), ("done", "2026-01-02", "2026-01-03"))
        self.assertEqual(t1["done_commit"], self.work_sha)  # found by the ID in the commit message
        self.assertEqual(t1["source_of_truth"], "/docs/PLAN-LEG.md#4.2")
        self.assertNotIn("fonte_de_verdade", t1)
        self.assertEqual((t2["reviewed_on"], t2["source_of_truth"]), ("pending", "/docs/PLAN-LEG.md"))
        self.assertTrue(t2["done_commit"])  # approximated by the last commit touching the file
        self.assertEqual((t3["type"], t3["status"], t3["reviewed_on"]), ("closing", "pending", None))

        c1, c2 = self.fields("CORR-LEG-001.md"), self.fields("CORR-LEG-002.md")
        self.assertEqual((c1["status"], c1["severity"], c1["origin"]), ("done", "high", "LEG-TASK-01"))
        self.assertEqual((c2["status"], c2["severity"], c2["origin"]), ("pending", "low", "LEG-TASK-02"))

        progress = (self.root / "docs/tasks/progresso.md").read_text(encoding="utf-8")
        self.assertIn("<!-- rite:begin tasks -->", progress)
        self.assertIn("Notas humanas ficam.", progress)
        self.assertNotIn("✅", progress)
        meta = frontmatter.parse(progress)[0]
        self.assertEqual((meta["prefix"], meta["cycle"]), ("LEG", "leg"))

        code, out, _ = rite(self.root, "check", "--json")
        self.assertEqual(json.loads(out)["errors"], 0, out)
        warnings = [f["message"] for f in json.loads(out)["findings"] if f["level"] == "warn"]
        # the generated [sections] names the pt-BR titles: Gates and Evidência are found
        self.assertEqual(warnings, ["id prefix PAR differs from cycle prefix LEG"])
        status = json.loads(rite(self.root, "status", "--json")[1])["cycles"][0]
        self.assertEqual(status["review_queue"], ["LEG-TASK-02"])
        self.assertEqual(status["open_fixes"]["low"], 1)

    def test_items_named_by_an_older_convention_are_migrated(self):
        code, out, err = rite(self.root, "migrate", "--from", "we2002", "--write", "--json")
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertFalse([w for w in report["warnings"] if "not recognized" in w], report["warnings"])
        par = self.fields("PAR-TASK-01.md")
        self.assertEqual((par["status"], par["done_on"], par["reviewed_on"]), ("done", "2026-01-05", "2026-01-06"))
        self.assertEqual(par["source_of_truth"], "/docs/PLAN-LEG.md#1")
        progress = (self.root / "docs/tasks/progresso.md").read_text(encoding="utf-8")
        self.assertEqual(progress.count("<!-- rite:begin tasks -->"), 1)
        self.assertIn("# Anexo — paridade", progress)          # the appendix prose stays
        self.assertIn("now lives in their frontmatter", progress)  # its state table does not
        self.assertNotIn("✅", progress)
        # new items are still named by the canonical (first) template
        code, out, err = rite(self.root, "new-task", "--title", "Nova", "--type", "closing", "--phase", "1",
                              "--source-of-truth", "/docs/PLAN-LEG.md#1", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["path"], "docs/tasks/04-nova.md")

    def test_approximated_commit_is_recorded_in_the_item(self):
        code, out, err = rite(self.root, "migrate", "--from", "we2002", "--write", "--json")
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertIn("LEG-TASK-02", report["approximated_commits"])
        self.assertNotIn("LEG-TASK-01", report["approximated_commits"])  # its commit names the ID
        body = (self.root / "docs/tasks/02-segunda.md").read_text(encoding="utf-8")
        log = body.split("## Log de Execução", 1)[1]
        self.assertRegex(log, r"_Migrated on \d{4}-\d{2}-\d{2}: done_commit approximated from the last "
                              r"commit touching this file\._")
        self.assertNotIn("approximated", (self.root / "docs/tasks/01-primeira.md").read_text(encoding="utf-8"))

    def test_missing_section_asks_the_operator_instead_of_inventing(self):
        code, out, _ = rite(self.root, "migrate", "--from", "we2002", "--json")
        actions = json.loads(out)["actions"]
        sections = [a for a in actions if "section" in a]
        self.assertEqual([a["item"] for a in sections], ["LEG-TASK-02"])
        self.assertEqual((sections[0]["target"], sections[0]["section"]), ("/docs/PLAN-LEG.md", "9.9"))
        self.assertIn("add a heading starting with '9.9'", sections[0]["action"])
        self.assertIn("rite anchors /docs/PLAN-LEG.md", sections[0]["action"])

    def test_unknown_phase_is_null_and_asked_for(self):
        code, out, err = rite(self.root, "migrate", "--from", "we2002", "--write", "--json")
        self.assertEqual(code, 0, err)
        phase_actions = [a["item"] for a in json.loads(out)["actions"] if "phase" in a["action"]]
        self.assertEqual(phase_actions, ["PAR-TASK-01"])
        self.assertIsNone(self.fields("PAR-TASK-01.md")["phase"])
        self.assertEqual(self.fields("01-primeira.md")["phase"], 1)

    def test_table_order_is_kept_as_execution_order(self):
        # by number, PAR-TASK-01 would sort next to LEG-TASK-01; the tables ran LEG 01-03, then PAR
        code, out, err = rite(self.root, "migrate", "--from", "we2002", "--write", "--json")
        self.assertEqual(code, 0, err)
        progress = (self.root / "docs/tasks/progresso.md").read_text(encoding="utf-8")
        self.assertEqual(frontmatter.parse(progress)[0]["order"],
                         ["LEG-TASK-01", "LEG-TASK-02", "LEG-TASK-03", "PAR-TASK-01"])
        region = progress.split("<!-- rite:begin tasks -->", 1)[1]
        self.assertLess(region.index("[LEG-TASK-03]"), region.index("[PAR-TASK-01]"))
        self.assertEqual(json.loads(rite(self.root, "next", "task", "--json")[1])["id"], "LEG-TASK-03")

    def test_pipe_inside_code_does_not_shift_columns(self):
        code, out, err = rite(self.root, "migrate", "--from", "we2002", "--write", "--json")
        self.assertEqual(code, 0, err)
        c3 = self.fields("CORR-LEG-003.md")
        self.assertEqual((c3["status"], c3["severity"], c3["done_on"]), ("done", "medium", "2026-01-07"))
        self.assertFalse([w for w in json.loads(out)["warnings"] if "CORR-LEG-003" in w])


class PrefixRuleTest(unittest.TestCase):
    """A foreign prefix is an error with single [naming] templates and a warning with lists."""

    def build(self, naming: str) -> Path:
        tmp = tempfile.TemporaryDirectory(prefix="rite-prefix-")
        self.addCleanup(tmp.cleanup)
        r = Path(tmp.name).resolve()
        git(r, "init", "-q")
        write(r / "rite.toml", f'[paths]\ncycles_root = "cycles"\n[naming]\n{naming}\n[vocab]\ntask_types = []\n')
        write(r / "cycles/a/progress.md", "---\nprefix: AAA\n---\n")
        write(r / "plan.md", "# P\n\n## 1. X\n")
        write(r / "cycles/a/OLD-TASK-01.md",
              '---\nid: OLD-TASK-01\ntitle: t\ntype: x\nphase: 1\ndepends_on: []\nsource_of_truth: "/plan.md#1"\n'
              "status: pending\ndone_on: null\ndone_commit: null\nreviewed_on: null\n---\n")
        rite(r, "sync", "--all")
        return r

    def findings(self, root: Path) -> list[tuple[str, str]]:
        out = rite(root, "check", "--all", "--quick", "--json")[1]
        return [(f["level"], f["message"]) for f in json.loads(out)["findings"] if "prefix" in f["message"]]

    def test_single_templates_are_strict(self):
        root = self.build('task_file = "{id}.md"')
        self.assertEqual(self.findings(root), [("error", "id prefix OLD differs from cycle prefix AAA")])

    def test_lists_allow_an_older_prefix(self):
        root = self.build('task_file = ["{n:02}-{slug}.md", "{id}.md"]')
        self.assertEqual(self.findings(root), [("warn", "id prefix OLD differs from cycle prefix AAA")])


if __name__ == "__main__":
    unittest.main()
