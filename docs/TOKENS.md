# Where the tokens go

`rite tokens` (the same code as `tools/token_report.py`) reads the transcripts Claude Code writes under
`~/.claude/projects` and reports where the tokens went — all of Claude Code's usage, not only the
rite's. Counts are tokens, never money. It is a diagnostic, not a rite: no command calls it, and it
needs no `rite.toml`.

```sh
rite tokens                                             # per command, medians per invocation
rite tokens --by day --since 2026-09-01 --markdown usage.md
rite tokens --project "*slugkit*" --top 10
rite tokens --project "*rite-node-minimal-*" --check tests/baselines/node-minimal.json
```

## Invocations and rows

A transcript is cut into invocations: a slash command — any plugin's or skill's, under its own name —
or a plain prompt, which is the row `(no command)`. Everything the model does after one belongs to it
until the next. Text the harness injects (a command's own prose, a task notification) does not cut it.

| Flag | What it does |
| --- | --- |
| `--by command\|session\|day\|project\|agent` | what a row is (default `command`) |
| `--since D` / `--until D` | only invocations whose first entry falls in the window (UTC days, inclusive) |
| `--project GLOB` | only transcripts whose path matches (`--glob` is the same flag) |
| `--command C` | only these commands (repeatable) |
| `--top N` | the N largest tool results: size, tool, target — never the text |
| `--markdown FILE` | also write the report as deterministic markdown |
| `--json`, `--check B`, `--tolerance P` | machine output; compare with a baseline (per command only) |
| `--cache-weight W` | the weight of a cache read in `effective` (default `0.1`) |

By command a row holds **medians** per invocation: one long invocation must not decide the number a
baseline is compared to. By session, day or project a row is a period, so it holds **totals**. By
agent there is one row for the main thread and one per agent type, totals too. Each row: `n`,
`turns`, the four counts, `billed`, `effective`, `ceremony` (tool calls on the rite's own prose and
CLI), `agents`, and the subagents' billed tokens and cache reads, with one line per agent type.

The **Totals** block sums the window: main thread and subagents apart, all of it in effective tokens,
the share that went to subagents, and how many tool calls were ceremony.

## The unit

Four counts are printed apart: `input`, `cache_write`, `cache_read`, `output`, then `billed`
(input + cache writes + output) and `turns`. Adding a cache read to the rest would hide that it is
an order of magnitude cheaper. So every comparison uses one number:

    effective = billed + w × cache_read

`w` is `--cache-weight` (default `0.1`): the rate of a cache read relative to an input token — a
ratio of rates, not a price. It is printed next to every effective number.

## Main thread and subagents

Every number at the top level is the main thread. A subagent (`rite-worker`, `rite-reviewer`,
`rite-reproducer`) runs in its own context, and its turns are billed too; Claude Code writes them
next to the session, in `<session>/subagents/agent-<id>.jsonl`, with a `.meta.json` naming the
`Agent` call that started it. Those tokens go to the invocation that made the call, reported as
`agents` (how many were started) and `agent` (billed, cache reads, output, turns, and the same per
agent type). Older transcripts that keep subagent turns inline (`isSidechain`) are attributed by
their `parentUuid` chain.

When a call left no trace of its agent, the command's `agent` is `"unknown"` — a gap declared, never
a zero that makes delegation look free. `--check` fails on it, as it fails on one agent more than the
baseline, whatever the tolerance: a new agent in the rite shows up in the gate.

The `usage` a main-thread `Agent` result carries is the agent's **last** turn, not its total; the
report sums the agent's own transcript instead.

## What is kept

Metrics only: token counts, turn counts, sizes of tool results, tool names and their targets (a
path, a command line). Never the text a tool read or returned, and never a message. `--top` lists
the largest tool results by size, tool and target — not their content.
