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
    args = p.parse_args(argv)

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
    print(f"\nmatrix: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
