"""The JSON state: progress.json / fixes.json are the only state, the markdown views are rendered from
them by a standalone script, and `rite migrate --from frontmatter` brings older cycles over."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fixtures import ROOT, fields, git, rite, set_fields, write

from test_cli import FixtureCase

from rite_lib import config, model, ops, state
from rite_lib.model import Project, RiteError


class StateFileTest(unittest.TestCase):
    def test_dumps_is_deterministic_with_scalar_lists_inline(self):
        data = {"schema": 1, "order": ["A", "B"], "tasks": [{"id": "A", "depends_on": [], "phase": None}]}
        text = state.dumps(data)
        self.assertEqual(text, '{\n  "schema": 1,\n  "order": ["A", "B"],\n  "tasks": [\n    {\n'
                               '      "id": "A",\n      "depends_on": [],\n      "phase": null\n    }\n  ]\n}\n')
        self.assertEqual(json.loads(text), data)
        self.assertEqual(state.dumps(json.loads(text)), text)

    def test_unknown_schema_and_bad_json_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "progress.json"
            path.write_text('{"schema": 2}', encoding="utf-8")
            with self.assertRaisesRegex(state.StateError, "schema 2"):
                state.read(path)
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(state.StateError, "not valid JSON"):
                state.read(path)

    def test_an_edit_that_changes_nothing_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "progress.json"
            path.write_text('{"schema":1,"tasks":[]}', encoding="utf-8")  # not in our format
            state.edit(path, lambda data: None)
            self.assertEqual(path.read_text(encoding="utf-8"), '{"schema":1,"tasks":[]}')
            self.assertFalse(path.with_name("progress.json.lock").exists())

    def test_a_held_lock_is_reported_not_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixes.json"
            path.write_text('{"schema": 1, "fixes": []}', encoding="utf-8")
            path.with_name("fixes.json.lock").write_text("", encoding="utf-8")
            with mock.patch.object(state, "LOCK_TIMEOUT_S", 0.1), \
                    self.assertRaisesRegex(state.StateError, "held by another rite process"):
                state.edit(path, lambda data: data["fixes"].append({"id": "X"}))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["fixes"], [])


class JsonStateTest(FixtureCase):
    def cyc(self) -> Path:
        return self.root / "docs/rite/cycles/alpha"

    def check_errors(self, *args) -> list[str]:
        out = self.fx.rite("check", "--all", "--json", *args)[1]
        return [f"{f['path']}: {f['message']}" for f in json.loads(out)["findings"] if f["level"] == "error"]

    def test_the_cli_writes_only_the_json_and_the_views(self):
        before = (self.cyc() / "01-harness.md").read_bytes()
        self.ok("mark", "ALP-TASK-01", "in-progress")
        self.assertEqual((self.cyc() / "01-harness.md").read_bytes(), before)  # no log line for it
        self.assertEqual(fields(self.cyc() / "01-harness.md")["status"], "in-progress")
        self.assertIn("| in-progress |", (self.cyc() / "progress.md").read_text(encoding="utf-8"))
        self.assertEqual(set(self.fx.git("status", "--porcelain").split()) - {"M"},
                         {"docs/rite/cycles/alpha/progress.json", "docs/rite/cycles/alpha/progress.md"})

    def test_new_items_keep_only_their_id_in_the_markdown(self):
        res = self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "Broken: it", "--severity",
                      "high")
        text = (self.root / res["path"]).read_text(encoding="utf-8")
        self.assertTrue(text.startswith(f"---\nid: {res['id']}\n---\n\n# {res['id']} — Broken: it\n"), text)
        f = fields(self.root / res["path"])
        self.assertEqual((f["title"], f["severity"], f["status"], f["files"]), ("Broken: it", "high", "pending", []))
        self.assertEqual(self.check_errors(), [])

    def test_set_writes_planning_fields_and_nothing_else(self):
        self.ok("set", "ALP-TASK-02", "--files", "src/a.py,src/b.py", "--resources", "display")
        f = fields(self.cyc() / "02-report.md")
        self.assertEqual((f["files"], f["resources"]), (["src/a.py", "src/b.py"], ["display"]))
        self.ok("set", "ALP-TASK-02", "--files", "")
        self.assertEqual(fields(self.cyc() / "02-report.md")["files"], [])
        self.assertEqual(self.fx.rite("set", "ALP-TASK-02")[0], 1)
        project = Project(config.load(self.root))
        cycle, item = project.find_item("ALP-TASK-02")
        with self.assertRaisesRegex(RiteError, "belongs to the CLI"):
            ops.set_fields(project, cycle, item, {"status": "done"})

    def test_set_cycle_ticket_and_plan(self):
        self.ok("set-cycle", "--cycle", "alpha", "--ticket", "PROJ-7")
        self.assertEqual(self.js("resolve-cycle", "alpha")["ticket"], "PROJ-7")
        self.ok("set-cycle", "--cycle", "alpha", "--ticket", "")
        self.assertIsNone(self.js("resolve-cycle", "alpha")["ticket"])
        state_doc = json.loads((self.cyc() / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(list(state_doc)[-1], "tasks")  # the item array stays last

    def test_check_finds_what_a_hand_edit_breaks(self):
        # an item file nobody listed
        write(self.cyc() / "04-stray.md", "---\nid: ALP-TASK-04\n---\n\n# stray\n")
        self.assertTrue(any("04-stray.md: task file not listed in progress.json" in e for e in self.check_errors()))
        (self.cyc() / "04-stray.md").unlink()
        # an entry whose file is gone
        (self.cyc() / "02-report.md").unlink()
        self.assertTrue(any("02-report.md: file not found" in e for e in self.check_errors()))
        self.fx.git("checkout", "--", "docs/rite/cycles/alpha/02-report.md")
        # state written back into the markdown
        path = self.cyc() / "01-harness.md"
        path.write_text(path.read_text(encoding="utf-8").replace("id: ALP-TASK-01\n", "id: ALP-TASK-01\nstatus: done\n"),
                        encoding="utf-8")
        self.assertTrue(any("frontmatter holds status" in e for e in self.check_errors()))
        path.write_text(path.read_text(encoding="utf-8").replace("status: done\n", "").replace("ALP-TASK-01\n---",
                                                                                                "ALP-TASK-09\n---"),
                        encoding="utf-8")
        self.assertTrue(any("id 'ALP-TASK-09' differs from ALP-TASK-01" in e for e in self.check_errors()))

    def test_a_broken_json_is_named(self):
        (self.cyc() / "progress.json").write_text("{", encoding="utf-8")
        code, _, err = self.fx.rite("check", "--all")
        self.assertEqual(code, 1)
        self.assertIn("progress.json: not valid JSON", err)

    def test_out_of_order_array_is_stale_until_sync(self):
        doc = json.loads((self.cyc() / "progress.json").read_text(encoding="utf-8"))
        doc["tasks"].reverse()
        (self.cyc() / "progress.json").write_text(state.dumps(doc), encoding="utf-8")
        self.assertTrue(any("progress.json: generated view out of sync" in e for e in self.check_errors()))
        self.ok("sync", "--all")
        self.assertEqual(self.check_errors(), [])
        doc = json.loads((self.cyc() / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual([t["id"] for t in doc["tasks"]], ["ALP-TASK-01", "ALP-TASK-02", "ALP-TASK-03"])

    def test_guard_refuses_a_hand_edit_of_the_state(self):
        code, out, _ = self.fx.rite("guard", "docs/rite/cycles/alpha/progress.json")
        self.assertEqual(code, 1)
        self.assertIn("Rite's state", out)
        self.assertEqual(self.fx.rite("guard", "docs/rite/cycles/alpha/01-harness.md")[0], 0)
        self.assertEqual(self.fx.rite("guard", "package.json")[0], 0)  # a JSON file that is not state
        ev = {"cwd": str(self.root), "tool_name": "Edit",
              "tool_input": {"file_path": str(self.cyc() / "fixes.json")}}
        res = subprocess.run([sys.executable, str(ROOT / "hooks" / "guard.py")], input=json.dumps(ev),
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(res.returncode, 2)

    def test_a_cycle_from_before_the_json_state_asks_for_the_migration(self):
        legacy = self.root / "docs/rite/cycles/old"
        write(legacy / "progress.md", "---\ncycle: old\nprefix: OLD\n---\n\n# Progress — old\n")
        code, _, err = self.fx.rite("status", "--all")
        self.assertEqual(code, 1)
        self.assertIn("rite migrate --from frontmatter", err)


class RenderStandaloneTest(FixtureCase):
    """render_md.py runs with nothing of Rite beside it, and renders what Rite renders."""

    def run_script(self, *args: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "render_md.py"
            shutil.copyfile(ROOT / "rite_lib" / "render_md.py", script)
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            return subprocess.run([sys.executable, "-I", str(script), *args], cwd=tmp, env=env,
                                  capture_output=True, text=True, encoding="utf-8")

    def test_rebuilds_the_views_rite_writes(self):
        cyc = self.root / "docs/rite/cycles/alpha"
        self.ok("mark", "ALP-TASK-02", "blocked", "--reason", "waiting")
        expected = (cyc / "progress.md").read_bytes()
        text = expected.decode("utf-8")
        start = text.index("<!-- rite:begin tasks -->")
        (cyc / "progress.md").write_text(text[:start] + "<!-- rite:begin tasks -->\n<!-- rite:end -->\n",
                                         encoding="utf-8", newline="\n")
        res = self.run_script(str(cyc), "--check")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        res = self.run_script(str(cyc))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((cyc / "progress.md").read_bytes(), expected)
        self.assertEqual(self.run_script(str(cyc), "--check").returncode, 0)

    def test_creates_a_missing_view(self):
        cyc = self.root / "docs/rite/cycles/alpha"
        (cyc / "fixes.md").unlink()
        res = self.run_script(str(cyc))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue((cyc / "fixes.md").read_text(encoding="utf-8").startswith("# Fixes — alpha\n"))


# --- migration: frontmatter -> JSON -----------------------------------------------
# A miniature of the two layouts it was planned on: pt-BR names, an archive folder that is itself a
# cycle with cycles nested in it, items named by ID, an `order:` with another prefix, keys outside
# Rite's vocabulary, a blocked fix, a NUL byte in a body, frontmatter comments, a non-item file.
CONFIG = """\
[project]
docs_language = "pt-BR"
[paths]
cycles_root  = "docs/tasks"
archive_dir  = "docs/tasks/concluidos"
profiles_dir = "docs/prompts"
plans_dir    = "docs"
[naming]
task_file     = ["{n:02}-{slug}.md", "{id}.md"]
fix_id        = "CORR-{prefix}-{n:03}"
progress_file = "progresso.md"
fixes_file    = "correcoes-progresso.md"
profile_file  = "perfil-{cycle}.md"
pitfalls_file = "perfil-{cycle}.armadilhas.md"
[sections]
execution_log = "Log de Execução"
evidence = "Evidência"
[vocab]
task_types = ["implementação", "closing"]
"""


def item(item_id: str, status: str = "pending", extra: str = "", deps: str = "[]") -> str:
    return (f"---\nid: {item_id}\ntitle: \"{item_id} título\"\ntype: implementação\nphase: 1\n"
            f"depends_on: {deps}\nsource_of_truth: \"/docs/PLAN.md#1\"\n{extra}"
            f"files: []            # predicted paths\nresources: []\nstatus: {status}\ndone_on: null\n"
            f"done_commit: null\nreviewed_on: null\nreview_commit: null\n---\n\n# {item_id}\n\n"
            "## Log de Execução\n")


def progress(cycle: str, prefix: str, extra: str = "") -> str:
    return (f"---\ncycle: {cycle}\nprefix: {prefix}\n{extra}---\n\n# Progresso — {cycle}\n\n"
            "Prosa humana fica.\n\n<!-- rite:begin tasks -->\n<!-- rite:end -->\n\n## Notas\n")


class MigrateToJsonTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rite-tojson-")
        self.addCleanup(self._tmp.cleanup)
        r = self.root = Path(self._tmp.name).resolve()
        git(r, "init", "-q")
        git(r, "config", "user.name", "T")
        git(r, "config", "user.email", "t@example.invalid")
        git(r, "config", "core.autocrlf", "false")
        write(r / "rite.toml", CONFIG)
        write(r / "docs/PLAN.md", "# Plano\n\n## 1. Contexto\n")
        t = r / "docs/tasks"
        write(t / "kits/progresso.md", progress("kits", "KIT", "profile: /docs/prompts/perfil-kits.md\n"))
        write(t / "kits/correcoes-progresso.md", "# Correções — kits\n")
        write(t / "kits/01-ler.md", item("KIT-TASK-01", extra="category: dados\n"))
        write(t / "kits/02-gravar.md", item("KIT-TASK-02", extra="category: dados\n", deps="[KIT-TASK-01]"))
        self.fix = t / "kits/CORR-KIT-001.md"
        self.fix.write_bytes(
            b"---\nid: CORR-KIT-001\ntitle: \"quebra\"\norigin: KIT-TASK-01\nseverity: medium\nfiles: []\n"
            b"resources: []        # serialized resources\nstatus: blocked\ndepends_on: []\ndone_on: null\n"
            b"done_commit: null\nunblocked_by: \"python -c 'print(1)'\"\n---\n\n# CORR-KIT-001\n\n"
            b"## Evid\xc3\xaancia\n\n```text\n$ echo \"MASTER DATA\x00\"\n```\n")
        write(t / "kits/retro.md", "# Retro\n")  # not an item: left alone
        # the archive folder is itself a closed cycle, and holds closed cycles
        write(t / "concluidos/progresso.md",
              progress("wte", "WTE", "order: [WTE-TASK-01, PAR-TASK-01, WTE-TASK-02]\n"))
        write(t / "concluidos/01-a.md", item("WTE-TASK-01", "skipped", extra="projeto: newWe2002\n"))
        write(t / "concluidos/02-b.md", item("WTE-TASK-02", "skipped"))
        write(t / "concluidos/PAR-TASK-01.md", item("PAR-TASK-01", "skipped"))
        write(t / "concluidos/looks/progresso.md", progress("looks", "LOOKS"))
        write(t / "concluidos/looks/01-olhar.md", item("LOOKS-TASK-01", "skipped"))
        # the views as Rite <= 0.13 left them
        from rite_lib import legacy
        old = legacy.LegacyProject(config.load(r))
        for d in old._cycle_dirs(old.cycles_root) + old.archived_dirs():
            legacy.sync(old, old.load_cycle(d))
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "chore: legacy")

    def migrate(self, *args: str) -> dict:
        code, out, err = rite(self.root, "migrate", "--from", "frontmatter", *args, "--json")
        self.assertEqual(code, 0, err + out)
        return json.loads(out)

    def test_dry_run_reports_and_writes_nothing(self):
        report = self.migrate()
        self.assertEqual(report["items"], 7)
        self.assertEqual(len(report["cycles"]), 3)
        self.assertEqual(report["extra_keys"], {"category": 2, "projeto": 1})
        self.assertEqual(report["comments"], 7)
        self.assertEqual(git(self.root, "status", "--porcelain"), "")

    def test_write_moves_the_state_and_changes_nothing_else(self):
        old_body = self.fix.read_bytes().split(b"\n---\n", 1)[1]
        report = self.migrate("--write", "--commit")
        self.assertTrue(report["commit"])
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        self.assertEqual(git(self.root, "log", "--format=%s", "-1").strip(), "chore(rite): move cycle state to JSON")

        t = self.root / "docs/tasks"
        self.assertEqual(self.fix.read_bytes(), b"---\nid: CORR-KIT-001\n---\n" + old_body)  # NUL and all
        fix = fields(self.fix)
        self.assertEqual((fix["status"], fix["unblocked_by"]), ("blocked", "python -c 'print(1)'"))
        self.assertEqual(fields(t / "kits/01-ler.md")["category"], "dados")
        self.assertEqual(fields(t / "concluidos/01-a.md")["projeto"], "newWe2002")
        meta = fields(t / "concluidos/progresso.md")
        self.assertEqual(meta["order"], ["WTE-TASK-01", "PAR-TASK-01", "WTE-TASK-02"])
        self.assertEqual(fields(t / "kits/progresso.md")["profile"], "/docs/prompts/perfil-kits.md")
        prog = (t / "kits/progresso.md").read_text(encoding="utf-8")
        self.assertTrue(prog.startswith("# Progresso — kits\n\nProsa humana fica."), prog)
        self.assertIn("## Notas", prog)
        self.assertEqual((t / "kits/retro.md").read_text(encoding="utf-8"), "# Retro\n")
        doc = json.loads((t / "concluidos/progress.json").read_text(encoding="utf-8"))
        self.assertEqual([e["file"] for e in doc["tasks"]], ["01-a.md", "PAR-TASK-01.md", "02-b.md"])

        code, out, _ = rite(self.root, "check", "--all", "--include-archived", "--json")
        self.assertEqual(json.loads(out)["errors"], 0, out)
        self.assertEqual(json.loads(rite(self.root, "next", "fix", "--json")[1])["id"], None)  # blocked
        # the cycles read back as they were: one more run finds nothing to do
        again = self.migrate("--write")
        self.assertEqual((again["cycles"], again["changed"]), ([], []))
        self.assertEqual(len(again["skipped"]), 3)

    def test_a_reader_that_would_lose_a_field_stops_it_before_any_write(self):
        original = model.Project._item_from_entry

        def lossy(self, cycle, kind, entry):
            got = original(self, cycle, kind, entry)
            got.fields.pop("category", None)
            return got

        with mock.patch.object(model.Project, "_item_from_entry", lossy):
            code, _, err = rite(self.root, "migrate", "--from", "frontmatter", "--write")
        self.assertEqual(code, 1)
        self.assertIn("would not read back", err)
        self.assertIn("KIT-TASK-01 fields", err)
        self.assertEqual(git(self.root, "status", "--porcelain"), "")

    def test_uncommitted_edits_are_not_mixed_in(self):
        path = self.root / "docs/tasks/kits/01-ler.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nnota\n", encoding="utf-8")
        code, _, err = rite(self.root, "migrate", "--from", "frontmatter", "--write")
        self.assertEqual(code, 1)
        self.assertIn("uncommitted changes", err)
        self.assertFalse((self.root / "docs/tasks/kits/progress.json").exists())


if __name__ == "__main__":
    unittest.main()
