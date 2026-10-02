"""The dependency graph: a view of each task's `depends_on`, rendered into progress.md where its region
is, and `rite migrate --from graph` putting that region in place of a hand-drawn mermaid block."""

import json
import unittest

import test_state_json
from fixtures import fields, set_fields, write
from test_cli import FixtureCase

from rite_lib import render_md

HAND_DRAWN = """\
---
cycle: alpha
prefix: ALP
plan: /docs/plans/PLAN-alpha.md
---

# Progress — alpha

## {title}

```mermaid
graph TD
  A["ALP-TASK-01 harness"] --> B["ALP-TASK-02"]
  A --> C[ALP-TASK-03 close]
  X[a note] --> A
```

The order is the plan's.

## Tasks

<!-- rite:begin tasks -->
<!-- rite:end -->
"""


class DependencyGraphTest(unittest.TestCase):
    def test_one_subgraph_per_phase_and_an_edge_per_dependency(self):
        tasks = [{"id": "ALP-TASK-01", "title": "Harness", "phase": 1, "depends_on": []},
                 {"id": "ALP-TASK-03", "title": "Close", "phase": 2, "depends_on": ["ALP-TASK-01", "ALP-TASK-02"]},
                 {"id": "ALP-TASK-02", "title": "Report", "phase": 1, "depends_on": ["ALP-TASK-01"]},
                 {"id": "ALP-TASK-04", "title": "", "phase": None, "depends_on": ["OTHER-TASK-01"]}]
        self.assertEqual(render_md.dependency_graph(tasks, phase_label="Fase"), "\n".join([
            "```mermaid",
            "graph TD",
            '  subgraph phase_1["Fase 1"]',
            '    ALP_TASK_01["ALP-TASK-01<br/>Harness"]',
            '    ALP_TASK_02["ALP-TASK-02<br/>Report"]',
            "  end",
            '  subgraph phase_2["Fase 2"]',
            '    ALP_TASK_03["ALP-TASK-03<br/>Close"]',
            "  end",
            '  ALP_TASK_04["ALP-TASK-04"]',
            "  ALP_TASK_01 --> ALP_TASK_03",
            "  ALP_TASK_02 --> ALP_TASK_03",
            "  ALP_TASK_01 --> ALP_TASK_02",
            "```"]))

    def test_a_title_cannot_break_the_label(self):
        out = render_md.dependency_graph([{"id": "A-TASK-01", "title": 'Say "hi" <b> #1', "phase": 1}])
        self.assertIn('A_TASK_01["A-TASK-01<br/>Say #quot;hi#quot; #lt;b#gt; #35;1"]', out)

    def test_no_tasks(self):
        self.assertEqual(render_md.dependency_graph([]), "```mermaid\ngraph TD\n```")


class GraphRegionTest(FixtureCase):
    def cyc(self):
        return self.root / "docs/rite/cycles/alpha"

    def progress(self) -> str:
        return (self.cyc() / "progress.md").read_text(encoding="utf-8")

    def hand_drawn(self, title: str = "Dependency graph") -> None:
        write(self.cyc() / "progress.md", HAND_DRAWN.format(title=title))
        self.ok("sync", "--all")
        self.fx.git("commit", "-qam", "docs: hand-drawn graph")

    def migrate(self, *args) -> dict:
        return self.js("migrate", "--from", "graph", *args)

    def graph(self) -> str:
        return render_md.extract_region(self.progress(), render_md.GRAPH_REGION)

    def test_without_its_marker_the_graph_is_not_rendered(self):
        self.ok("mark", "ALP-TASK-01", "in-progress")
        self.assertNotIn("rite:begin graph", self.progress())
        self.assertEqual(self.check_errors("--all"), [])

    def test_new_cycle_renders_it(self):
        self.ok("new-cycle", "gamma", "--prefix", "GAM")
        self.ok("new-task", "--cycle", "gamma", "--title", "One", "--type", "feature", "--phase", "1",
                "--source-of-truth", "/docs/plans/PLAN-alpha.md#1")
        self.ok("new-task", "--cycle", "gamma", "--title", "Two", "--type", "feature", "--phase", "1",
                "--depends-on", "GAM-TASK-01", "--source-of-truth", "/docs/plans/PLAN-alpha.md#1")
        text = (self.root / "docs/rite/cycles/gamma/progress.md").read_text(encoding="utf-8")
        self.assertIn("## Dependency graph\n", text)
        self.assertIn("  GAM_TASK_01 --> GAM_TASK_02\n```\n<!-- rite:end -->", text)

    def test_dry_run_reports_the_edge_depends_on_lacks_and_writes_nothing(self):
        self.hand_drawn()
        report = self.migrate()
        self.assertEqual(report["cycles"], ["alpha: hand-drawn graph replaced", "beta: graph region added"])
        self.assertEqual(len(report["warnings"]), 2, report["warnings"])
        self.assertIn("alpha: ALP-TASK-01 --> ALP-TASK-03 is in the hand-drawn graph", report["warnings"][0])
        self.assertIn("naming no task, not compared: X", report["warnings"][1])
        self.assertEqual(self.fx.git("status", "--porcelain"), "")

    def test_write_swaps_only_the_block_and_runs_once(self):
        self.hand_drawn()
        report = self.migrate("--write", "--commit")
        self.assertTrue(report["commit"])
        self.assertEqual(self.log(1), ["chore(rite): generate dependency graphs from depends_on"])
        self.assertEqual(self.fx.git("status", "--porcelain"), "")
        text = self.progress()
        self.assertIn("## Dependency graph\n\n<!-- rite:begin graph -->\n```mermaid\n", text)
        self.assertIn("<!-- rite:end -->\n\nThe order is the plan's.\n\n## Tasks\n", text)
        self.assertNotIn("a note", text)
        self.assertIn("  ALP_TASK_02 --> ALP_TASK_03", self.graph())
        self.assertEqual(self.check_errors("--all"), [])
        self.assertEqual(self.migrate()["skipped"], ["alpha", "beta"])

    def test_a_missing_section_goes_before_the_tasks_table(self):
        self.migrate("--write")
        text = self.progress()
        self.assertLess(text.index("# Progress — alpha"), text.index("## Dependency graph\n\n<!-- rite:begin graph"))
        self.assertLess(text.index("<!-- rite:end -->"), text.index("<!-- rite:begin tasks -->"))
        self.assertEqual(self.check_errors("--all"), [])

    def test_section_titles_and_phase_label_come_from_the_config(self):
        toml = self.root / "rite.toml"
        toml.write_text(toml.read_text(encoding="utf-8") + '\n[sections]\nphase_label = "Fase"\n'
                        'dependency_graph = ["Grafo de dependências", "Dependency graph"]\n', encoding="utf-8")
        self.hand_drawn("Grafo de dependências")
        self.migrate("--write")
        self.assertIn("## Grafo de dependências\n\n<!-- rite:begin graph -->", self.progress())
        self.assertIn('subgraph phase_1["Fase 1"]', self.graph())

    def test_a_hand_edited_dependency_is_out_of_sync_until_sync(self):
        self.migrate("--write")
        set_fields(self.cyc() / "03-close-phase.md", {"depends_on": ["ALP-TASK-01"]})
        self.assertTrue(any("progress.md: generated view out of sync" in e for e in self.check_errors("--all")))
        self.ok("sync", "--all")
        self.assertIn("  ALP_TASK_01 --> ALP_TASK_03", self.graph())
        self.assertEqual(fields(self.cyc() / "03-close-phase.md")["depends_on"], ["ALP-TASK-01"])

    def test_the_standalone_script_renders_the_same_graph(self):
        self.migrate("--write")
        expected = self.progress()
        empty = render_md.replace_region(expected, render_md.GRAPH_REGION, "")
        (self.cyc() / "progress.md").write_text(empty, encoding="utf-8", newline="\n")
        res = test_state_json.RenderStandaloneTest.run_script(self, str(self.cyc()))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.progress(), expected)


if __name__ == "__main__":
    unittest.main()
