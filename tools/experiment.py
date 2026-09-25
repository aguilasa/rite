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
        row, source = data["groups"].get(name), f"transcripts matching {estimate_from}"
    else:  # one baseline per e2e script: the first that ran the command
        row, source = None, f"tests/baselines/{example}.{{loop,lifecycle}}.json"
        for script in ("loop", "lifecycle"):
            path = ROOT / "tests" / "baselines" / f"{example}.{script}.json"
            row = tr.baseline_groups(json.loads(path.read_text(encoding="utf-8"))).get(name) if path.is_file() else None
            if row:
                source = str(path.relative_to(ROOT)).replace("\\", "/")
                break
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


def _median(values: list[float]) -> float:
    import statistics
    return statistics.median(values)


def _range(values: list[float]) -> float:
    return max(values) - min(values)


def agent_side(cell: dict, weight: float) -> dict | None:
    """What the reproducers of one run used, for the whole batch."""
    row = _type(cell, REPRODUCER)
    if not row or not row["n"]:
        return None
    return {"billed": row["billed"], "cache_read": row["cache_read"],
            "effective": tr.effective(row["billed"], row["cache_read"], weight)}


def inline_estimate(cell: dict, weight: float) -> dict | None:
    """Triage inline, for the whole batch: **one** main-thread turn runs every fix's evidence
    (`reproduce --all`), and its output — bytes / 4 as tokens, bounded by `--tail` — is written once
    and read back on each main-thread turn that followed a reproducer's result."""
    row, main = _type(cell, REPRODUCER), cell["main"]
    if not row or not row["n"] or not main.get("turns"):
        return None
    held = row["shell_bytes"] / BYTES_PER_TOKEN
    after = row["main_turns_after"] / row["n"]
    turn_billed, turn_read = main["billed"] / main["turns"], main["cache_read"] / main["turns"]
    billed, read = turn_billed + held, turn_read + held * after
    return {"billed": billed, "cache_read": read, "effective": tr.effective(billed, read, weight),
            "after": after}


def triage_verdict(cells: list[dict], weight: float = tr.CACHE_WEIGHT) -> dict:
    """Is a reproducer per fix dearer than triage inline? Judged per batch, in effective tokens: the
    agents multiply a fresh context per fix, while inline one main-thread turn serves the whole batch.
    A side wins an N only by more than the dispersion between repetitions. The turn-over is the
    smallest N from which inline wins at every N measured; the output limit is what one fix may hold
    inline before its own reproducer would have been cheaper."""
    rows = []
    for n in sorted({c["n"] for c in cells}):
        group = [c for c in cells if c["n"] == n]
        agent = [agent_side(c, weight) for c in group]
        inline = [inline_estimate(c, weight) for c in group]
        if any(v is None for v in agent + inline):
            continue
        row = {"n": n,
               "agent": {k: _median([a[k] for a in agent]) for k in ("billed", "cache_read", "effective")},
               "inline": {k: _median([i[k] for i in inline]) for k in ("billed", "cache_read", "effective")},
               "noise": max(_range([a["effective"] for a in agent]), _range([i["effective"] for i in inline])),
               "after": _median([i["after"] for i in inline])}
        row["agent_per_fix"] = row["agent"]["effective"] / n
        row["inline_per_fix"] = row["inline"]["effective"] / n
        # one more fix held inline costs its output (written, then read back); its agent costs a context
        row["break_even_kb"] = (row["agent_per_fix"] * BYTES_PER_TOKEN / (1 + weight * row["after"])) / 1024
        gain = row["agent"]["effective"] - row["inline"]["effective"]
        row["side"] = "inline" if gain > row["noise"] else "agent" if gain < -row["noise"] else "open"
        rows.append(row)
    if not rows:
        return {"verdict": "none", "why": "no cell measured a reproducer"}
    turn_over = None
    for row in reversed(rows):
        if row["side"] != "inline":
            break
        turn_over = row["n"]
    if all(r["side"] == "agent" for r in rows):
        return {"verdict": "do not apply", "rows": rows,
                "why": "a reproducer per fix is cheaper than one main-thread turn holding the output"}
    if turn_over is None:
        return {"verdict": "inconclusive", "rows": rows,
                "why": "at the largest N measured the difference is within the dispersion"}
    limit = min(r["break_even_kb"] for r in rows if r["n"] >= turn_over)
    below = [r["n"] for r in rows if r["n"] < turn_over]
    return {"verdict": "apply", "rows": rows, "turn_over": turn_over,
            "inline_triage_max_output_kb": max(int(limit), 1),
            "why": f"inline triage is cheaper from N = {turn_over} up, and the gap grows with the batch"
                   + (f"; at N = {', '.join(map(str, below))} the difference is within the dispersion"
                      if below else "")}


def analyze(matrix: dict, weight: float = tr.CACHE_WEIGHT) -> dict:
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
            "triage": triage_verdict(known, weight),
            "effective": {
                "main": fit(_series(cells, lambda c: tr.effective(c["main"]["billed"], c["main"]["cache_read"],
                                                                  weight))),
                "agent": fit(_series(known, lambda c: tr.effective(c["agent"]["billed"],
                                                                   c["agent"]["cache_read"], weight))),
            },
        }
    return out


def compare_labels(matrix: dict, weight: float = tr.CACHE_WEIGHT) -> list[dict]:
    """Per N, each label's median of the whole invocation — main thread plus subagents, in effective
    tokens — with its dispersion and main-thread turns. What a change of the rite actually saved."""
    labels = [l["label"] for l in matrix["meta"]["labels"]]
    rows = []
    for n in sorted({c["n"] for c in matrix["cells"]}):
        row = {"n": n, "labels": {}}
        for label in labels:
            cells = [c for c in matrix["cells"] if c["label"] == label and c["n"] == n and c.get("valid")
                     and _agent(c) is not None]
            if not cells:
                continue
            totals = [tr.effective(c["main"]["billed"] + c["agent"]["billed"],
                                   c["main"]["cache_read"] + c["agent"]["cache_read"], weight) for c in cells]
            row["labels"][label] = {"effective": _median(totals), "noise": _range(totals),
                                    "turns": _median([c["main"]["turns"] for c in cells]),
                                    "agents": _median([c["agents"] for c in cells])}
        rows.append(row)
    return rows


def _tok(value: float) -> str:
    return f"{round(value):,}"


def _line(f: dict | None) -> str:
    if not f:
        return "n/a (fewer than two values of N)"
    return f"intercept {_tok(f['intercept'])}, slope {_tok(f['slope'])} per fix"


def render_markdown(matrix: dict, weight: float = tr.CACHE_WEIGHT) -> str:
    """The report. Pure: the same matrix and weight give the same bytes (no clock, sorted, fixed
    formats)."""
    meta = matrix["meta"]
    analysis = analyze(matrix, weight)
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
              "calls the model.",
              f"- Effective = billed + {weight:g} × cache read: {tr.WEIGHT_NOTE}. Every comparison below "
              "is in effective tokens.", ""]

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
        lines.append(f"- Effective (w = {weight:g}) — main thread: {_line(a['effective']['main'])}; "
                     f"subagents: {_line(a['effective']['agent'])}.")
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

    lines += ["## Triage decision", "",
              f"Is a `{REPRODUCER}` per fix dearer than running the evidence in the main thread? Judged per "
              "batch, in effective tokens "
              f"(w = {weight:g}). The agent side is what the reproducers used. The inline side is **one** "
              "main-thread turn for the whole batch (`reproduce --all`: the run's average main turn) plus "
              f"the output it holds — shell bytes / {BYTES_PER_TOKEN} as tokens, bounded by `--tail`, "
              "written once and read back on each main-thread turn that followed a reproducer's result. "
              "A side wins an N only by more than the dispersion between repetitions. The output limit "
              "is what one fix may hold inline before its own reproducer would have been cheaper.", ""]
    for label, a in analysis.items():
        t = a["triage"]
        lines.append(f"### `{label}`")
        lines.append("")
        if t.get("rows"):
            lines += ["| N | reproducers (agent) | inline (1 turn per batch) | effective agent | effective inline "
                      "| per fix agent | per fix inline | dispersion | side | output limit per fix |",
                      "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |"]
            for r in t["rows"]:
                ag, il = r["agent"], r["inline"]
                lines.append(f"| {r['n']} | {_tok(ag['billed'])} billed + {_tok(ag['cache_read'])} cache read | "
                             f"{_tok(il['billed'])} billed + {_tok(il['cache_read'])} cache read | "
                             f"{_tok(ag['effective'])} | {_tok(il['effective'])} | {_tok(r['agent_per_fix'])} | "
                             f"{_tok(r['inline_per_fix'])} | {_tok(r['noise'])} | {r['side']} | "
                             f"{r['break_even_kb']:.1f} KB |")
            lines.append("")
        lines.append(f"**{t['verdict']}** — {t['why']}."
                     + (f" Turn-over: N = {t['turn_over']}." if "turn_over" in t else "")
                     + (f" `[limits].inline_triage_max_output_kb` = {t['inline_triage_max_output_kb']}."
                        if "inline_triage_max_output_kb" in t else ""))
        lines.append("")

    labels = [l["label"] for l in meta["labels"]]
    if len(labels) > 1:
        base = labels[0]
        lines += ["## Labels compared", "",
                  f"The whole invocation — main thread plus subagents — in effective tokens (w = {weight:g}), "
                  f"median per N, against `{base}`. The change counts only beyond the dispersion.", "",
                  "| N | " + " | ".join(f"`{l}`" for l in labels) + " | "
                  + " | ".join(f"`{l}` vs `{base}`" for l in labels[1:]) + " |",
                  "| ---: |" + " ---: |" * (2 * len(labels) - 1)]
        for row in compare_labels(matrix, weight):
            got = row["labels"]
            cells = [f"{_tok(got[l]['effective'])} ± {_tok(got[l]['noise'])} ({got[l]['turns']:g} turns, "
                     f"{got[l]['agents']:g} agents)" if l in got else "—" for l in labels]
            deltas = []
            for l in labels[1:]:
                if l in got and base in got:
                    change = got[l]["effective"] - got[base]["effective"]
                    beyond = abs(change) > max(got[l]["noise"], got[base]["noise"])
                    deltas.append(f"{change / got[base]['effective']:+.0%}" + ("" if beyond else " (within noise)"))
                else:
                    deltas.append("—")
            lines.append(f"| {row['n']} | " + " | ".join(cells) + " | " + " | ".join(deltas) + " |")
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
        f"- The inline side is modelled, not measured: {BYTES_PER_TOKEN} bytes per token, and the cost of its "
        "one turn is the run's average main-thread turn, while a later turn costs more than an early one.",
        "",
    ]
    return "\n".join(lines)


def write_report(json_path: Path, weight: float = tr.CACHE_WEIGHT) -> Path:
    matrix = json.loads(json_path.read_text(encoding="utf-8"))
    md_path = json_path.with_suffix(".md")
    with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_markdown(matrix, weight))
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
    p.add_argument("--cache-weight", type=float, default=tr.CACHE_WEIGHT,
                   help=f"weight of a cache read in effective tokens ({tr.WEIGHT_NOTE})")
    args = p.parse_args(argv)

    if args.report:
        print(f"report: {write_report(Path(args.report), args.cache_weight)}")
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
    print(f"\nmatrix: {json_path}\nreport: {write_report(json_path, args.cache_weight)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
