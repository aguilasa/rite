"""The token measurement itself: grouping, classification and the baseline check."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import token_report as tr  # noqa: E402


def user(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def result(tool_use_id: str, body: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_use_id, "content": body}]}}


def assistant(msg_id: str, *, usage: dict | None = None, tool: tuple | None = None) -> dict:
    content = []
    if tool:
        name, tool_input, tid = tool
        content.append({"type": "tool_use", "id": tid, "name": name, "input": tool_input})
    message = {"id": msg_id, "role": "assistant", "content": content}
    if usage:
        message["usage"] = usage
    return {"type": "assistant", "message": message}


USAGE = {"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000,
         "output_tokens": 5}

TRANSCRIPT = [
    user("<command-name>/rite:execute</command-name>"),
    assistant("m1", usage=USAGE, tool=("Bash", {"command": 'sh "$ROOT/bin/rite" next task --json'}, "t1")),
    result("t1", "{}"),
    # the same message split into several entries must count as one turn
    assistant("m1", usage=USAGE, tool=("Read", {"file_path": "/plugins/rite/shared/layers.md"}, "t2")),
    result("t2", "x" * 50),
    assistant("m2", usage=USAGE, tool=("Bash", {"command": "cd repo && git commit -m x"}, "t3")),
    assistant("m3", usage=USAGE, tool=("Bash", {"command": "cd repo && npm test"}, "t4")),
    assistant("m4", usage=USAGE, tool=("Edit", {"file_path": "src/a.py"}, "t5")),
    assistant("m5", usage=USAGE, tool=("Task", {"subagent_type": "rite:rite-worker"}, "t6")),
    result("t6", "y" * 9000),
    user("<command-name>/rite:review</command-name>"),
    assistant("m6", usage=USAGE, tool=("Bash", {"command": "cd repo && cat docs/plan.md"}, "t7")),
]


class TokenReportTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rite-tokens-")
        self.dir = Path(self._tmp.name)
        (self.dir / "session.jsonl").write_text(
            "\n".join(json.dumps(e) for e in TRANSCRIPT), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def measure(self) -> dict:
        return tr.summarize(tr.collect(self.dir, None))

    def test_groups_by_command_and_counts_turns_once_per_message(self):
        data = self.measure()
        self.assertEqual(sorted(data["commands"]), ["/rite:execute", "/rite:review"])
        execute = data["commands"]["/rite:execute"]
        self.assertEqual(execute["turns"], 5)  # m1 split in two entries counts once
        self.assertEqual(execute["billed"], 5 * 115)
        self.assertEqual(execute["cache_read"], 5 * 1000)

    def test_classification(self):
        tools = self.measure()["commands"]["/rite:execute"]["tools"]
        self.assertEqual(tools, {"rite:fragment": 1, "rite:cli": 1, "git": 1, "gate": 1,
                                 "edit": 1, "subagent": 1})
        # ceremony is what the rite costs around the work: its own prose plus its CLI
        self.assertEqual(self.measure()["commands"]["/rite:execute"]["ceremony"], 2)
        self.assertEqual(self.measure()["commands"]["/rite:review"]["tools"], {"read:shell": 1})

    def test_largest_results_name_their_tool_and_target(self):
        top = tr.largest_results(tr.collect(self.dir, None), 2)
        self.assertEqual(top[0]["bytes"], 9000)
        self.assertEqual(top[0]["tool"], "Task")
        self.assertEqual(top[1]["tool"], "Read")

    def test_check_flags_a_regression_only_beyond_the_tolerance(self):
        data = self.measure()
        baseline = self.dir / "baseline.json"
        turns = data["commands"]["/rite:execute"]["turns"]
        billed = data["commands"]["/rite:execute"]["billed"]
        baseline.write_text(json.dumps({"commands": {"/rite:execute": {
            "billed": billed, "turns": turns}}}), encoding="utf-8")
        self.assertEqual(tr.check(data, baseline, 15.0)[0], 0)

        baseline.write_text(json.dumps({"commands": {"/rite:execute": {
            "billed": billed // 2, "turns": turns}}}), encoding="utf-8")
        failures, messages = tr.check(data, baseline, 15.0)
        self.assertEqual(failures, 1)
        self.assertTrue(any("WORSE" in m and "billed" in m for m in messages), messages)

        baseline.write_text(json.dumps({"commands": {"/rite:gone": {"billed": 1, "turns": 1}}}),
                            encoding="utf-8")
        self.assertTrue(any("MISS" in m for m in tr.check(data, baseline, 15.0)[1]))

    def test_cli_runs_and_reports_missing_data(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = tr.main(["--dir", str(self.dir), "--top", "1"])
        self.assertEqual(code, 0)
        self.assertIn("/rite:execute", out.getvalue())
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(tr.main(["--dir", empty]), 2)


class BaselineFilesTest(unittest.TestCase):
    def test_baselines_are_present_and_shaped(self):
        for name in ("node-minimal", "python-minimal"):
            path = Path(__file__).resolve().parent / "baselines" / f"{name}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["example"], name)
            self.assertTrue(data["version"] and data["measured_on"])
            self.assertIn("/rite:execute", data["commands"])
            for command in data["commands"].values():
                self.assertTrue({"billed", "turns", "ceremony", "n"} <= set(command))


if __name__ == "__main__":
    unittest.main()
