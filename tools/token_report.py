#!/usr/bin/env python3
"""What one invocation of a command costs, measured from Claude Code transcripts.

Reads the JSONL transcripts Claude Code writes under ``~/.claude/projects`` and groups them by
invoked command (`/rite:execute`, …): every assistant message after a command belongs to it until
the next command. For each command it reports medians — billed tokens, cache reads, output, turns —
and the tool calls that produced them, classified (fragment reads, CLI calls, git, gates, edits,
subagents). Why medians: one long invocation must not decide the number a baseline is compared to.

    python tools/token_report.py --dir ~/.claude/projects --glob "*node-minimal*" --top 10
    python tools/token_report.py --dir <e2e temp dir> --check tests/baselines/node-minimal.json

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
                         r"migrate|guard|begin|context|gates|sweep|finish)\b")
# a plugin's own prose: the fragments and command files commands read at runtime
FRAGMENT_RE = re.compile(r"(plugins[\\/].*[\\/])?(shared|parts|commands|agents)[\\/][^\\/]+\.md$",
                         re.IGNORECASE)

CATEGORIES = ("rite:fragment", "rite:cli", "git", "read:project", "read:shell", "gate", "edit",
              "subagent", "other")


def classify(tool: str, target: str) -> str:
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "edit"
    if tool in ("Task", "Agent"):
        return "subagent"
    if tool in ("Read", "Glob", "Grep"):
        return "rite:fragment" if FRAGMENT_RE.search(target or "") else "read:project"
    if tool in ("Bash", "PowerShell"):
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


class Invocation:
    def __init__(self, command: str, session: str):
        self.command = command
        self.session = session
        self.billed = self.cache_read = self.output = 0
        self.turns = 0
        self.tools: dict[str, int] = {}
        self.results: list[tuple[int, str, str]] = []  # (bytes, tool, target)

    def add_usage(self, usage: dict) -> None:
        self.turns += 1
        self.billed += (usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
                        + usage.get("output_tokens", 0))
        self.cache_read += usage.get("cache_read_input_tokens", 0)
        self.output += usage.get("output_tokens", 0)

    def add_tool(self, category: str) -> None:
        self.tools[category] = self.tools.get(category, 0) + 1

    @property
    def ceremony(self) -> int:
        """Turns spent around the work: reading the plugin's own prose and calling its CLI."""
        return self.tools.get("rite:fragment", 0) + self.tools.get("rite:cli", 0)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content or "")


def read_file(path: Path) -> list[Invocation]:
    """Every invocation in one transcript, in order."""
    out: list[Invocation] = []
    current: Invocation | None = None
    seen_messages: set[str] = set()
    tool_calls: dict[str, tuple[str, str]] = {}  # tool_use id -> (tool, target)
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = entry.get("type")
        message = entry.get("message") or {}
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
                        tool, target = tool_calls.get(block.get("tool_use_id"), ("?", ""))
                        current.results.append((len(_text(block.get("content"))), tool, target))
        elif kind == "assistant" and current is not None:
            usage = message.get("usage") or {}
            message_id = str(message.get("id") or entry.get("requestId") or entry.get("uuid"))
            if usage and message_id not in seen_messages:
                seen_messages.add(message_id)
                current.add_usage(usage)
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool = str(block.get("name") or "?")
                    target = target_of(tool, block.get("input") or {})
                    tool_calls[str(block.get("id"))] = (tool, target)
                    current.add_tool(classify(tool, target))
    return out


def collect(root: Path, pattern: str | None) -> list[Invocation]:
    files = sorted(root.rglob("*.jsonl")) if root.is_dir() else [root]
    if pattern:
        files = [f for f in files if f.match(pattern) or any(p.match(pattern) for p in f.parents)]
    return [inv for f in files for inv in read_file(f)]


def median(values: list[float]) -> int:
    return int(statistics.median(values)) if values else 0


def summarize(invocations: list[Invocation]) -> dict:
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
        }
    return {"invocations": len(invocations), "commands": commands}


def largest_results(invocations: list[Invocation], top: int) -> list[dict]:
    rows = [(size, tool, target, inv.command)
            for inv in invocations for size, tool, target in inv.results]
    rows.sort(reverse=True)
    return [{"bytes": s, "tool": t, "target": g[:120], "command": c} for s, t, g, c in rows[:top]]


def render(data: dict, top: list[dict]) -> str:
    lines = [f"{data['invocations']} invocation(s)", ""]
    head = f"{'command':28} {'n':>3} {'billed':>9} {'cache read':>11} {'turns':>6} {'ceremony':>9}"
    lines += [head, "-" * len(head)]
    for name, c in data["commands"].items():
        lines.append(f"{name[:28]:28} {c['n']:>3} {c['billed']:>9,} {c['cache_read']:>11,} "
                     f"{c['turns']:>6} {c['ceremony']:>9}")
        tools = ", ".join(f"{k} {v}" for k, v in c["tools"].items())
        if tools:
            lines.append(f"{'':28}     {tools}")
    if top:
        lines += ["", f"largest tool results ({len(top)}):"]
        lines += [f"  {r['bytes']:>8,} B  {r['tool']:<12} {r['target']}" for r in top]
    return "\n".join(lines)


def check(data: dict, baseline_path: Path, tolerance: float) -> tuple[int, list[str]]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    messages, failures = [], 0
    for name, want in baseline.get("commands", {}).items():
        got = data["commands"].get(name)
        if not got:
            messages.append(f"MISS  {name}: not in this measurement")
            continue
        for metric in ("billed", "turns"):
            limit = want[metric] * (1 + tolerance / 100)
            mark = "ok   "
            if want[metric] and got[metric] > limit:
                mark, failures = "WORSE", failures + 1
            messages.append(f"{mark} {name} {metric}: {got[metric]:,} vs {want[metric]:,} baseline "
                            f"(limit {int(limit):,})")
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
