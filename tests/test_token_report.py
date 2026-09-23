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


AGENT_USAGE = {"input_tokens": 1, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 3000,
               "output_tokens": 20}
# 20 + 201 is billed per agent turn; 115 per main turn


def agent_call(msg_id: str, tid: str, kind: str, uuid: str = "") -> dict:
    entry = assistant(msg_id, usage=USAGE, tool=("Agent", {"subagent_type": kind}, tid))
    if uuid:
        entry["uuid"] = uuid
    return entry


def agent_result(tid: str, agent_id: str) -> dict:
    entry = result(tid, "REPRODUCED")
    entry["toolUseResult"] = {"agentId": agent_id, "usage": {"output_tokens": 999}}
    return entry


def sidechain(entry: dict, **fields) -> dict:
    return {**entry, "isSidechain": True, **fields}


def write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")


class AgentAttributionTest(unittest.TestCase):
    """The subagent's tokens belong to the invocation that started it, reported apart."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rite-agents-")
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def measure(self, prices=None) -> dict:
        return tr.summarize(tr.collect(self.dir, None), prices)

    def fix_all_session(self) -> None:
        write_jsonl(self.dir / "s1.jsonl", [
            user("<command-name>/rite:fix-all</command-name>"),
            agent_call("m1", "call-a", "rite:rite-reproducer"),
            agent_result("call-a", "aaa"),
            agent_call("m2", "call-b", "rite:rite-worker"),
            agent_result("call-b", "bbb"),
            assistant("m3", usage=USAGE),
        ])
        subagents = self.dir / "s1" / "subagents"
        write_jsonl(subagents / "agent-aaa.jsonl", [
            sidechain(user("reproduce FIX-1"), agentId="aaa"),
            sidechain(assistant("a1", usage=AGENT_USAGE,
                                tool=("Bash", {"command": "node -e x"}, "sh1")), agentId="aaa"),
            sidechain(result("sh1", "HELLO-WORLD"), agentId="aaa"),
            sidechain(assistant("a1", usage=AGENT_USAGE), agentId="aaa"),  # same message, split
            sidechain(assistant("a2", usage=AGENT_USAGE), agentId="aaa"),
        ])
        (subagents / "agent-aaa.meta.json").write_text(json.dumps(
            {"agentType": "rite:rite-reproducer", "toolUseId": "call-a"}), encoding="utf-8")
        # no meta file: linked through the agentId the main thread's result carries
        write_jsonl(subagents / "agent-bbb.jsonl", [
            sidechain(assistant("b1", usage=AGENT_USAGE), agentId="bbb"),
        ])

    def test_subagent_files_are_attributed_to_their_call(self):
        self.fix_all_session()
        c = self.measure()["commands"]["/rite:fix-all"]
        self.assertEqual(c["billed"], 3 * 115)  # the main thread only, as before
        self.assertEqual(c["agents"], 2)
        self.assertEqual(c["agent"]["billed"], 3 * 221)
        self.assertEqual(c["agent"]["cache_read"], 3 * 3000)
        self.assertEqual(c["agent"]["turns"], 3)
        reproducer = c["agent"]["by_type"]["rite:rite-reproducer"]
        self.assertEqual((reproducer["n"], reproducer["billed"], reproducer["turns"]), (1, 442, 2))
        self.assertEqual(reproducer["shell_bytes"], len("HELLO-WORLD"))
        self.assertEqual(reproducer["main_turns_after"], 2)  # m2 and m3 carried its result
        self.assertEqual(c["agent"]["by_type"]["rite:rite-worker"]["billed"], 221)

    def test_inline_sidechain_follows_parent_uuid(self):
        write_jsonl(self.dir / "s2.jsonl", [
            user("<command-name>/rite:review</command-name>"),
            agent_call("m1", "call-r", "rite:rite-reviewer", uuid="u-call"),
            sidechain(user("review it"), uuid="u1", parentUuid="u-call"),
            sidechain(assistant("r1", usage=AGENT_USAGE), uuid="u2", parentUuid="u1"),
            sidechain(assistant("r2", usage=AGENT_USAGE), uuid="u3", parentUuid="u2"),
            result("call-r", "PASS"),
            assistant("m2", usage=USAGE),
        ])
        c = self.measure()["commands"]["/rite:review"]
        self.assertEqual(c["billed"], 2 * 115)  # sidechain turns are not the main thread's
        self.assertEqual(c["agent"]["billed"], 2 * 221)
        self.assertEqual(list(c["agent"]["by_type"]), ["rite:rite-reviewer"])

    def test_an_agent_without_a_trace_is_unknown_not_zero(self):
        write_jsonl(self.dir / "s3.jsonl", [
            user("<command-name>/rite:review</command-name>"),
            agent_call("m1", "call-x", "rite:rite-reviewer"),
            result("call-x", "PASS"),
        ])
        c = self.measure()["commands"]["/rite:review"]
        self.assertEqual(c["agents"], 1)
        self.assertEqual(c["agent"], "unknown")
        self.assertIn("unknown", tr.render(self.measure(), []))

    def test_no_agent_means_a_measured_zero(self):
        write_jsonl(self.dir / "s4.jsonl", TRANSCRIPT[:2])
        c = self.measure()["commands"]["/rite:execute"]
        self.assertEqual((c["agents"], c["agent"]["billed"]), (0, 0))

    def test_check_compares_agents_only_when_both_sides_have_them(self):
        self.fix_all_session()
        data = self.measure()
        c = data["commands"]["/rite:fix-all"]
        baseline = self.dir / "baseline.json"
        # an old baseline, without agent fields, still passes
        baseline.write_text(json.dumps({"commands": {"/rite:fix-all": {
            "billed": c["billed"], "turns": c["turns"]}}}), encoding="utf-8")
        self.assertEqual(tr.check(data, baseline, 15.0)[0], 0)
        # one more agent than the baseline fails, whatever the tolerance
        baseline.write_text(json.dumps({"commands": {"/rite:fix-all": {
            "billed": c["billed"], "turns": c["turns"], "agents": 1,
            "agent": {"billed": c["agent"]["billed"]}}}}), encoding="utf-8")
        failures, messages = tr.check(data, baseline, 50.0)
        self.assertEqual(failures, 1)
        self.assertTrue(any("WORSE" in m and "agents" in m for m in messages), messages)
        # a costlier agent side fails beyond the tolerance
        baseline.write_text(json.dumps({"commands": {"/rite:fix-all": {
            "billed": c["billed"], "turns": c["turns"], "agents": 2,
            "agent": {"billed": c["agent"]["billed"] // 2}}}}), encoding="utf-8")
        failures, messages = tr.check(data, baseline, 15.0)
        self.assertEqual(failures, 1)
        self.assertTrue(any("WORSE" in m and "agent.billed" in m for m in messages), messages)

    def test_check_fails_when_the_agent_side_went_missing(self):
        write_jsonl(self.dir / "s3.jsonl", [
            user("<command-name>/rite:review</command-name>"),
            agent_call("m1", "call-x", "rite:rite-reviewer"),
            result("call-x", "PASS"),
        ])
        data = self.measure()
        baseline = self.dir / "baseline.json"
        baseline.write_text(json.dumps({"commands": {"/rite:review": {
            "billed": 115, "turns": 1, "agents": 1, "agent": {"billed": 100}}}}), encoding="utf-8")
        failures, messages = tr.check(data, baseline, 15.0)
        self.assertEqual(failures, 1)
        self.assertTrue(any(m.startswith("UNKN") for m in messages), messages)

    def test_dollars_only_with_a_complete_price_table(self):
        self.fix_all_session()
        self.assertNotIn("usd", self.measure()["commands"]["/rite:fix-all"])
        prices_file = self.dir / "prices.toml"
        prices_file.write_text("[cost]\ninput = 3.0\noutput = 15.0\n", encoding="utf-8")
        self.assertIsNone(tr.load_prices(prices_file))  # partial: omitted, never guessed
        prices_file.write_text("[cost]\ninput = 3.0\noutput = 15.0\ncache_write = 3.75\n"
                               "cache_read = 0.3\n", encoding="utf-8")
        prices = tr.load_prices(prices_file)
        data = self.measure(prices)
        c = data["commands"]["/rite:fix-all"]
        main = 3 * (10 * 3.0 + 100 * 3.75 + 1000 * 0.3 + 5 * 15.0) / 1e6
        agent = 3 * (1 * 3.0 + 200 * 3.75 + 3000 * 0.3 + 20 * 15.0) / 1e6
        self.assertAlmostEqual(c["usd"], round(main, 4))
        self.assertAlmostEqual(c["agent"]["usd"], round(agent, 4))
        self.assertEqual(data["prices"], prices)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(tr.main(["--dir", str(self.dir), "--prices", str(prices_file)]), 0)
        self.assertIn("usd agent", out.getvalue())


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
