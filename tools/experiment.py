#!/usr/bin/env python3
"""What one more fix costs a `/rite:fix-all` — main thread and subagents apart — measured, not argued.

Each cell of the matrix (label × number of fixes × repetition) starts from nothing: the example copied
into a new temporary git repository (without its seeding data, so the model never sees the answer),
its tasks finished from the reference solution and closed through the CLI, N defects planted, and N
fixes opened as a review would. Only then does a fresh headless Claude session run the command under
measurement, with the plugin tree the label names. The transcripts of that session are read with
``token_report``: main thread, subagents, and each agent type.

    python tools/experiment.py --example node-minimal --plugin . --label as-is --defects 1,2,4 \\
        --repeat 2 --model sonnet --dry-run
    python tools/experiment.py ... --yes                  # spends tokens: run --dry-run first
    python tools/experiment.py --report docs/cost/<date>-<name>.json    # rewrite the markdown only

A run writes ``docs/cost/<date>-<name>.json`` (the raw matrix, after every cell) and its sibling
``.md``: setup, matrix, fitted line (intercept = fixed ceremony, slope = cost per fix, the slope of
the agent side = the subagent floor), reading, triage decision, caveats. The markdown is rendered from
the JSON alone, so the same matrix always gives the same bytes.

``--plugin``/``--label`` repeat to compare plugin trees. ``--command review`` measures the control:
one defect, one review, one reviewer agent. Nothing here changes a prompt or the flow of the rite:
if measuring needed that, the run would not measure the rite.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tests" / "e2e")]

import _example as ex  # noqa: E402
import token_report as tr  # noqa: E402

COMMANDS = {"fix-all": "/rite:fix-all", "review": "/rite:review"}
AGENTS_PER_UNIT = {"fix-all": 2, "review": 1}  # a reproducer and a worker per fix; one reviewer


# --- the matrix -----------------------------------------------------------------
def plan_cells(labels: list[str], defects: list[int], repeat: int, command: str) -> list[dict]:
    sizes = [1] if command == "review" else defects
    return [{"label": label, "n": n, "rep": rep}
            for label in labels for n in sizes for rep in range(1, repeat + 1)]


def _usage(u: tr.Usage) -> dict:
    return {"billed": u.billed, "input": u.input, "cache_write": u.cache_write,
            "cache_read": u.cache_read, "output": u.output, "turns": u.turns}


def measure(inv: tr.Invocation, prices: dict | None) -> dict:
    """One invocation's raw numbers — no medians: the report aggregates across repetitions."""
    out = {"main": {**_usage(inv), "ceremony": inv.ceremony}, "agents": len(inv.agents)}
    if prices:
        out["main"]["usd"] = round(inv.usd(prices), 6)
    if inv.agent_unknown:
        out["agent"] = "unknown"
        return out
    total, by_type = tr.Usage(), {}
    for run in inv.agents:
        total.merge(run)
        kind = by_type.setdefault(run.agent_type, {"runs": [], "shell_bytes": 0, "main_turns_after": 0})
        kind["runs"].append(run)
        kind["shell_bytes"] += run.shell_bytes
        kind["main_turns_after"] += run.main_turns_after
    agent = _usage(total)
    if prices:
        agent["usd"] = round(total.usd(prices), 6)
    agent["by_type"] = {}
    for name in sorted(by_type):
        kind, subtotal = by_type[name], tr.Usage()
        for run in kind["runs"]:
            subtotal.merge(run)
        row = {"n": len(kind["runs"]), **_usage(subtotal), "shell_bytes": kind["shell_bytes"],
               "main_turns_after": kind["main_turns_after"]}
        if prices:
            row["usd"] = round(subtotal.usd(prices), 6)
        agent["by_type"][name] = row
    out["agent"] = agent
    return out


# --- estimate (dry run) -----------------------------------------------------------
def _usd_rough(side: dict, prices: dict) -> float:
    """Billed minus output priced as cache writes (the upper side), output as output, reads as reads."""
    written = max(side.get("billed", 0) - side.get("output", 0), 0)
    return (written * prices["cache_write"] + side.get("output", 0) * prices["output"]
            + side.get("cache_read", 0) * prices["cache_read"]) / 1_000_000


def reference(example: str, command: str, estimate_from: str | None) -> dict:
    """The per-invocation numbers an estimate scales: live transcripts, else the example's baseline."""
    name = COMMANDS[command]
    if estimate_from:
        data = tr.summarize([i for i in tr.collect(Path.home() / ".claude" / "projects", estimate_from)
                             if i.command == name])
        row, source = data["commands"].get(name), f"transcripts matching {estimate_from}"
    else:
        path = ROOT / "tests" / "baselines" / f"{example}.json"
        row = json.loads(path.read_text(encoding="utf-8"))["commands"].get(name) if path.is_file() else None
        source = str(path.relative_to(ROOT)).replace("\\", "/")
    if not row:
        raise SystemExit(f"no {name} in {source}: pass --estimate-from <glob of past runs>")
    agent = row.get("agent")
    per_agent = None
    if isinstance(agent, dict) and row.get("agents"):
        per_agent = {k: agent[k] / row["agents"] for k in ("billed", "cache_read", "output")}
    return {"source": source, "main": {k: row[k] for k in ("billed", "cache_read", "output")},
            "per_agent": per_agent}


def estimate(cells: list[dict], ref: dict, command: str, prices: dict | None) -> dict:
    """Rough cost of the whole matrix: the main thread once per cell, agents scaled by N."""
    main_usd = _usd_rough(ref["main"], prices) if prices else None
    agent_usd = _usd_rough(ref["per_agent"], prices) if prices and ref["per_agent"] else None
    tokens = usd = 0.0
    for cell in cells:
        agents = AGENTS_PER_UNIT[command] * cell["n"]
        tokens += ref["main"]["billed"] + ref["main"]["cache_read"]
        if ref["per_agent"]:
            tokens += agents * (ref["per_agent"]["billed"] + ref["per_agent"]["cache_read"])
        if main_usd is not None:
            usd += main_usd + (agents * agent_usd if agent_usd is not None else 0)
    return {"tokens": int(tokens), "usd": round(usd, 2) if prices else None,
            "agents_included": ref["per_agent"] is not None}


# --- one cell ---------------------------------------------------------------------
def run_cell(args, cell: dict, plugin: Path, prices: dict | None) -> dict:
    tmp, repo, manifest = ex.make_repo(args.example, strip=("e2e", "e2e.json"))
    cycle, result = manifest["cycle"], {**cell, "valid": False}
    try:
        ex.seed_done(repo, manifest, args.example)
        defects = ex.defect_list(manifest)[:cell["n"]]
        if len(defects) < cell["n"]:
            raise SystemExit(f"{args.example}: {cell['n']} defects asked, the manifest has {len(defects)}")
        for defect in defects:
            if ex.apply_defect(repo, defect) is None:
                result["reason"] = f"defect did not apply: {defect['title']}"
                return result
        if args.command == "fix-all":
            ex.seed_fixes(repo, manifest, defects)
            opened = ex.open_fixes(repo, cycle)
            if opened != cell["n"]:
                result["reason"] = f"{opened} open fixes before the run, {cell['n']} planted"
                return result
        ex.claude(repo, f"{COMMANDS[args.command]} {cycle}", args.model, plugin=plugin)
        found = [i for i in tr.collect(ex.transcripts_for(repo), None)
                 if i.command == COMMANDS[args.command]]
        if len(found) != 1:
            result["reason"] = f"{len(found)} {COMMANDS[args.command]} invocations in the transcripts"
            return result
        result.update(measure(found[0], prices))
        result["symptoms_fixed"] = sum(ex.symptom_of(repo, d) == d["good_output"] for d in defects)
        if args.command == "fix-all":
            result["open_fixes_after"] = ex.open_fixes(repo, cycle)
        result["valid"] = True
        return result
    finally:
        if args.keep:
            print(f"kept: {tmp}", flush=True)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def plugin_info(path: Path) -> dict:
    manifest = path / ".claude-plugin" / "plugin.json"
    version = json.loads(manifest.read_text(encoding="utf-8")).get("version", "") if manifest.is_file() else ""
    try:
        commit = subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(path), "status", "--porcelain"], capture_output=True,
                               text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = "", ""
    return {"version": version, "commit": commit + ("-dirty" if dirty else "")}


def write_matrix(path: Path, matrix: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(matrix, indent=2, sort_keys=True) + "\n")


# --- the report -------------------------------------------------------------------
REPRODUCER = "rite:rite-reproducer"
BYTES_PER_TOKEN = 4  # rough, and said so in the report


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _series(cells: list[dict], value) -> list[tuple[int, float]]:
    points = []
    for cell in cells:
        v = value(cell)
        if v is not None:
            points.append((cell["n"], float(v)))
    return points


def fit(points: list[tuple[int, float]]) -> dict | None:
    """Least squares over every repetition: intercept = fixed ceremony, slope = cost per fix."""
    if len({x for x, _ in points}) < 2:
        return None
    import statistics
    slope, intercept = statistics.linear_regression([x for x, _ in points], [y for _, y in points])
    return {"intercept": intercept, "slope": slope}


def spread(points: list[tuple[int, float]]) -> dict[int, float]:
    """Per N, max − min across repetitions."""
    by_n: dict[int, list[float]] = {}
    for x, y in points:
        by_n.setdefault(x, []).append(y)
    return {n: max(ys) - min(ys) for n, ys in sorted(by_n.items())}


def _agent(cell: dict) -> dict | None:
    return cell["agent"] if isinstance(cell.get("agent"), dict) else None


def _type(cell: dict, kind: str) -> dict | None:
    agent = _agent(cell)
    return agent["by_type"].get(kind) if agent else None


def inline_estimate(cell: dict, prices: dict) -> float | None:
    """What keeping the reproduction output in the main context would have cost, per fix: its tokens
    written once, then read back on every main turn that followed the triage."""
    row = _type(cell, REPRODUCER)
    if not row or not row["n"]:
        return None
    tokens = row["shell_bytes"] / BYTES_PER_TOKEN
    turns_after = row["main_turns_after"] / row["n"]
    usd = (tokens * prices["cache_write"] + tokens * turns_after * prices["cache_read"]) / 1_000_000
    return usd / cell["n"]


def triage_verdict(cells: list[dict], prices: dict | None) -> dict:
    """The question the floor answers: is a reproducer per fix dearer than triage inline? Inline, the
    main thread pays for holding the reproduction output and for the turns it spends running the
    evidence, whose count the matrix cannot see. So each N is judged at the two ends — no extra turn,
    one extra turn per fix — against the dispersion between repetitions; in between, the report gives
    the break-even number of main-thread turns."""
    if not prices:
        return {"verdict": "none", "why": "no [cost] table: tokens alone cannot price a fresh context "
                                          "against a growing one"}
    rows = []
    for n in sorted({c["n"] for c in cells}):
        group = [c for c in cells if c["n"] == n]
        agent = [(_type(c, REPRODUCER) or {}).get("usd") for c in group]
        inline = [inline_estimate(c, prices) for c in group]
        turns = [c["main"]["usd"] / c["main"]["turns"] for c in group if c["main"].get("turns")]
        if any(v is None for v in agent + inline) or len(turns) != len(group):
            continue
        per_fix = [v / n for v in agent]
        noise = max(max(per_fix) - min(per_fix), max(inline) - min(inline))
        row = {"n": n, "agent_per_fix": _mean(per_fix), "inline_per_fix": _mean(inline),
               "main_turn": _mean(turns), "noise": noise}
        row["break_even_turns"] = (row["agent_per_fix"] - row["inline_per_fix"]) / row["main_turn"]
        if row["agent_per_fix"] + noise < row["inline_per_fix"]:
            row["side"] = "agent"      # cheaper even if inline triage cost no turn at all
        elif row["agent_per_fix"] - noise > row["inline_per_fix"] + row["main_turn"]:
            row["side"] = "inline"     # cheaper even at a whole extra main-thread turn per fix
        else:
            row["side"] = "open"
        rows.append(row)
    if not rows:
        return {"verdict": "none", "why": "no cell measured a reproducer"}
    sides = [r["side"] for r in rows]
    if all(side == "inline" for side in sides):
        return {"verdict": "apply", "rows": rows, "inline_triage_max": max(r["n"] for r in rows),
                "why": "the reproducer costs more than inline triage even at one extra main-thread turn "
                       "per fix, at every N measured; no crossover inside the range, so the limit is the "
                       "largest N measured"}
    if all(side == "agent" for side in sides):
        return {"verdict": "do not apply", "rows": rows,
                "why": "the reproducer is cheaper than holding its output inline, even with no extra turn"}
    low = min(r["break_even_turns"] for r in rows)
    high = max(r["break_even_turns"] for r in rows)
    return {"verdict": "inconclusive", "rows": rows,
            "why": f"inline triage is cheaper only if it adds fewer than {low:.2f}–{high:.2f} main-thread "
                   f"turns per fix, which this matrix does not measure; apply it and measure the turns"}


def analyze(matrix: dict) -> dict:
    prices = matrix["meta"].get("prices")
    out = {}
    for label in [l["label"] for l in matrix["meta"]["labels"]]:
        cells = [c for c in matrix["cells"] if c["label"] == label and c.get("valid")]
        known = [c for c in cells if _agent(c)]
        total = _series(known, lambda c: c["main"]["billed"] + c["agent"]["billed"])
        kinds = sorted({k for c in known for k in c["agent"]["by_type"]})
        result = {
            "cells": len(cells), "invalid": sum(1 for c in matrix["cells"]
                                                if c["label"] == label and not c.get("valid")),
            "unknown": len(cells) - len(known),
            "total": fit(total), "main": fit(_series(cells, lambda c: c["main"]["billed"])),
            "agent": fit(_series(known, lambda c: c["agent"]["billed"])),
            "by_type": {k: fit(_series(known, lambda c, k=k: (_type(c, k) or {}).get("billed", 0)))
                        for k in kinds},
            "spread": spread(total),
        }
        if prices:
            result["usd"] = {
                "total": fit(_series(known, lambda c: c["main"]["usd"] + c["agent"]["usd"])),
                "agent": fit(_series(known, lambda c: c["agent"]["usd"])),
                "by_type": {k: fit(_series(known, lambda c, k=k: (_type(c, k) or {}).get("usd", 0)))
                            for k in kinds},
            }
        result["triage"] = triage_verdict(known, prices)
        out[label] = result
    return out


def _tok(value: float) -> str:
    return f"{round(value):,}"


def _usd(value: float) -> str:
    return f"${value:.4f}"


def _line(f: dict | None, money: bool = False) -> str:
    if not f:
        return "n/a (fewer than two values of N)"
    fmt = _usd if money else _tok
    return f"intercept {fmt(f['intercept'])}, slope {fmt(f['slope'])} per fix"


def render_markdown(matrix: dict) -> str:
    """The report. Pure: the same matrix gives the same bytes (no clock, sorted, fixed formats)."""
    meta, prices = matrix["meta"], matrix["meta"].get("prices")
    analysis = analyze(matrix)
    runs = len(matrix["cells"])
    lines = [f"# Cost of {meta['command']} on {meta['example']} — {meta['date']}", "", "## Setup", ""]
    lines += [
        f"- Example: `{meta['example']}`, command `{meta['command']}`, model `{meta['model']}`.",
        f"- Fixes per run (N): {', '.join(str(n) for n in meta['defects'])}; "
        f"{meta['repeat']} repetition(s) each; {runs} run(s) in all.",
    ]
    for label in meta["labels"]:
        lines.append(f"- Label `{label['label']}`: plugin {label['version'] or '?'} at `{label['commit'] or '?'}`.")
    if prices:
        lines.append(f"- Prices (USD per million tokens, from `{meta.get('prices_file') or '?'}`, "
                     f"used on {meta['date']}): " + ", ".join(f"{k} {prices[k]}" for k in tr.PRICE_KEYS) + ".")
    else:
        lines.append("- No `[cost]` table: tokens only, no dollars.")
    lines += ["- Each run: a fresh copy of the example, its tasks finished from a reference solution, N "
              "defects planted and N fixes opened through the CLI; only the command under measurement "
              "calls the model.", ""]

    lines += ["## Matrix", "",
              "Billed = input + cache writes + output. Main thread and subagents apart.", ""]
    head = "| label | N | rep | main billed | main cache read | main turns | ceremony | agents | agent billed | agent cache read |"
    rule = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    if prices:
        head += " USD main | USD agent |"
        rule += " ---: | ---: |"
    lines += [head, rule]
    for cell in matrix["cells"]:
        if not cell.get("valid"):
            lines.append(f"| {cell['label']} | {cell['n']} | {cell['rep']} | invalid: {cell.get('reason', '?')} |"
                         + " |" * (8 if prices else 6))
            continue
        main, agent = cell["main"], _agent(cell)
        row = (f"| {cell['label']} | {cell['n']} | {cell['rep']} | {_tok(main['billed'])} | "
               f"{_tok(main['cache_read'])} | {main['turns']} | {main['ceremony']} | {cell['agents']} | "
               + (f"{_tok(agent['billed'])} | {_tok(agent['cache_read'])} |" if agent else "unknown | unknown |"))
        if prices:
            row += f" {_usd(main['usd'])} | " + (f"{_usd(agent['usd'])} |" if agent else "? |")
        lines.append(row)
    lines.append("")
    kinds = sorted({k for c in matrix["cells"] if _agent(c) for k in c["agent"]["by_type"]})
    if kinds:
        lines += ["Per agent type (billed / turns / shell output bytes):", ""]
        lines += ["| label | N | rep | " + " | ".join(kinds) + " |",
                  "| --- | ---: | ---: |" + " ---: |" * len(kinds)]
        for cell in matrix["cells"]:
            if not _agent(cell):
                continue
            parts = []
            for kind in kinds:
                row = _type(cell, kind)
                parts.append(f"{row['n']}× {_tok(row['billed'])} / {row['turns']} / {_tok(row['shell_bytes'])}"
                             if row else "—")
            lines.append(f"| {cell['label']} | {cell['n']} | {cell['rep']} | " + " | ".join(parts) + " |")
        lines.append("")

    lines += ["## Fitted line", "",
              "Least squares over every valid repetition, billed tokens against N. The intercept is the "
              "fixed ceremony of an invocation; the slope is what one more fix costs. **The subagent floor "
              "is the slope of the agent side**: what the rite spends in fresh contexts per fix.", ""]
    for label, a in analysis.items():
        lines.append(f"### `{label}`")
        lines.append("")
        lines.append(f"- Total: {_line(a['total'])}.")
        lines.append(f"- Main thread: {_line(a['main'])}.")
        lines.append(f"- **Subagent floor: {_line(a['agent'])}.**")
        for kind, f in a["by_type"].items():
            lines.append(f"  - `{kind}`: {_line(f)}.")
        if prices:
            lines.append(f"- In dollars — total: {_line(a['usd']['total'], True)}; "
                         f"**agent: {_line(a['usd']['agent'], True)}**.")
            for kind, f in a["usd"]["by_type"].items():
                lines.append(f"  - `{kind}`: {_line(f, True)}.")
        lines.append("")

    lines += ["## Reading", ""]
    for label, a in analysis.items():
        floor, money = a["agent"], (a.get("usd") or {}).get("agent")
        if not floor:
            lines.append(f"- `{label}`: no floor — fewer than two values of N measured the agent side.")
            continue
        sentence = f"- `{label}`: each fix adds {_tok(floor['slope'])} billed tokens in subagents"
        if money:
            sentence += f" ({_usd(money['slope'])})"
        per_type = ", ".join(f"`{k}` {_tok(f['slope'])}" for k, f in a["by_type"].items() if f)
        sentence += (f" — {per_type}. An agent added to the rite costs at least its own per-call share "
                     f"of this on every invocation that starts it, before it does any work.")
        lines.append(sentence)
    lines.append("")

    lines += ["## Triage decision", "",
              f"Is a `{REPRODUCER}` per fix dearer than running its evidence in the main thread? Inline, "
              "the main thread pays twice: for holding the output (estimated: bytes / "
              f"{BYTES_PER_TOKEN} as tokens, written once, then read from cache on every later turn) and "
              "for the turns spent running the commands, which only a run with inline triage can count. "
              "Each N is judged with no extra turn and with one extra turn per fix; the break-even is the "
              "number of main-thread turns per fix at which both cost the same.", ""]
    for label, a in analysis.items():
        t = a["triage"]
        lines.append(f"- `{label}`: **{t['verdict']}** — {t['why']}."
                     + (f" `[limits].inline_triage_max` = {t['inline_triage_max']}." if "inline_triage_max" in t else ""))
        for r in t.get("rows", []):
            lines.append(f"  - N={r['n']}: reproducer {_usd(r['agent_per_fix'])} per fix; output held inline "
                         f"{_usd(r['inline_per_fix'])} per fix; one main-thread turn {_usd(r['main_turn'])}; "
                         f"break-even {r['break_even_turns']:.2f} turns per fix; dispersion {_usd(r['noise'])}.")
    lines.append("")

    lines += ["## Caveats", ""]
    lines.append(f"- {meta['repeat']} repetition(s) per N: the line is a trend, not a law. "
                 + ("One repetition measures no dispersion at all." if meta["repeat"] < 2 else
                    "Two points per N bound the noise only loosely."))
    for label, a in analysis.items():
        sp = ", ".join(f"N={n}: {_tok(v)}" for n, v in a["spread"].items())
        lines.append(f"- `{label}`: spread of total billed between repetitions — {sp or 'n/a'}. "
                     f"Invalid runs: {a['invalid']}; runs with an unknown agent side: {a['unknown']}.")
    lines += [
        "- Not controlled: the model's own variance; fixes written by the seeding harness rather than by "
        "a review (same evidence and files, plainer prose); prompt-cache state across runs; the price "
        "table's date.",
        f"- The inline estimate assumes {BYTES_PER_TOKEN} bytes per token and that the output would be "
        "held until the end of the invocation. The cost of one main-thread turn is the run's main-thread "
        "dollars divided by its turns: an average, while a later turn costs more than an early one.",
        "",
    ]
    return "\n".join(lines)


def write_report(json_path: Path) -> Path:
    matrix = json.loads(json_path.read_text(encoding="utf-8"))
    md_path = json_path.with_suffix(".md")
    with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_markdown(matrix))
    return md_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--example", default="node-minimal")
    p.add_argument("--plugin", action="append", help="plugin tree to load (repeatable; default: this one)")
    p.add_argument("--label", action="append", help="one per --plugin (default: as-is)")
    p.add_argument("--defects", default="1,2,4", help="numbers of fixes per cell, comma-separated")
    p.add_argument("--repeat", type=int, default=2)
    p.add_argument("--model", default="sonnet")
    p.add_argument("--command", choices=sorted(COMMANDS), default="fix-all")
    p.add_argument("--prices", help="TOML with a [cost] table (USD per million tokens)")
    p.add_argument("--estimate-from", help="glob of past transcripts to estimate from (default: baseline)")
    p.add_argument("--name", help="report name (default: <command>-<labels>)")
    p.add_argument("--out", default=str(ROOT / "docs" / "cost"))
    p.add_argument("--dry-run", action="store_true", help="print the matrix and its estimated cost")
    p.add_argument("--yes", action="store_true", help="run it: spends tokens")
    p.add_argument("--keep", action="store_true", help="keep the temporary repositories")
    p.add_argument("--report", help="only (re)write the markdown report of this matrix JSON")
    args = p.parse_args(argv)

    if args.report:
        print(f"report: {write_report(Path(args.report))}")
        return 0

    plugins = [Path(x).resolve() for x in (args.plugin or [str(ROOT)])]
    labels = args.label or (["as-is"] if len(plugins) == 1 else [])
    if len(labels) != len(plugins):
        p.error("give one --label per --plugin")
    prices = tr.load_prices(Path(args.prices)) if args.prices else None
    if args.prices and prices is None:
        p.error(f"no complete [cost] table in {args.prices}")
    defects = [int(x) for x in args.defects.split(",") if x.strip()]
    cells = plan_cells(labels, defects, args.repeat, args.command)

    guess = estimate(cells, reference(args.example, args.command, args.estimate_from), args.command, prices)
    print(f"{args.command} on {args.example}, model {args.model}: {len(cells)} run(s)")
    for cell in cells:
        print(f"  {cell['label']:<12} N={cell['n']}  rep {cell['rep']}")
    print(f"estimate: ~{guess['tokens']:,} tokens"
          + (f", ~${guess['usd']:.2f}" if guess["usd"] is not None else " (no [cost]: no dollars)")
          + ("" if guess["agents_included"] else "; agent side NOT included (the reference has none)"))
    if args.dry_run:
        return 0
    if not args.yes:
        print("nothing run: pass --yes to spend these tokens (after --dry-run)", file=sys.stderr)
        return 2

    today = dt.date.today().isoformat()
    name = args.name or f"{args.command}-{'-'.join(labels)}"
    json_path = Path(args.out) / f"{today}-{name}.json"
    matrix = {
        "meta": {"example": args.example, "command": COMMANDS[args.command], "model": args.model,
                 "date": today, "defects": defects, "repeat": args.repeat,
                 "labels": [{"label": l, **plugin_info(pl)} for l, pl in zip(labels, plugins)],
                 "prices": prices, "prices_file": args.prices},
        "cells": [],
    }
    by_label = dict(zip(labels, plugins))
    for cell in cells:
        print(f"\n=== {cell['label']} N={cell['n']} rep {cell['rep']}", flush=True)
        matrix["cells"].append(run_cell(args, cell, by_label[cell["label"]], prices))
        write_matrix(json_path, matrix)  # after every cell: a crash keeps what was paid for
    print(f"\nmatrix: {json_path}\nreport: {write_report(json_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
