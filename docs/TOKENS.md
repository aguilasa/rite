# Where the tokens go

`rite tokens` (the same code as `tools/token_report.py`) reads the transcripts Claude Code writes under
`~/.claude/projects` and reports, per command, the median of each invocation: billed tokens, cache
reads, output, turns, ceremony (turns spent on the rite's own prose and CLI), the tools used — and,
apart, what its subagents used. Counts are tokens, never money. It is a tool **about** the rite: no
command calls it, and it needs no `rite.toml`.

```sh
rite tokens --glob "*slugkit*" --top 10
rite tokens --glob "*rite-node-minimal-*" --check tests/baselines/node-minimal.json
```

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
