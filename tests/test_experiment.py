"""The token experiment without a model: its matrix, its measurement of one cell, its estimate."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import experiment  # noqa: E402
import token_report as tr  # noqa: E402


def invocation() -> tr.Invocation:
    inv = tr.Invocation("/rite:fix-all", "s")
    inv.add_usage({"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000,
                   "output_tokens": 5})
    inv.add_tool("rite:cli")
    for kind, billed, shell_bytes in (("rite:rite-reproducer", 50, 40), ("rite:rite-worker", 70, 0)):
        run = tr.AgentRun(kind, kind)
        run.add_usage({"input_tokens": 0, "cache_creation_input_tokens": billed - 10,
                       "cache_read_input_tokens": 500, "output_tokens": 10})
        run.measured, run.shell_bytes, run.main_turns_after = True, shell_bytes, 3
        inv.agents.append(run)
    return inv


class ExperimentTest(unittest.TestCase):
    def test_matrix(self):
        cells = experiment.plan_cells(["as-is"], [1, 2, 4], 2, "fix-all")
        self.assertEqual([(c["n"], c["rep"]) for c in cells],
                         [(1, 1), (1, 2), (2, 1), (2, 2), (4, 1), (4, 2)])
        # the control is one review, whatever the sizes asked
        self.assertEqual([c["n"] for c in experiment.plan_cells(["a", "b"], [1, 2, 4], 1, "review")], [1, 1])

    def test_measure_keeps_raw_numbers_per_side_and_type(self):
        cell = experiment.measure(invocation())
        self.assertEqual((cell["main"]["billed"], cell["main"]["ceremony"], cell["agents"]), (115, 1, 2))
        self.assertEqual(cell["agent"]["billed"], 120)
        reproducer = cell["agent"]["by_type"]["rite:rite-reproducer"]
        self.assertEqual((reproducer["n"], reproducer["billed"], reproducer["shell_bytes"]), (1, 50, 40))
        self.assertEqual(set(cell["main"]), {"billed", "input", "cache_write", "cache_read", "output",
                                             "turns", "ceremony"})

    def test_an_unmeasured_agent_is_unknown(self):
        inv = invocation()
        inv.agents[1].measured = False
        self.assertEqual(experiment.measure(inv)["agent"], "unknown")

    def test_estimate_scales_agents_with_n(self):
        ref = {"source": "x", "main": {"billed": 100, "cache_read": 1000, "output": 10},
               "per_agent": {"billed": 50, "cache_read": 500, "output": 5}}
        cells = experiment.plan_cells(["as-is"], [1, 2], 1, "fix-all")
        guess = experiment.estimate(cells, ref, "fix-all")
        self.assertEqual(guess["tokens"], 2 * 1100 + (2 + 4) * 550)
        self.assertEqual(set(guess), {"tokens", "agents_included"})

    def test_nothing_runs_without_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "b.json"
            baseline.write_text(json.dumps({"commands": {}}), encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(experiment.main(["--repeat", "1"]), 2)
                self.assertEqual(experiment.main(["--repeat", "1", "--dry-run"]), 0)
        self.assertIn("pass --yes", err.getvalue())
        self.assertIn("3 run(s)", out.getvalue())


TOKENS = Path(__file__).resolve().parent / "tokens"


class ReportTest(unittest.TestCase):
    """The report is deterministic: a fixed matrix gives fixed bytes."""

    def matrix(self) -> dict:
        return json.loads((TOKENS / "matrix.json").read_text(encoding="utf-8"))

    def test_markdown_is_byte_for_byte(self):
        expected = (TOKENS / "report.md").read_bytes()
        self.assertEqual(experiment.render_markdown(self.matrix()).encode("utf-8"), expected)
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "2026-09-23-x.json"
            copy.write_bytes((TOKENS / "matrix.json").read_bytes())
            first = experiment.write_report(copy).read_bytes()
            second = experiment.write_report(copy).read_bytes()
        self.assertEqual(first, expected)
        self.assertEqual(first, second)

    def test_fit_separates_ceremony_from_the_cost_per_fix(self):
        line = experiment.analyze(self.matrix())["as-is"]
        self.assertAlmostEqual(line["main"]["intercept"], 40500)
        self.assertAlmostEqual(line["agent"]["slope"], 26150)
        self.assertAlmostEqual(line["by_type"]["rite:rite-reproducer"]["slope"], 6900)
        self.assertEqual(line["invalid"], 1)
        self.assertIsNone(experiment.fit([(1, 10.0), (1, 12.0)]))  # one N: no line

    def test_triage_verdicts(self):
        cells = [c for c in self.matrix()["cells"] if c.get("valid")]
        self.assertEqual(experiment.triage_verdict([])["verdict"], "none")
        verdict = experiment.triage_verdict(cells)
        self.assertEqual((verdict["verdict"], verdict["turn_over"]), ("apply", 1))
        self.assertIn("inline_triage_max_output_kb", verdict)
        self.assertNotIn("inline_triage_max", verdict)  # never a cap on the number of fixes
        # an output read back for ever makes the reproducer the cheaper side
        heavy = json.loads(json.dumps(cells))
        for cell in heavy:
            cell["agent"]["by_type"]["rite:rite-reproducer"]["shell_bytes"] = 4_000_000 * cell["n"]
        self.assertEqual(experiment.triage_verdict(heavy)["verdict"], "do not apply")
        # a difference within the dispersion decides nothing
        noisy = json.loads(json.dumps(cells))
        for cell in noisy:
            if cell["rep"] == 2:
                cell["agent"]["by_type"]["rite:rite-reproducer"]["billed"] *= 50
        self.assertEqual(experiment.triage_verdict(noisy)["verdict"], "inconclusive")
        # the weight is part of the verdict: cache reads at full rate make the main thread's turn dearer
        light, full = (experiment.triage_verdict(cells, weight=w)["rows"][0] for w in (0.1, 1.0))
        self.assertGreater(full["inline"]["effective"] - light["inline"]["effective"],
                           full["agent"]["effective"] - light["agent"]["effective"])

    def test_labels_are_compared_on_the_whole_invocation(self):
        matrix = self.matrix()
        other = json.loads(json.dumps([c for c in matrix["cells"] if c.get("valid")]))
        for cell in other:
            cell["label"] = "lean"
            for side in (cell["main"], cell["agent"]):
                side["billed"], side["cache_read"] = side["billed"] // 2, side["cache_read"] // 2
        matrix["cells"] += other
        matrix["meta"]["labels"].append({"label": "lean", "version": "", "commit": ""})
        rows = experiment.compare_labels(matrix)
        for row in rows:
            got = row["labels"]
            self.assertAlmostEqual(got["lean"]["effective"] / got["as-is"]["effective"], 0.5, delta=0.01)
        text = experiment.render_markdown(matrix)
        self.assertIn("## Labels compared", text)
        self.assertIn("-50%", text)
        self.assertNotIn("## Labels compared", experiment.render_markdown(self.matrix()))

    def test_triage_of_the_measured_fix_all(self):
        """The matrix of 2026-09-23 gives the table CONCEPTS.md quotes: inline from N = 2 up."""
        path = Path(__file__).resolve().parent.parent / "docs" / "tokens" / "2026-09-23-fixall-as-is.json"
        cells = [c for c in json.loads(path.read_text(encoding="utf-8"))["cells"] if c.get("valid")]
        verdict = experiment.triage_verdict(cells)
        self.assertEqual((verdict["verdict"], verdict["turn_over"]), ("apply", 2))
        rows = {r["n"]: r for r in verdict["rows"]}
        self.assertEqual([round(rows[n]["agent"]["effective"]) for n in (1, 2, 4)], [6183, 8215, 16416])
        self.assertEqual([round(rows[n]["inline"]["effective"]) for n in (1, 2, 4)], [7570, 7535, 9266])
        self.assertEqual([rows[n]["side"] for n in (1, 2, 4)], ["open", "inline", "inline"])
        self.assertEqual(verdict["inline_triage_max_output_kb"], 6)


if __name__ == "__main__":
    unittest.main()
