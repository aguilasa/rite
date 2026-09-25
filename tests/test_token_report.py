"""The token measurement itself: grouping, classification and the baseline check."""

import io
import json
import os
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
        self.assertEqual(sorted(data["groups"]), ["/rite:execute", "/rite:review"])
        execute = data["groups"]["/rite:execute"]
        self.assertEqual(execute["turns"], 5)  # m1 split in two entries counts once
        self.assertEqual(execute["billed"], 5 * 115)
        self.assertEqual(execute["cache_read"], 5 * 1000)

    def test_four_counts_and_effective_at_the_printed_weight(self):
        execute = self.measure()["groups"]["/rite:execute"]
        self.assertEqual({k: execute[k] for k in ("input", "cache_write", "cache_read", "output")},
                         {"input": 50, "cache_write": 500, "cache_read": 5000, "output": 25})
        self.assertEqual(execute["effective"], 5 * 115 + 0.1 * 5000)
        heavy = tr.summarize(tr.collect(self.dir, None), weight=1.0)
        self.assertEqual(heavy["cache_weight"], 1.0)
        self.assertEqual(heavy["groups"]["/rite:execute"]["effective"], 5 * 115 + 5000)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(tr.main(["--dir", str(self.dir), "--cache-weight", "0.25"]), 0)
        self.assertIn("billed + 0.25 × cache read", out.getvalue())
        self.assertIn("not a price", out.getvalue())

    def test_classification(self):
        tools = self.measure()["groups"]["/rite:execute"]["tools"]
        self.assertEqual(tools, {"rite:fragment": 1, "rite:cli": 1, "git": 1, "gate": 1,
                                 "edit": 1, "subagent": 1})
        # ceremony is what the rite spends around the work: its own prose plus its CLI
        self.assertEqual(self.measure()["groups"]["/rite:execute"]["ceremony"], 2)
        self.assertEqual(self.measure()["groups"]["/rite:review"]["tools"], {"read:shell": 1})

    def test_largest_results_name_their_tool_and_target(self):
        top = tr.largest_results(tr.collect(self.dir, None), 2)
        self.assertEqual(top[0]["bytes"], 9000)
        self.assertEqual(top[0]["tool"], "Task")
        self.assertEqual(top[1]["tool"], "Read")

    def test_check_flags_a_regression_only_beyond_the_tolerance(self):
        data = self.measure()
        baseline = self.dir / "baseline.json"
        turns = data["groups"]["/rite:execute"]["turns"]
        billed = data["groups"]["/rite:execute"]["billed"]
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
            self.assertEqual(tr.main(["--dir", str(Path(empty) / "no-such-run")]), 2)


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

    def measure(self) -> dict:
        return tr.summarize(tr.collect(self.dir, None))

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
        c = self.measure()["groups"]["/rite:fix-all"]
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
        c = self.measure()["groups"]["/rite:review"]
        self.assertEqual(c["billed"], 2 * 115)  # sidechain turns are not the main thread's
        self.assertEqual(c["agent"]["billed"], 2 * 221)
        self.assertEqual(list(c["agent"]["by_type"]), ["rite:rite-reviewer"])

    def test_an_agent_without_a_trace_is_unknown_not_zero(self):
        write_jsonl(self.dir / "s3.jsonl", [
            user("<command-name>/rite:review</command-name>"),
            agent_call("m1", "call-x", "rite:rite-reviewer"),
            result("call-x", "PASS"),
        ])
        c = self.measure()["groups"]["/rite:review"]
        self.assertEqual(c["agents"], 1)
        self.assertEqual(c["agent"], "unknown")
        self.assertIn("unknown", tr.render(self.measure(), []))

    def test_no_agent_means_a_measured_zero(self):
        write_jsonl(self.dir / "s4.jsonl", TRANSCRIPT[:2])
        c = self.measure()["groups"]["/rite:execute"]
        self.assertEqual((c["agents"], c["agent"]["billed"]), (0, 0))

    def test_check_compares_agents_only_when_both_sides_have_them(self):
        self.fix_all_session()
        data = self.measure()
        c = data["groups"]["/rite:fix-all"]
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

    def test_tokens_never_money(self):
        self.fix_all_session()
        self.assertEqual(set(self.measure()), {"invocations", "by", "statistic", "cache_weight", "groups", "totals"})
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(tr.main(["--dir", str(self.dir)]), 0)
        self.assertNotIn("$", out.getvalue())


def at(entry: dict, when: str, session: str, cwd: str, **fields) -> dict:
    return {**entry, "timestamp": when, "sessionId": session, "cwd": cwd, **fields}


HUMAN = {"origin": {"kind": "human"}}


class GeneralReportTest(unittest.TestCase):
    """All of Claude Code's usage, not only the rite: plain prompts, other plugins, any axis."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rite-usage-")
        self.dir = Path(self._tmp.name)
        write_jsonl(self.dir / "proj-a" / "s1.jsonl", [
            at(user("hello"), "2026-09-20T10:00:00Z", "s1", "/work/a", **HUMAN),
            at(assistant("n1", usage=USAGE), "2026-09-20T10:00:05Z", "s1", "/work/a"),
            # the harness speaking is not a prompt: the invocation goes on
            at(user("<task-notification>done</task-notification>"), "2026-09-20T10:01:00Z", "s1", "/work/a",
               origin={"kind": "task-notification"}),
            at(assistant("n2", usage=USAGE), "2026-09-20T10:01:05Z", "s1", "/work/a"),
            at(user("<command-name>/other:thing</command-name>"), "2026-09-20T11:00:00Z", "s1", "/work/a"),
            at(assistant("n3", usage=USAGE), "2026-09-20T11:00:05Z", "s1", "/work/a"),
        ])
        write_jsonl(self.dir / "proj-b" / "s2.jsonl", [
            at(user("<command-name>/rite:fix-all</command-name>"), "2026-09-21T09:00:00Z", "s2", "/work/b"),
            at(user("the command's own prose"), "2026-09-21T09:00:00Z", "s2", "/work/b", isMeta=True),
            at(agent_call("m1", "call-a", "rite:rite-reproducer"), "2026-09-21T09:00:05Z", "s2", "/work/b"),
            at(agent_result("call-a", "aaa"), "2026-09-21T09:01:00Z", "s2", "/work/b"),
            at(assistant("m2", usage=USAGE), "2026-09-21T09:01:05Z", "s2", "/work/b"),
            # 23:30 at UTC-3 is already the next day in UTC
            at(user("thanks"), "2026-09-21T23:30:00-03:00", "s2", "/work/b", **HUMAN),
            at(assistant("m3", usage=USAGE), "2026-09-21T23:30:05-03:00", "s2", "/work/b"),
        ])
        subagents = self.dir / "proj-b" / "s2" / "subagents"
        write_jsonl(subagents / "agent-aaa.jsonl", [
            sidechain(assistant("a1", usage=AGENT_USAGE), agentId="aaa")])
        (subagents / "agent-aaa.meta.json").write_text(json.dumps(
            {"agentType": "rite:rite-reproducer", "toolUseId": "call-a"}), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def measure(self, by: str) -> dict:
        return tr.summarize(tr.collect(self.dir, None), by=by)

    def run_cli(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = tr.main(["--dir", str(self.dir), *args])
        return code, out.getvalue()

    def test_prompts_and_other_plugins_are_rows(self):
        data = self.measure("command")
        self.assertEqual(sorted(data["groups"]), ["(no command)", "/other:thing", "/rite:fix-all"])
        self.assertEqual(data["groups"]["(no command)"]["n"], 2)
        self.assertEqual(data["groups"]["(no command)"]["turns"], 1)  # median of 2 and 1
        # the isMeta expansion does not cut the command; the later prompt does
        self.assertEqual(data["groups"]["/rite:fix-all"]["turns"], 2)
        self.assertEqual(data["statistic"], "median")

    def test_every_axis(self):
        self.assertEqual(list(self.measure("session")["groups"]), ["s1", "s2"])
        self.assertEqual(self.measure("session")["groups"]["s1"]["turns"], 3)  # a total, not a median
        self.assertEqual(list(self.measure("day")["groups"]), ["2026-09-20", "2026-09-21", "2026-09-22"])
        self.assertEqual(sorted(self.measure("project")["groups"]), ["/work/a", "/work/b"])
        agents = self.measure("agent")["groups"]
        self.assertEqual(list(agents), ["(main thread)", "rite:rite-reproducer"])
        self.assertEqual((agents["(main thread)"]["turns"], agents["rite:rite-reproducer"]["billed"]),
                         (6, 221))

    def test_totals_say_where_the_tokens_went(self):
        totals = self.measure("command")["totals"]
        self.assertEqual((totals["invocations"], totals["main"]["turns"], totals["agent"]["turns"]), (4, 6, 1))
        main_effective, agent_effective = 6 * 115 + 0.1 * 6000, 221 + 0.1 * 3000
        self.assertEqual(totals["effective"], int(main_effective + agent_effective))
        self.assertAlmostEqual(totals["agent_share"], agent_effective / (main_effective + agent_effective),
                               places=3)
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("Totals", out)

    def test_window_cuts_by_utc_day(self):
        code, out = self.run_cli("--since", "2026-09-21", "--until", "2026-09-21", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual((data["invocations"], list(data["groups"])), (1, ["/rite:fix-all"]))
        self.assertEqual(data["window"]["since"], "2026-09-21")
        self.assertEqual(self.run_cli("--since", "2027-01-01")[0], 2)

    def test_markdown_is_deterministic(self):
        first, second = self.dir / "a.md", self.dir / "b.md"
        self.assertEqual(self.run_cli("--by", "day", "--top", "2", "--markdown", str(first))[0], 0)
        self.assertEqual(self.run_cli("--by", "day", "--top", "2", "--markdown", str(second))[0], 0)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        text = first.read_text(encoding="utf-8")
        self.assertIn("| day |", text)
        self.assertIn("## Totals", text)
        self.assertNotIn("REPRODUCED", text)  # sizes and targets, never the text of a result

    def test_a_baseline_is_per_command(self):
        self.assertEqual(self.run_cli("--by", "day", "--check", str(self.dir / "none.json"))[0], 2)


def skill(msg_id: str, tid: str, name: str) -> dict:
    return assistant(msg_id, usage=USAGE, tool=("Skill", {"skill": name, "args": "looks"}, tid))


def launched(tid: str, name: str) -> list[dict]:
    """What follows a Skill call: its result, then the command's prose injected by the harness."""
    return [result(tid, f"Launching skill: {name}"),
            {**user(f"# /{name} — the command's own prose"), "isMeta": True}]


class SkillInvocationTest(unittest.TestCase):
    """A command entered through the Skill tool is an invocation too, under the same name."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rite-skill-")
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def measure(self) -> dict:
        return tr.summarize(tr.collect(self.dir, None))

    def test_a_skill_call_alone_opens_the_command(self):
        write_jsonl(self.dir / "s.jsonl", [
            user("run /rite:fix-all on looks"),
            assistant("m1", usage=USAGE, tool=("Bash", {"command": "ls"}, "t1")),
            result("t1", "ok"),
            skill("m2", "t2", "rite:fix-all"),
            *launched("t2", "rite:fix-all"),
            assistant("m3", usage=USAGE),
            assistant("m4", usage=USAGE),
        ])
        data = self.measure()
        self.assertEqual(sorted(data["groups"]), ["(no command)", "/rite:fix-all"])
        self.assertEqual(data["groups"]["/rite:fix-all"]["turns"], 3)
        self.assertEqual(data["groups"]["(no command)"]["turns"], 1)

    def test_a_typed_command_and_its_skill_call_are_one_invocation(self):
        write_jsonl(self.dir / "s.jsonl", [
            user("<command-name>/rite:fix-all</command-name>"),
            skill("m1", "t1", "rite:fix-all"),
            *launched("t1", "rite:fix-all"),
            assistant("m2", usage=USAGE),
        ])
        data = self.measure()
        self.assertEqual(data["invocations"], 1)
        self.assertEqual(list(data["groups"]), ["/rite:fix-all"])
        self.assertEqual(data["groups"]["/rite:fix-all"]["turns"], 2)
        self.assertEqual(data["groups"]["/rite:fix-all"]["billed"], 2 * 115)

    def test_a_skill_of_another_name_opens_a_new_invocation(self):
        write_jsonl(self.dir / "s.jsonl", [
            user("<command-name>/rite:execute</command-name>"),
            assistant("m1", usage=USAGE),
            skill("m2", "t2", "caveman:caveman"),
            *launched("t2", "caveman:caveman"),
            assistant("m3", usage=USAGE),
        ])
        data = self.measure()
        self.assertEqual(data["invocations"], 2)
        self.assertEqual(data["groups"]["/rite:execute"]["turns"], 1)
        self.assertEqual(data["groups"]["/caveman:caveman"]["turns"], 2)

    def test_turns_before_the_skill_call_stay_without_command(self):
        # the Skill call's message arrives split: its text entry carries the usage first
        write_jsonl(self.dir / "s.jsonl", [
            user("read this plan and run it"),
            assistant("m1", usage=USAGE, tool=("Read", {"file_path": "plan.md"}, "t1")),
            result("t1", "x" * 10),
            assistant("m2", usage=USAGE),
            assistant("m3", usage=USAGE),
            skill("m3", "t3", "rite:fix-all"),
            *launched("t3", "rite:fix-all"),
            assistant("m4", usage=USAGE),
        ])
        groups = self.measure()["groups"]
        self.assertEqual((groups["(no command)"]["turns"], groups["(no command)"]["billed"]), (2, 2 * 115))
        self.assertEqual((groups["/rite:fix-all"]["turns"], groups["/rite:fix-all"]["billed"]), (2, 2 * 115))
        self.assertEqual(groups["(no command)"]["tools"], {"read:project": 1})

    def test_a_prompt_that_only_carried_the_skill_call_is_no_invocation(self):
        write_jsonl(self.dir / "s.jsonl", [
            user("run /rite:fix-all on looks"),
            assistant("m1", usage=USAGE),
            skill("m1", "t1", "rite:fix-all"),
            *launched("t1", "rite:fix-all"),
            assistant("m2", usage=USAGE),
        ])
        data = self.measure()
        self.assertEqual((data["invocations"], list(data["groups"])), (1, ["/rite:fix-all"]))
        self.assertEqual(data["groups"]["/rite:fix-all"]["turns"], 2)

    def test_a_subagent_belongs_to_the_skill_invocation(self):
        write_jsonl(self.dir / "s.jsonl", [
            user("fix them"),
            assistant("m1", usage=USAGE),
            skill("m2", "t2", "rite:fix-all"),
            *launched("t2", "rite:fix-all"),
            agent_call("m3", "call-w", "rite:rite-worker"),
            agent_result("call-w", "www"),
            assistant("m4", usage=USAGE),
        ])
        subagents = self.dir / "s" / "subagents"
        write_jsonl(subagents / "agent-www.jsonl", [
            sidechain(assistant("w1", usage=AGENT_USAGE), agentId="www"),
            sidechain(assistant("w2", usage=AGENT_USAGE), agentId="www"),
        ])
        (subagents / "agent-www.meta.json").write_text(json.dumps(
            {"agentType": "rite:rite-worker", "toolUseId": "call-w"}), encoding="utf-8")
        groups = self.measure()["groups"]
        fix_all = groups["/rite:fix-all"]
        self.assertEqual((fix_all["agents"], fix_all["agent"]["billed"]), (1, 2 * 221))
        self.assertEqual(groups["(no command)"]["agents"], 0)


class ScopeTest(unittest.TestCase):
    """A baseline is one run; a glob over many runs is history, and the check says so."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rite-scope-")
        self.dir = Path(self._tmp.name)
        for name, session, when in (("run-a", "sa", 1_000_000_000), ("run-b", "sb", 1_000_000_600)):
            path = self.dir / name / f"{session}.jsonl"
            write_jsonl(path, [at(entry, "2026-09-24T10:00:00Z", session, f"/tmp/{name}")
                               for entry in TRANSCRIPT])
            os.utime(path, (when, when))
        # run-a has one more session: the older run is the bigger one, so "latest" is not "largest"
        extra = self.dir / "run-a" / "sa2.jsonl"
        write_jsonl(extra, [at(entry, "2026-09-24T09:00:00Z", "sa2", "/tmp/run-a") for entry in TRANSCRIPT])
        os.utime(extra, (1_000_000_000, 1_000_000_000))

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = tr.main(["--dir", str(self.dir), *args])
        return code, out.getvalue()

    def baseline_of(self, run: str) -> Path:
        path = self.dir / f"{run}.baseline.json"
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(tr.main(["--dir", str(self.dir / run), "--write-baseline", str(path)]), 0)
        return path

    def test_a_glob_sums_every_run_it_matches(self):
        code, out = self.run_cli("--project", "*run-*", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["invocations"], 6)  # 2 per session, 3 sessions
        self.assertEqual((data["window"]["sessions"], data["window"]["projects"]), (3, 2))

    def test_latest_measures_the_newest_run_only(self):
        code, out = self.run_cli("--project", "*run-*", "--latest", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["invocations"], 2)
        self.assertEqual((data["window"]["sessions"], data["window"]["projects"]), (1, 1))
        self.assertTrue(data["window"]["latest"])
        self.assertEqual({i.project for i in tr.collect(self.dir, "*run-*", latest=True)}, {"/tmp/run-b"})

    def test_check_over_more_runs_than_the_baseline_fails_on_scope_not_on_numbers(self):
        baseline = self.baseline_of("run-a")
        code, out = self.run_cli("--project", "*run-*", "--check", str(baseline))
        self.assertEqual(code, 3)
        check = out.split("check against", 1)[1]
        self.assertIn("SCOPE", check)
        self.assertIn("6 invocation(s) in 3 session(s) across 2 project folder(s)", check)
        self.assertIn("the baseline 4 in 2 across 1", check)
        self.assertNotIn("WORSE", check)
        self.assertNotIn("ok   ", check)

    def test_check_in_the_scope_of_the_baseline_passes(self):
        baseline = self.baseline_of("run-b")
        code, out = self.run_cli("--project", "*run-*", "--latest", "--check", str(baseline))
        self.assertEqual(code, 0, out)
        self.assertNotIn("SCOPE", out.split("check against", 1)[1])

    def test_a_written_baseline_carries_its_scope(self):
        data = json.loads(self.baseline_of("run-a").read_text(encoding="utf-8"))
        self.assertEqual(data["invocations"], 4)
        self.assertEqual({k: data["window"][k] for k in ("sessions", "projects", "latest")},
                         {"sessions": 2, "projects": 1, "latest": False})
        self.assertIn("project", data["window"])

    def test_a_baseline_without_scope_is_named_not_trusted_blindly(self):
        baseline = self.dir / "old.json"
        baseline.write_text(json.dumps({"commands": {"/rite:execute": {"billed": 10 ** 6, "turns": 99}}}),
                            encoding="utf-8")
        code, out = self.run_cli("--project", "*run-*", "--check", str(baseline))
        self.assertEqual(code, 0)
        self.assertIn("SCOPE? baseline records no scope", out)


def fix_all_run(folder: Path, session: str, day: str, agent_turns: list[dict]) -> None:
    """One /rite:fix-all: a reproducer per entry of ``agent_turns`` (its usage per turn, 10 turns
    each), started one main turn apart, then two more main turns. Main turns cost USAGE."""
    when = f"{day}T10:00:00Z"
    entries = [at(user("<command-name>/rite:fix-all</command-name>"), when, session, str(folder))]
    for i, _ in enumerate(agent_turns):
        entries += [at(agent_call(f"{session}-m{i}", f"{session}-c{i}", "rite:rite-reproducer"),
                       when, session, str(folder)),
                    at(agent_result(f"{session}-c{i}", f"{session}-a{i}"), when, session, str(folder))]
    entries += [at(assistant(f"{session}-end{k}", usage=USAGE), when, session, str(folder)) for k in (1, 2)]
    write_jsonl(folder / f"{session}.jsonl", entries)
    for i, usage in enumerate(agent_turns):
        agent_id = f"{session}-a{i}"
        write_jsonl(folder / session / "subagents" / f"agent-{agent_id}.jsonl",
                    [sidechain(assistant(f"{agent_id}-t{t}", usage=usage), agentId=agent_id) for t in range(10)])
        (folder / session / "subagents" / f"agent-{agent_id}.meta.json").write_text(json.dumps(
            {"agentType": "rite:rite-reproducer", "toolUseId": f"{session}-c{i}"}), encoding="utf-8")


CHEAP = {"output_tokens": 15}  # 150 billed over 10 turns, no cache read


class SuggestLimitsTest(unittest.TestCase):
    """The inline-triage limit is measured from the project's own history, and says from what."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rite-limits-")
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = tr.main(["--dir", str(self.dir), "--suggest-limits", *args])
        return code, out.getvalue()

    def test_the_limit_is_the_formula_over_measured_inputs(self):
        fix_all_run(self.dir / "repo", "s1", "2026-09-20", [AGENT_USAGE] * 3)
        code, out = self.run_cli("--json")
        self.assertEqual(code, 0, out)
        data = json.loads(out)
        # by hand: a reproducer is 10 turns of 221 billed + 3,000 cache read -> 2,210 + 0.1 * 30,000 = 5,210;
        # a main turn is 115 + 0.1 * 1,000 = 215; the fix-all has 5 turns, the results came back after
        # turns 1, 2 and 3, so 4, 3 and 2 turns carried them: median 3, and 1 + 0.1 * 3 = 1.3
        self.assertEqual(data["inputs"]["agent"], {"billed": 2210, "cache_read": 30000, "effective": 5210})
        self.assertEqual(data["inputs"]["main_turn"], {"billed": 115, "cache_read": 1000, "effective": 215})
        self.assertEqual(data["inputs"]["turns_after"], 3)
        # N=1: (5,210 - 215) / 1.3 * 4 / 1024 = 15.01; N=2: (5,210 - 107.5) / 1.3 * 4 / 1024 = 15.33;
        # N=4: (5,210 - 53.75) / 1.3 * 4 / 1024 = 15.49
        self.assertEqual([(r["n"], r["kb"]) for r in data["limits"]], [(1, 15.0), (2, 15.3), (4, 15.5)])
        self.assertEqual(data["recommended"], {"n": 1, "inline_triage_max_output_kb": 15})
        self.assertEqual((data["invocations"], data["agents"], data["unmeasured"]), (1, 3, 0))
        self.assertEqual(data["cache_weight"], 0.1)
        self.assertEqual(len(data["formula"]), 2)

    def test_the_text_names_inputs_limits_recommendation_and_formula(self):
        fix_all_run(self.dir / "repo", "s1", "2026-09-20", [AGENT_USAGE] * 3)
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)
        self.assertIn("median of 3 run(s)", out)
        self.assertIn("N = 4: 15.5 KB", out)
        self.assertIn("inline_triage_max_output_kb = 15 (N = 1", out)
        self.assertIn("formula: budget = agent_effective - main_turn_effective / N", out)
        self.assertIn("w = 0.1", out)

    def test_a_reproducer_cheaper_than_a_turn_moves_the_recommendation_up(self):
        fix_all_run(self.dir / "repo", "s1", "2026-09-20", [CHEAP] * 3)
        code, out = self.run_cli("--json")
        self.assertEqual(code, 0, out)
        data = json.loads(out)
        # 150 < 215: at N=1 the agent always wins; N=2: (150 - 107.5) / 1.3 * 4 / 1024 = 0.13
        self.assertEqual([(r["n"], r["kb"], r["agent_always"]) for r in data["limits"]],
                         [(1, None, True), (2, 0.1, False), (4, 0.3, False)])
        self.assertEqual(data["recommended"], {"n": 2, "inline_triage_max_output_kb": 1})
        self.assertIn("N = 1: agent always wins", self.run_cli()[1])

    def test_a_small_sample_suggests_nothing_and_says_what_is_missing(self):
        fix_all_run(self.dir / "repo", "s1", "2026-09-20", [AGENT_USAGE] * 2)
        code, out = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("insufficient data: 2 measured rite:rite-reproducer run(s), 3 needed", out)
        self.assertNotIn("recommended for", out)
        code, out = self.run_cli("--json")
        self.assertEqual(code, 2)
        self.assertNotIn("limits", json.loads(out))

    def test_no_fix_all_names_the_command(self):
        write_jsonl(self.dir / "repo" / "s1.jsonl", TRANSCRIPT)
        code, out = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("no /rite:fix-all invocation in the window", out)

    def test_the_window_decides_the_inputs_and_is_declared(self):
        dear, cheap = self.dir / "run-a", self.dir / "run-b"
        fix_all_run(dear, "sa", "2026-09-20", [AGENT_USAGE] * 3)
        fix_all_run(cheap, "sb", "2026-09-22", [CHEAP] * 3)
        for path in (dear / "sa.jsonl", *dear.rglob("*.jsonl")):
            os.utime(path, (1_000_000_000, 1_000_000_000))
        for args, agent_effective in ((("--project", "*run-a*"), 5210), (("--since", "2026-09-21"), 150),
                                      (("--latest",), 150)):
            code, out = self.run_cli(*args, "--json")
            self.assertEqual(code, 0, out)
            data = json.loads(out)
            self.assertEqual(data["inputs"]["agent"]["effective"], agent_effective, args)
            self.assertEqual((data["window"]["sessions"], data["window"]["projects"]), (1, 1), args)
        self.assertEqual(json.loads(self.run_cli("--project", "*run-a*", "--json")[1])["window"]["project"],
                         "*run-a*")
        self.assertIn("(project *run-a*, 1 session(s) across 1 project folder(s))",
                      self.run_cli("--project", "*run-a*")[1])
        self.assertIn("latest run", self.run_cli("--latest")[1])

    def test_it_is_no_baseline(self):
        fix_all_run(self.dir / "repo", "s1", "2026-09-20", [AGENT_USAGE] * 3)
        self.assertEqual(self.run_cli("--check", str(self.dir / "b.json"))[0], 2)


BASELINES = [(example, script) for example in ("node-minimal", "python-minimal")
             for script in ("loop", "lifecycle")]


class BaselineFilesTest(unittest.TestCase):
    def test_baselines_are_present_and_shaped(self):
        for example, script in BASELINES:
            path = Path(__file__).resolve().parent / "baselines" / f"{example}.{script}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["example"], example)
            self.assertTrue(data["version"] and data["measured_on"])
            self.assertEqual(data["window"]["projects"], 1, f"{path.name} is one run")
            groups = tr.baseline_groups(data)
            self.assertIn("/rite:execute" if script == "loop" else "/rite:execute-batch", groups)
            for command in groups.values():
                self.assertTrue({"billed", "turns", "ceremony", "n"} <= set(command))


if __name__ == "__main__":
    unittest.main()
