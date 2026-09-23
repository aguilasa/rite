#!/usr/bin/env python3
"""The tokens one more fix adds to a `/rite:fix-all` — main thread and subagents apart — measured, not argued.

Each cell of the matrix (label × number of fixes × repetition) starts from nothing: the example copied
into a new temporary git repository (without its seeding data, so the model never sees the answer),
its tasks finished from the reference solution and closed through the CLI, N defects planted, and N
fixes opened as a review would. Only then does a fresh headless Claude session run the command under
measurement, with the plugin tree the label names. The transcripts of that session are read with
``token_report``: main thread, subagents, and each agent type.

    python tools/experiment.py --example node-minimal --plugin . --label as-is --defects 1,2,4 \\
        --repeat 2 --model sonnet --dry-run
    python tools/experiment.py ... --yes                  # spends tokens: run --dry-run first
    python tools/experiment.py --report docs/tokens/<date>-<name>.json  # rewrite the markdown only

A run writes ``docs/tokens/<date>-<name>.json`` (the raw matrix, after every cell) and its sibling
``.md``: setup, matrix, fitted line (intercept = fixed ceremony, slope = tokens per fix, the slope of
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


def measure(inv: tr.Invocation) -> dict:
    """One invocation's raw numbers — no medians: the report aggregates across repetitions."""
    out = {"main": {**_usage(inv), "ceremony": inv.ceremony}, "agents": len(inv.agents)}
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
    agent["by_type"] = {}
    for name in sorted(by_type):
        kind, subtotal = by_type[name], tr.Usage()
        for run in kind["runs"]:
            subtotal.merge(run)
        row = {"n": len(kind["runs"]), **_usage(subtotal), "shell_bytes": kind["shell_bytes"],
               "main_turns_after": kind["main_turns_after"]}
        agent["by_type"][name] = row
    out["agent"] = agent
    return out


# --- estimate (dry run) -----------------------------------------------------------
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


def estimate(cells: list[dict], ref: dict, command: str) -> dict:
    """Rough size of the whole matrix: the main thread once per cell, agents scaled by N."""
    tokens = 0.0
    for cell in cells:
        agents = AGENTS_PER_UNIT[command] * cell["n"]
        tokens += ref["main"]["billed"] + ref["main"]["cache_read"]
        if ref["per_agent"]:
            tokens += agents * (ref["per_agent"]["billed"] + ref["per_agent"]["cache_read"])
    return {"tokens": int(tokens), "agents_included": ref["per_agent"] is not None}


# --- one cell ---------------------------------------------------------------------
def run_cell(args, cell: dict, plugin: Path) -> dict:
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
        result.update(measure(found[0]))
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


def triage_verdict(cells: list[dict]) -> dict:
    """Is a reproducer per fix dearer than triage inline? Judged in tokens; see the report."""
    if not any(_type(c, REPRODUCER) for c in cells):
        return {"verdict": "none", "why": "no cell measured a reproducer"}
    return {"verdict": "none", "why": "not judged: the verdict in tokens is not written yet"}


def analyze(matrix: dict) -> dict:
    out = {}
    for label in [l["label"] for l in matrix["meta"]["labels"]]:
        cells = [c for c in matrix["cells"] if c["label"] == label and c.get("valid")]
        known = [c for c in cells if _agent(c)]
        total = _series(known, lambda c: c["main"]["billed"] + c["agent"]["billed"])
        kinds = sorted({k for c in known for k in c["agent"]["by_type"]})
        out[label] = {
            "cells": len(cells), "invalid": sum(1 for c in matrix["cells"]
                                                if c["label"] == label and not c.get("valid")),
            "unknown": len(cells) - len(known),
            "total": fit(total), "main": fit(_series(cells, lambda c: c["main"]["billed"])),
            "agent": fit(_series(known, lambda c: c["agent"]["billed"])),
            "by_type": {k: fit(_series(known, lambda c, k=k: (_type(c, k) or {}).get("billed", 0)))
                        for k in kinds},
            "spread": spread(total),
            "triage": triage_verdict(known),
        }
    return out


def _tok(value: float) -> str:
    return f"{round(value):,}"


def _line(f: dict | None) -> str:
    if not f:
        return "n/a (fewer than two values of N)"
    return f"intercept {_tok(f['intercept'])}, slope {_tok(f['slope'])} per fix"


def render_markdown(matrix: dict) -> str:
    """The report. Pure: the same matrix gives the same bytes (no clock, sorted, fixed formats)."""
    meta = matrix["meta"]
    analysis = analyze(matrix)
    runs = len(matrix["cells"])
    lines = [f"# Tokens of {meta['command']} on {meta['example']} — {meta['date']}", "", "## Setup", ""]
    lines += [
        f"- Example: `{meta['example']}`, command `{meta['command']}`, model `{meta['model']}`.",
        f"- Fixes per run (N): {', '.join(str(n) for n in meta['defects'])}; "
        f"{meta['repeat']} repetition(s) each; {runs} run(s) in all.",
    ]
    for label in meta["labels"]:
        lines.append(f"- Label `{label['label']}`: plugin {label['version'] or '?'} at `{label['commit'] or '?'}`.")
    lines += ["- Each run: a fresh copy of the example, its tasks finished from a reference solution, N "
              "defects planted and N fixes opened through the CLI; only the command under measurement "
              "calls the model.", ""]

    lines += ["## Matrix", "",
              "Billed = input + cache writes + output. Main thread and subagents apart.", "",
              "| label | N | rep | main billed | main cache read | main turns | ceremony | agents "
              "| agent billed | agent cache read |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for cell in matrix["cells"]:
        if not cell.get("valid"):
            lines.append(f"| {cell['label']} | {cell['n']} | {cell['rep']} | invalid: {cell.get('reason', '?')} |"
                         + " |" * 6)
            continue
        main, agent = cell["main"], _agent(cell)
        lines.append(f"| {cell['label']} | {cell['n']} | {cell['rep']} | {_tok(main['billed'])} | "
                     f"{_tok(main['cache_read'])} | {main['turns']} | {main['ceremony']} | {cell['agents']} | "
                     + (f"{_tok(agent['billed'])} | {_tok(agent['cache_read'])} |" if agent else "unknown | unknown |"))
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
              "fixed ceremony of an invocation; the slope is what one more fix adds. **The subagent floor "
              "is the slope of the agent side**: what the rite spends in fresh contexts per fix.", ""]
    for label, a in analysis.items():
        lines.append(f"### `{label}`")
        lines.append("")
        lines.append(f"- Total: {_line(a['total'])}.")
        lines.append(f"- Main thread: {_line(a['main'])}.")
        lines.append(f"- **Subagent floor: {_line(a['agent'])}.**")
        for kind, f in a["by_type"].items():
            lines.append(f"  - `{kind}`: {_line(f)}.")
        lines.append("")

    lines += ["## Reading", ""]
    for label, a in analysis.items():
        floor = a["agent"]
        if not floor:
            lines.append(f"- `{label}`: no floor — fewer than two values of N measured the agent side.")
            continue
        per_type = ", ".join(f"`{k}` {_tok(f['slope'])}" for k, f in a["by_type"].items() if f)
        lines.append(f"- `{label}`: each fix adds {_tok(floor['slope'])} billed tokens in subagents — "
                     f"{per_type}. An agent added to the rite takes at least its own per-call share "
                     f"of this on every invocation that starts it, before it does any work.")
    lines.append("")

    lines += ["## Triage decision", ""]
    for label, a in analysis.items():
        t = a["triage"]
        lines.append(f"- `{label}`: **{t['verdict']}** — {t['why']}.")
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
        "a review (same evidence and files, plainer prose); prompt-cache state across runs.",
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
    p.add_argument("--estimate-from", help="glob of past transcripts to estimate from (default: baseline)")
    p.add_argument("--name", help="report name (default: <command>-<labels>)")
    p.add_argument("--out", default=str(ROOT / "docs" / "tokens"))
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
    defects = [int(x) for x in args.defects.split(",") if x.strip()]
    cells = plan_cells(labels, defects, args.repeat, args.command)

    guess = estimate(cells, reference(args.example, args.command, args.estimate_from), args.command)
    print(f"{args.command} on {args.example}, model {args.model}: {len(cells)} run(s)")
    for cell in cells:
        print(f"  {cell['label']:<12} N={cell['n']}  rep {cell['rep']}")
    print(f"estimate: ~{guess['tokens']:,} tokens"
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
                 "labels": [{"label": l, **plugin_info(pl)} for l, pl in zip(labels, plugins)]},
        "cells": [],
    }
    by_label = dict(zip(labels, plugins))
    for cell in cells:
        print(f"\n=== {cell['label']} N={cell['n']} rep {cell['rep']}", flush=True)
        matrix["cells"].append(run_cell(args, cell, by_label[cell["label"]]))
        write_matrix(json_path, matrix)  # after every cell: a crash keeps what was paid for
    print(f"\nmatrix: {json_path}\nreport: {write_report(json_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
