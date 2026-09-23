#!/usr/bin/env python3
"""The tokens one invocation of a command uses, measured from Claude Code transcripts.

Reads the JSONL transcripts Claude Code writes under ``~/.claude/projects`` and groups them by
invoked command (`/rite:execute`, …): every assistant message after a command belongs to it until
the next command. For each command it reports medians — billed tokens, cache reads, output, turns —
and the tool calls that produced them, classified (fragment reads, CLI calls, git, gates, edits,
subagents). Why medians: one long invocation must not decide the number a baseline is compared to.

A subagent's turns are billed too, but they are not in the main thread: Claude Code writes them to
``<session>/subagents/agent-<id>.jsonl`` (with a ``.meta.json`` naming the ``Agent`` call that
started it), or inline as ``isSidechain`` entries. Both are attributed to the invocation that made
the call and reported apart, as ``agent``. A call whose agent left no trace makes the command's agent
side ``"unknown"`` — a declared gap, never a silent zero.

Everything is counted in tokens, never in money. Only metrics are kept: sizes, tool names and
targets, never the text of a transcript.

    python tools/token_report.py --dir ~/.claude/projects --glob "*node-minimal*" --top 10
    python tools/token_report.py --glob "*rite-node-minimal-*" --check tests/baselines/node-minimal.json

Exit codes: 0 ok · 1 a checked command regressed beyond the tolerance · 2 nothing measured.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

COMMAND_RE = re.compile(r"<command-name>([^<]+)</command-name>")

# Bash commands that are the project's own gates rather than reading or bookkeeping.
GATE_RE = re.compile(r"\b(unittest|pytest|npm (run |)test|node --test|ctest|cmake|make|tox|"
                     r"cargo (test|build)|go test|mvn|gradle|ruff|eslint|flake8|mypy)\b")
# a shell line is a chain (`cd X && git ...`), so anchor on a segment start, not the line start
SEGMENT = r"(?:^|[;&|]\s*|&&\s*)"
READ_SHELL_RE = re.compile(SEGMENT + r"\s*(cat|sed|head|tail|grep|rg|ls|find|wc|awk|type)\b")
GIT_RE = re.compile(SEGMENT + r"\s*git\b|\bgit -C\b")
RITE_CLI_RE = re.compile(r"(rite\.py|bin/rite|\brite)[\"']?\s+(resolve-cycle|next|new-task|new-fix|"
                         r"commit-new|commit-refs|close|rebind|mark|mark-reviewed|mark-stale|sync|"
                         r"check|status|batch-plan|new-cycle|archive|publish|anchors|stats|relink|"
                         r"migrate|guard|begin|context|gates|sweep|finish|tokens|cost)\b")
# a plugin's own prose: the fragments and command files commands read at runtime
FRAGMENT_RE = re.compile(r"(plugins[\\/].*[\\/])?(shared|parts|commands|agents)[\\/][^\\/]+\.md$",
                         re.IGNORECASE)

CATEGORIES = ("rite:fragment", "rite:cli", "git", "read:project", "read:shell", "gate", "edit",
              "subagent", "other")
AGENT_TOOLS = ("Task", "Agent")
SHELL_TOOLS = ("Bash", "PowerShell")


def classify(tool: str, target: str) -> str:
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "edit"
    if tool in AGENT_TOOLS:
        return "subagent"
    if tool in ("Read", "Glob", "Grep"):
        return "rite:fragment" if FRAGMENT_RE.search(target or "") else "read:project"
    if tool in SHELL_TOOLS:
        cmd = target or ""
        if RITE_CLI_RE.search(cmd):
            return "rite:cli"
        if GIT_RE.search(cmd):
            return "git"
        if GATE_RE.search(cmd):
            return "gate"
        if READ_SHELL_RE.search(cmd):
            return "read:shell"
        return "other"
    return "other"


def target_of(tool: str, tool_input: dict) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("file_path", "path", "command", "pattern", "notebook_path", "skill",
                "subagent_type", "description"):
        if tool_input.get(key):
            return str(tool_input[key])
    return ""


class Usage:
    """Tokens of a run of assistant turns. ``billed`` is what is paid at the full input rate."""

    def __init__(self):
        self.input = self.cache_write = self.cache_read = self.output = 0
        self.turns = 0

    def add_usage(self, usage: dict) -> None:
        self.turns += 1
        self.input += usage.get("input_tokens", 0)
        self.cache_write += usage.get("cache_creation_input_tokens", 0)
        self.cache_read += usage.get("cache_read_input_tokens", 0)
        self.output += usage.get("output_tokens", 0)

    def merge(self, other: Usage) -> None:
        for key in ("input", "cache_write", "cache_read", "output", "turns"):
            setattr(self, key, getattr(self, key) + getattr(other, key))

    @property
    def billed(self) -> int:
        return self.input + self.cache_write + self.output


class AgentRun(Usage):
    """One subagent, started by an ``Agent``/``Task`` call of the main thread."""

    def __init__(self, tool_use_id: str = "", agent_type: str = ""):
        super().__init__()
        self.tool_use_id = tool_use_id
        self.agent_type = agent_type or "?"
        self.agent_id = ""
        self.measured = False
        self.shell_bytes = 0        # what its shell commands printed: the reproduction output
        self.result_turn = None     # main-thread turn count when its result came back
        self.main_turns_after = 0   # main-thread turns that carried its result afterwards

    def absorb(self, found: AgentRun, agent_type: str = "") -> None:
        self.merge(found)
        self.shell_bytes += found.shell_bytes
        self.measured = True
        if agent_type:
            self.agent_type = agent_type


class Invocation(Usage):
    def __init__(self, command: str, session: str):
        super().__init__()
        self.command = command
        self.session = session
        self.tools: dict[str, int] = {}
        self.results: list[tuple[int, str, str]] = []  # (bytes, tool, target)
        self.agents: list[AgentRun] = []

    def add_tool(self, category: str) -> None:
        self.tools[category] = self.tools.get(category, 0) + 1

    @property
    def ceremony(self) -> int:
        """Turns spent around the work: reading the plugin's own prose and calling its CLI."""
        return self.tools.get("rite:fragment", 0) + self.tools.get("rite:cli", 0)

    @property
    def agent_unknown(self) -> bool:
        return any(not run.measured for run in self.agents)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content or "")


def _entries(path: Path):
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _message_id(entry: dict) -> str:
    message = entry.get("message") or {}
    return str(message.get("id") or entry.get("requestId") or entry.get("uuid"))


class Sidechains:
    """Inline agent turns, set aside until the call that started them is known."""

    def __init__(self):
        self.by_agent: dict[str, AgentRun] = {}  # agentId -> tokens
        self.by_call: dict[str, AgentRun] = {}   # tool_use id reached through parentUuid -> tokens
        self.seen: set[str] = set()


def _count_agent_entry(entry: dict, run: AgentRun, seen: set[str], shell_calls: set[str]) -> None:
    message = entry.get("message") or {}
    if entry.get("type") == "assistant":
        usage = message.get("usage") or {}
        message_id = _message_id(entry)
        if usage and message_id not in seen:
            seen.add(message_id)
            run.add_usage(usage)
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" \
                    and block.get("name") in SHELL_TOOLS:
                shell_calls.add(str(block.get("id")))
    elif entry.get("type") == "user" and isinstance(message.get("content"), list):
        for block in message["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_result" \
                    and str(block.get("tool_use_id")) in shell_calls:
                run.shell_bytes += len(_text(block.get("content")))


def read_file(path: Path, sidechains: Sidechains | None = None) -> list[Invocation]:
    """Every invocation in one transcript, in order. Sidechain entries are set aside, not counted."""
    out: list[Invocation] = []
    current: Invocation | None = None
    seen_messages: set[str] = set()
    tool_calls: dict[str, tuple[str, str]] = {}  # tool_use id -> (tool, target)
    runs: dict[str, AgentRun] = {}               # tool_use id -> agent run
    owner: dict[str, AgentRun] = {}              # entry uuid -> the run its chain hangs from
    open_runs: list[AgentRun] = []               # calls whose result has not come back yet
    shell_calls: set[str] = set()
    for entry in _entries(path):
        kind = entry.get("type")
        message = entry.get("message") or {}
        if entry.get("isSidechain"):
            if sidechains is not None:
                _set_aside(entry, owner, open_runs, sidechains, shell_calls)
            continue
        if kind == "user":
            content = message.get("content")
            hit = COMMAND_RE.search(_text(content)) if not isinstance(content, list) else None
            if isinstance(content, list):
                hit = COMMAND_RE.search("".join(b.get("text", "") for b in content
                                                if isinstance(b, dict) and b.get("type") == "text"))
            if hit:
                current = Invocation(hit.group(1).strip(), str(entry.get("sessionId") or path.stem))
                out.append(current)
            elif isinstance(content, list) and current is not None:
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_use_id = str(block.get("tool_use_id"))
                        tool, target = tool_calls.get(tool_use_id, ("?", ""))
                        current.results.append((len(_text(block.get("content"))), tool, target))
                        run = runs.get(tool_use_id)
                        if run is not None:
                            run.result_turn = current.turns
                            if run in open_runs:
                                open_runs.remove(run)
                            meta = entry.get("toolUseResult")
                            if isinstance(meta, dict) and meta.get("agentId"):
                                run.agent_id = str(meta["agentId"])
        elif kind == "assistant" and current is not None:
            usage = message.get("usage") or {}
            message_id = _message_id(entry)
            if usage and message_id not in seen_messages:
                seen_messages.add(message_id)
                current.add_usage(usage)
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool = str(block.get("name") or "?")
                    tool_input = block.get("input") or {}
                    target = target_of(tool, tool_input)
                    tool_calls[str(block.get("id"))] = (tool, target)
                    current.add_tool(classify(tool, target))
                    if tool in AGENT_TOOLS:
                        subagent_type = tool_input.get("subagent_type") if isinstance(tool_input, dict) else ""
                        run = AgentRun(str(block.get("id")), str(subagent_type or ""))
                        runs[run.tool_use_id] = run
                        current.agents.append(run)
                        open_runs.append(run)
                        if entry.get("uuid"):
                            owner[str(entry["uuid"])] = run
    for inv in out:
        for run in inv.agents:
            if run.result_turn is not None:
                run.main_turns_after = inv.turns - run.result_turn
    return out


def _set_aside(entry: dict, owner: dict[str, AgentRun], open_runs: list[AgentRun],
               sidechains: Sidechains, shell_calls: set[str]) -> None:
    """An inline sidechain entry: keyed by its agentId, else by the chain it hangs from, else by
    the window of the one call still open."""
    uuid, parent = str(entry.get("uuid") or ""), str(entry.get("parentUuid") or "")
    run = owner.get(parent)
    if run is None and len(open_runs) == 1:
        run = open_runs[0]
    if run is not None and uuid:
        owner[uuid] = run
    if entry.get("agentId"):
        bucket = sidechains.by_agent.setdefault(str(entry["agentId"]), AgentRun())
    elif run is not None:
        bucket = sidechains.by_call.setdefault(run.tool_use_id, AgentRun(run.tool_use_id))
    else:
        return
    _count_agent_entry(entry, bucket, sidechains.seen, shell_calls)


def read_agent_file(path: Path) -> tuple[AgentRun, dict]:
    """One ``subagents/agent-<id>.jsonl``: its tokens, and its ``.meta.json`` when there is one."""
    run = AgentRun()
    run.agent_id = path.stem.removeprefix("agent-")
    seen: set[str] = set()
    shell_calls: set[str] = set()
    for entry in _entries(path):
        _count_agent_entry(entry, run, seen, shell_calls)
    meta: dict = {}
    meta_path = path.with_name(path.stem + ".meta.json")
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            meta = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            pass
    return run, meta


def attribute(invocations: list[Invocation], agent_files: list[Path], sidechains: Sidechains) -> None:
    """Hand each subagent's tokens to the call that started it: by the call id its meta names,
    then by its agent id, then — for inline sidechains — by the chain it hangs from."""
    by_call = {run.tool_use_id: run for inv in invocations for run in inv.agents}
    by_agent = {run.agent_id: run for run in by_call.values() if run.agent_id}
    for path in agent_files:
        found, meta = read_agent_file(path)
        run = by_call.get(str(meta.get("toolUseId") or "")) or by_agent.get(found.agent_id)
        if run is not None and not run.measured:
            run.absorb(found, str(meta.get("agentType") or ""))
    for agent_id, found in sidechains.by_agent.items():
        run = by_agent.get(agent_id)
        if run is not None and not run.measured:
            run.absorb(found)
    for tool_use_id, found in sidechains.by_call.items():
        run = by_call.get(tool_use_id)
        if run is not None and not run.measured:
            run.absorb(found)


def collect(root: Path, pattern: str | None) -> list[Invocation]:
    files = sorted(root.rglob("*.jsonl")) if root.is_dir() else [root]
    if pattern:
        files = [f for f in files if f.match(pattern) or any(p.match(pattern) for p in f.parents)]
    sidechains = Sidechains()
    invocations = [inv for f in files if f.parent.name != "subagents"
                   for inv in read_file(f, sidechains)]
    attribute(invocations, [f for f in files if f.parent.name == "subagents"], sidechains)
    return invocations


def median(values: list[float]) -> int:
    return int(statistics.median(values)) if values else 0


def _agent_side(group: list[Invocation]) -> dict | str:
    """Medians of what the invocations' subagents cost, in total and per agent type."""
    if any(inv.agent_unknown for inv in group):
        return "unknown"

    def sums(runs: list[AgentRun]) -> AgentRun:
        total = AgentRun()
        for run in runs:
            total.merge(run)
            total.shell_bytes += run.shell_bytes
            total.main_turns_after += run.main_turns_after
        return total

    def block(totals: list[AgentRun], counts: list[int] | None = None) -> dict:
        out = {}
        if counts is not None:
            out["n"] = median(counts)
        out.update({
            "billed": median([t.billed for t in totals]),
            "cache_read": median([t.cache_read for t in totals]),
            "output": median([t.output for t in totals]),
            "turns": median([t.turns for t in totals]),
        })
        return out

    side = block([sums(inv.agents) for inv in group])
    by_type = {}
    for kind in sorted({run.agent_type for inv in group for run in inv.agents}):
        per = [[run for run in inv.agents if run.agent_type == kind] for inv in group]
        totals = [sums(runs) for runs in per]
        by_type[kind] = block(totals, [len(runs) for runs in per])
        by_type[kind]["shell_bytes"] = median([t.shell_bytes for t in totals])
        by_type[kind]["main_turns_after"] = median([t.main_turns_after for t in totals])
    side["by_type"] = by_type
    return side


def summarize(invocations: list[Invocation]) -> dict:
    """Medians per command. The top-level numbers are the main thread; ``agent`` is its subagents."""
    by_command: dict[str, list[Invocation]] = {}
    for inv in invocations:
        by_command.setdefault(inv.command, []).append(inv)
    commands = {}
    for name, group in sorted(by_command.items()):
        commands[name] = {
            "n": len(group),
            "billed": median([i.billed for i in group]),
            "cache_read": median([i.cache_read for i in group]),
            "output": median([i.output for i in group]),
            "turns": median([i.turns for i in group]),
            "ceremony": median([i.ceremony for i in group]),
            "tools": {c: median([i.tools.get(c, 0) for i in group])
                      for c in CATEGORIES if any(i.tools.get(c) for i in group)},
            "agents": median([len(i.agents) for i in group]),
            "agent": _agent_side(group),
        }
    return {"invocations": len(invocations), "commands": commands}


def largest_results(invocations: list[Invocation], top: int) -> list[dict]:
    rows = [(size, tool, target, inv.command)
            for inv in invocations for size, tool, target in inv.results]
    rows.sort(reverse=True)
    return [{"bytes": s, "tool": t, "target": g[:120], "command": c} for s, t, g, c in rows[:top]]


def render(data: dict, top: list[dict]) -> str:
    lines = [f"{data['invocations']} invocation(s)", ""]
    head = (f"{'command':28} {'n':>3} {'billed':>9} {'cache read':>11} {'turns':>6} {'ceremony':>9}"
            f" {'agents':>7} {'agent billed':>13}")
    lines += [head, "-" * len(head)]
    for name, c in data["commands"].items():
        agent = c.get("agent", {})
        agent_billed = agent if isinstance(agent, str) else f"{agent.get('billed', 0):,}"
        row = (f"{name[:28]:28} {c['n']:>3} {c['billed']:>9,} {c['cache_read']:>11,} "
               f"{c['turns']:>6} {c['ceremony']:>9} {c.get('agents', 0):>7} {agent_billed:>13}")
        lines.append(row)
        tools = ", ".join(f"{k} {v}" for k, v in c["tools"].items())
        if tools:
            lines.append(f"{'':28}     {tools}")
        if isinstance(agent, dict):
            for kind, a in agent.get("by_type", {}).items():
                lines.append(f"{'':28}     agent {kind}: n {a['n']}, billed {a['billed']:,}, "
                             f"cache read {a['cache_read']:,}, turns {a['turns']}")
    if top:
        lines += ["", f"largest tool results ({len(top)}):"]
        lines += [f"  {r['bytes']:>8,} B  {r['tool']:<12} {r['target']}" for r in top]
    return "\n".join(lines)


def check(data: dict, baseline_path: Path, tolerance: float) -> tuple[int, list[str]]:
    """Compare against a baseline. Agent metrics are compared only where both sides have them, so
    a baseline written before they existed still passes on what it does have."""
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    messages, failures = [], 0

    def compare(name: str, metric: str, got: int, want: int) -> None:
        nonlocal failures
        limit = want * (1 + tolerance / 100)
        mark = "ok   "
        if want and got > limit:
            mark, failures = "WORSE", failures + 1
        messages.append(f"{mark} {name} {metric}: {got:,} vs {want:,} baseline (limit {int(limit):,})")

    for name, want in baseline.get("commands", {}).items():
        got = data["commands"].get(name)
        if not got:
            messages.append(f"MISS  {name}: not in this measurement")
            continue
        for metric in ("billed", "turns"):
            compare(name, metric, got[metric], want[metric])
        if "agents" in want and "agents" in got:
            mark = "ok   "
            if got["agents"] > want["agents"]:  # one more agent is never within a tolerance
                mark, failures = "WORSE", failures + 1
            messages.append(f"{mark} {name} agents: {got['agents']} vs {want['agents']} baseline")
        want_agent, got_agent = want.get("agent"), got.get("agent")
        if isinstance(want_agent, dict) and got_agent == "unknown":
            failures += 1
            messages.append(f"UNKN  {name} agent.billed: an agent call left no transcript")
        elif isinstance(want_agent, dict) and isinstance(got_agent, dict):
            compare(name, "agent.billed", got_agent["billed"], want_agent["billed"])
    return failures, messages


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dir", default=str(Path.home() / ".claude" / "projects"),
                   help="folder of Claude Code transcripts (default: ~/.claude/projects)")
    p.add_argument("--glob", help="only transcripts whose path matches this pattern")
    p.add_argument("--command", action="append", help="only these commands (repeatable)")
    p.add_argument("--top", type=int, default=0, help="also list the N largest tool results")
    p.add_argument("--json", action="store_true")
    p.add_argument("--check", help="baseline JSON to compare against")
    p.add_argument("--tolerance", type=float, default=15.0, help="percent a metric may grow")
    p.add_argument("--write-baseline", help="write the measurement as a baseline file")
    p.add_argument("--example", default="", help="example name stored in a written baseline")
    p.add_argument("--version", default="", help="version stored in a written baseline")
    args = p.parse_args(argv)

    invocations = collect(Path(args.dir).expanduser(), args.glob)
    if args.command:
        wanted = set(args.command)
        invocations = [i for i in invocations if i.command in wanted]
    if not invocations:
        print(f"token_report: no invocation found under {args.dir}", file=sys.stderr)
        return 2
    data = summarize(invocations)
    top = largest_results(invocations, args.top)

    if args.write_baseline:
        import datetime as dt
        out = {"example": args.example, "version": args.version,
               "measured_on": dt.date.today().isoformat(), **data}
        Path(args.write_baseline).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        print(f"baseline written: {args.write_baseline}")

    if args.json:
        print(json.dumps({**data, "largest": top}, indent=2))
    else:
        print(render(data, top))

    if args.check:
        failures, messages = check(data, Path(args.check), args.tolerance)
        print("\n".join(["", f"check against {args.check} (tolerance {args.tolerance}%)", *messages]))
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
