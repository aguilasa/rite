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
"""

FIXES = """\
# Correções

| ID | ID Task Origem | Título | Criticidade | Status | Concluída em |
|---|---|---|---|---|---|
| [CORR-LEG-001](/docs/tasks/CORR-LEG-001.md) | [LEG-TASK-01](/docs/tasks/01-primeira.md) | Um erro | Alta | [x] concluída | 2026-01-03 |
| [CORR-LEG-002](/docs/tasks/CORR-LEG-002.md) | [LEG-TASK-02](/docs/tasks/02-segunda.md) | Outro | Baixa | [ ] pendente | — |
"""


def legacy_task(item_id, title, sot, status, type_="implementação", deps="[]"):
    return (f"---\nid: {item_id}\ntitle: \"{title}\"\ntype: {type_}\ncategory: x\nphase: 1\n"
            f"depends_on: {deps}\nfonte_de_verdade: \"{sot}\"\nstatus: {status}\n---\n\n# {item_id}\n\n"
            "## Log de Execução\n\n- feito\n")


def legacy_fix(item_id, status):
    return f"---\nid: {item_id}\ntitle: \"x\"\ntype: correção\nstatus: {status}\ndepends_on: []\n---\n\n# {item_id}\n"


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rite-migrate-")
        r = self.root = Path(self._tmp.name).resolve()
        git(r, "init", "-q")
        git(r, "config", "user.name", "T")
        git(r, "config", "user.email", "t@example.invalid")
        git(r, "config", "core.autocrlf", "false")
        write(r / "docs/PLAN-LEG.md", PLAN)
        write(r / "docs/prompts/perfil-leg.md", "# Perfil\n\n## Verificações específicas por fase\n\n**Fase 1:** medir\n")
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
        self.assertEqual(json.loads(out)["items"], 5)
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
        status = json.loads(rite(self.root, "status", "--json")[1])["cycles"][0]
        self.assertEqual(status["review_queue"], ["LEG-TASK-02"])
        self.assertEqual(status["open_fixes"]["low"], 1)


if __name__ == "__main__":
    unittest.main()
