"""`rite reproduce`: a fix's evidence, run and measured, never judged."""

import json
import sys
import unittest
from pathlib import Path

from fixtures import Fixture

from rite_lib import compose

PY = f'"{sys.executable}"'


def fix_body(evidence: str, verification: str = "") -> str:
    return f"""\
---
id: {{id}}
title: t
origin: ALP-TASK-01
severity: low
files: []
resources: {{resources}}
status: pending
depends_on: []
done_on: null
done_commit: null
---

# {{id}} — t

## Problem

Wrong output.

## Evidence

{evidence}

## Root cause

## Fix

## Verification

{verification}

## Execution Log
"""


class EvidenceCommandsTest(unittest.TestCase):
    """Where the commands come from."""

    def test_dollar_lines_of_the_fenced_evidence(self):
        found = compose.evidence_commands(fix_body("```text\n$ node bin/x.mjs a\nBAD\n$ echo 2\n2\n```"))
        self.assertEqual(found, {"source": "Evidence", "heading": "Evidence", "why": "ok",
                                 "commands": ["node bin/x.mjs a", "echo 2"],
                                 "recorded": ["BAD", "2"]})

    def test_a_dollar_outside_a_fence_is_prose(self):
        found = compose.evidence_commands(fix_body("$ not a command\n\n```text\n$\n```"))
        self.assertEqual((found["source"], found["commands"]), (None, []))

    def test_verification_is_the_fallback(self):
        fenced = compose.evidence_commands(fix_body("```text\n$\nBAD\n```", "```sh\n$ run-check\n```"))
        self.assertEqual((fenced["source"], fenced["commands"], fenced["recorded"]),
                         ("Verification", ["run-check"], ["BAD"]))
        bullet = compose.evidence_commands(fix_body("", "- `run-check --all` turns green"))
        self.assertEqual((bullet["source"], bullet["commands"]), ("Verification", ["run-check --all"]))

    def test_no_command_anywhere_is_not_runnable(self):
        found = compose.evidence_commands(fix_body("It just breaks."))
        self.assertEqual((found["source"], found["why"]), (None, "no_command"))

    def test_a_heredoc_and_a_continued_line_are_one_command_each(self):
        found = compose.evidence_commands(fix_body(
            "```text\n"
            "$ python - <<'EOF'   # the balance\nimport json\nprint(1)\nEOF\n1\n"
            "$ for r in a b; do echo $r \\\n> done; done\na\nb\n"
            "```"))
        self.assertEqual(found["commands"], ["python - <<'EOF'   # the balance\nimport json\nprint(1)\nEOF",
                                             "for r in a b; do echo $r \\\ndone; done"])
        self.assertEqual(found["recorded"], ["1", "a", "b"])

    def test_a_heredoc_never_closed_runs_nothing(self):
        found = compose.evidence_commands(fix_body("```text\n$ echo ok\n$ cat <<X\nnever closed\n```"))
        self.assertEqual((found["why"], found["commands"], found["broken"]), ("unterminated", [], ["cat <<X"]))

    def test_a_title_mismatch_is_no_section_not_no_command(self):
        text = "# CORR-X\n\n## Evidência\n\n```text\n$ grep -n x f\n```\n"
        found = compose.evidence_commands(text)
        self.assertEqual((found["why"], found["looked_for"]), ("no_section", ["Evidence", "Verification"]))
        found = compose.evidence_commands(text, ["Evidence", "Evidência"], ["Verification"])
        self.assertEqual((found["why"], found["heading"], found["commands"]), ("ok", "Evidência", ["grep -n x f"]))

    def test_a_separated_suffix_still_names_the_section_and_a_near_miss_is_named(self):
        suffixed = "# X\n\n## Evidência — e as três vezes\n\n```text\n$ grep -n x f\n```\n"
        found = compose.evidence_commands(suffixed, ["Evidência"], ["Verificação"])
        self.assertEqual((found["why"], found["heading"]), ("ok", "Evidência — e as três vezes"))
        other = "# X\n\n## Evidência de que não é artefato\n\n```text\n$ grep -n x f\n```\n"
        found = compose.evidence_commands(other, ["Evidência"], ["Verificação"])
        self.assertEqual((found["why"], found["near"]), ("no_section", ["Evidência de que não é artefato"]))


class ReproduceTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture("subfolder")
        self.root = self.fx.root
        self.cycle = self.root / "docs/rite/cycles/alpha"

    def tearDown(self):
        self.fx.cleanup()

    def add_fix(self, evidence: str, *, resources: str = "[]", verification: str = "") -> str:
        code, out, err = self.fx.rite("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "t",
                                      "--severity", "low", "--json")
        self.assertEqual(code, 0, err)
        fix_id = json.loads(out)["id"]
        path = self.cycle / f"{fix_id}.md"
        path.write_text(fix_body(evidence, verification).replace("{id}", fix_id)
                        .replace("{resources}", resources), encoding="utf-8")
        return fix_id

    def reproduce(self, *args: str) -> dict:
        code, out, err = self.fx.rite("reproduce", "--cycle", "alpha", *args, "--json")
        self.assertEqual(code, 0, err + out)
        return json.loads(out)

    def test_the_whole_batch_in_one_call(self):
        bad = self.add_fix(f"```text\n$ {PY} -c \"print('BAD')\"\nBAD\n```")
        silent = self.add_fix("Nothing to run.")
        data = self.reproduce("--all")
        self.assertEqual([f["id"] for f in data["fixes"]], [bad, silent])
        first, second = data["fixes"]
        self.assertTrue(first["runnable"])
        self.assertEqual((first["commands"][0]["exit_code"], first["commands"][0]["output"].strip()), (0, "BAD"))
        self.assertEqual(first["recorded"], ["BAD"])
        self.assertEqual((second["runnable"], second["commands"]), (False, []))
        self.assertEqual(data["limit_kb"], 6)
        self.assertEqual(self.reproduce("--all"), data)  # the same structure, call after call

    def test_quotes_mean_what_they_mean_in_bash(self):
        # evidence is copied from bash sessions; cmd.exe would print the quotes and split on spaces
        fix_id = self.add_fix("```text\n$ echo 'a  b' | grep -c '^a  b$'\n1\n```")
        data = self.reproduce(fix_id)
        if data["shell"] == "system" and sys.platform == "win32":
            self.skipTest("no bash on this machine")
        run = data["fixes"][0]["commands"][0]
        self.assertEqual((run["exit_code"], run["output"].strip()), (0, "1"))

    def test_a_command_reads_no_stdin(self):
        # a heredoc (`python - <<'EOF'`) arrives one line at a time: `python -` must not wait forever
        fix_id = self.add_fix(f"```text\n$ {PY} -c \"import sys; print(len(sys.stdin.read()))\"\n```")
        run = self.reproduce(fix_id)["fixes"][0]["commands"][0]
        self.assertEqual((run["exit_code"], run["output"].strip()), (0, "0"))

    def test_one_fix_and_a_missing_command(self):
        fix_id = self.add_fix("```text\n$ rite-no-such-command-xyz\n```")
        run = self.reproduce(fix_id)["fixes"][0]["commands"][0]
        self.assertNotEqual(run["exit_code"], 0)  # the caller reads this as CANNOT RUN

    def test_a_passing_command_is_cut_to_its_tail(self):
        fix_id = self.add_fix(f"```text\n$ {PY} -c \"[print(i) for i in range(50)]\"\n```")
        run = self.reproduce(fix_id, "--tail", "5")["fixes"][0]["commands"][0]
        self.assertEqual(run["output"].split(), ["45", "46", "47", "48", "49"])
        self.assertTrue(run["truncated"])

    def test_an_output_above_the_limit_goes_to_an_agent(self):
        toml = self.root / "rite.toml"
        toml.write_text(toml.read_text(encoding="utf-8") + "\n[limits]\ninline_triage_max_output_kb = 1\n",
                        encoding="utf-8")
        # a failing command keeps its whole output — until it passes the limit
        fix_id = self.add_fix(f"```text\n$ {PY} -c \"import sys; [print('x' * 99) for _ in range(40)]; "
                              f"sys.exit(1)\"\n```")
        fix = self.reproduce(fix_id, "--tail", "3")["fixes"][0]
        self.assertTrue(fix["over_limit"])
        self.assertGreater(fix["held_bytes"], 1024)
        self.assertEqual(len(fix["commands"][0]["output"].splitlines()), 3)

    def test_scratch_leaves_the_tree_alone(self):
        writes = f"```text\n$ {PY} -c \"open('touched.txt', 'w').write('x')\"\n```"
        fix_id = self.add_fix(writes)
        self.reproduce(fix_id, "--scratch")
        self.assertFalse((self.root / "touched.txt").exists())
        self.reproduce(fix_id)
        self.assertTrue((self.root / "touched.txt").exists())

    def test_a_serialized_resource_runs_in_order_and_is_named(self):
        first = self.add_fix(f"```text\n$ {PY} -c \"print(1)\"\n```", resources="[board]")
        second = self.add_fix(f"```text\n$ {PY} -c \"print(2)\"\n```", resources="[board]")
        data = self.reproduce("--all")
        self.assertEqual([(f["id"], f["resources"]) for f in data["fixes"]], [(first, ["board"]), (second, ["board"])])

    def test_the_limit_is_a_positive_number(self):
        toml = self.root / "rite.toml"
        toml.write_text(toml.read_text(encoding="utf-8") + "\n[limits]\ninline_triage_max_output_kb = 0\n",
                        encoding="utf-8")
        code, _, err = self.fx.rite("status")
        self.assertEqual(code, 1)
        self.assertIn("inline_triage_max_output_kb", err)

    def test_needs_a_fix_or_all(self):
        code, _, err = self.fx.rite("reproduce", "--cycle", "alpha")
        self.assertEqual(code, 1)
        self.assertIn("--all", err)

    def evidence_warnings(self, fix_id: str) -> list[str]:
        code, out, err = self.fx.rite("check", "--cycle", "alpha", "--json")
        self.assertEqual(code, 0, err + out)
        return [f["message"] for f in json.loads(out)["findings"]
                if f["level"] == "warn" and fix_id in f["path"] and "Evidence" in f["message"]]

    def test_check_warns_on_a_script_that_is_not_in_the_repository(self):
        # a reviewer measured with scripts in its scratch copy, then cited them; the copy is gone
        fix_id = self.add_fix("```text\n$ python run.py\n316 of 520\n$ python src/app.py\nhi\n"
                              "$ python $TMP/x.py\n$ cd /tmp/scratch && python run2.py\n```")
        warnings = self.evidence_warnings(fix_id)
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("runs `run.py`, which is not in the repository", warnings[0])

    def test_check_warns_on_a_python_heredoc_holding_its_output(self):
        fix_id = self.add_fix("```text\n$ python - <<'EOF'\nslot 1 max rotation spread 4552\nEOF\n```")
        warnings = self.evidence_warnings(fix_id)
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("a heredoc that is not Python", warnings[0])
        fine = self.add_fix("```text\n$ python - <<'EOF'\nprint(4552)\nEOF\n4552\n```")
        self.assertEqual(self.evidence_warnings(fine), [])


class StaleRuleTest(unittest.TestCase):
    """`mark-stale` closes a fix unrepaired: the rule names what never authorizes it."""

    def test_the_evidence_rule_never_reads_a_shell_error_as_stale(self):
        root = Path(__file__).resolve().parent.parent
        text = (root / "parts" / "evidence.md").read_text(encoding="utf-8")
        rule = next(b for b in text.split("\n- ") if "NOT REPRODUCED" in b)
        for term in ("why: ok", "shell_error", "CANNOT RUN", "never *stale*", "exit code is not a verdict"):
            self.assertIn(term, " ".join(rule.split()), term)
        reproducer = (root / "agents" / "rite-reproducer.md").read_text(encoding="utf-8")
        self.assertIn("never `NOT REPRODUCED`", reproducer)


if __name__ == "__main__":
    unittest.main()
