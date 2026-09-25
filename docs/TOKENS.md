# Where the tokens go

`rite tokens` (the same code as `tools/token_report.py`) reads the transcripts Claude Code writes under
`~/.claude/projects` and reports where the tokens went — all of Claude Code's usage, not only the
rite's. Counts are tokens, never money. It is a diagnostic, not a rite: no command calls it, and it
needs no `rite.toml`.

```sh
rite tokens                                             # per command, medians per invocation
rite tokens --by day --since 2026-09-01 --markdown usage.md
rite tokens --project "*slugkit*" --top 10
rite tokens --project "*rite-node-minimal-*" --latest --check tests/baselines/node-minimal.lifecycle.json
rite tokens --project "*my-repo*" --suggest-limits      # this repository's inline-triage limit
```

`--project` with a glob sums every run it matches — every run, of every version. To compare with a
baseline, measure one run: `--dir` of its project folder, or `--latest`. A baseline records its scope
(sessions, project folders), and `--check` on a measurement that spans more fails on scope (exit 3)
before comparing a number. There is one baseline per e2e script and example: `<example>.loop.json`,
`<example>.lifecycle.json`.

## Invocations and rows

A transcript is cut into invocations: a slash command — any plugin's or skill's, under its own name —
or a plain prompt, which is the row `(no command)`. Everything the model does after one belongs to it
until the next. Text the harness injects (a command's own prose, a task notification) does not cut it.
Both doors into a command count, under the same name: typed (`<command-name>`) and through the
`Skill` tool (a pasted instruction, a model-invoked skill) — a typed command followed by its own
`Skill` call is one invocation; through `Skill`, the turns before the call stay in `(no command)`.

| Flag | What it does |
| --- | --- |
| `--by command\|session\|day\|project\|agent` | what a row is (default `command`) |
| `--since D` / `--until D` | only invocations whose first entry falls in the window (UTC days, inclusive) |
| `--project GLOB` | only transcripts whose path matches (`--glob` is the same flag) |
| `--latest` | only the project folder written last among those matched: one run, not their sum |
| `--command C` | only these commands (repeatable) |
| `--top N` | the N largest tool results: size, tool, target — never the text |
| `--markdown FILE` | also write the report as deterministic markdown |
| `--json`, `--check B`, `--tolerance P` | machine output; compare with a baseline (per command only) |
| `--cache-weight W` | the weight of a cache read in `effective` (default `0.1`) |
| `--suggest-limits` | instead of the report, the `[limits].inline_triage_max_output_kb` the window supports ([below](#the-inline-triage-limit)) |

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

## The inline-triage limit

`/rite:fix-all` triages inline — one main-thread turn runs every fix's evidence — and hands a fix to a
`rite-reproducer` only when its output is over `[limits].inline_triage_max_output_kb`. Where that line
sits depends on the repository: a fresh context there carries its profile, plan and documents, and a
main-thread turn re-reads a context that grows with them. `--suggest-limits` measures both from the
window's `/rite:fix-all` runs and prints the limit per batch size N (1, 2, 4):

    budget   = agent_effective - main_turn_effective / N
    limit_kb = budget / (1 + w × turns_after) × 4 / 1024

`agent_effective` is a reproducer (median billed and median cache reads, weighed), `main_turn_effective`
a main-thread turn of `/rite:fix-all` (the same, per turn), `turns_after` the median number of
main-thread turns that carried a reproducer's result — what held output is read back on. 4 bytes per
token is rough, and said so. When the budget is not positive the agent wins whatever the output. The
recommendation is the N = 1 value (a larger batch allows more); when the agent always wins there, the
smallest N that has a budget. Fewer than 3 measured reproducers, or no `/rite:fix-all` in the window,
give `insufficient data` naming what is missing (exit 2). The output states its scope; `--project`,
`--since`, `--until` and `--latest` cut the window as for the report, and `--json` has the raw inputs,
the limit per N and the weight. Measured on 2026-09-25:
[tokens/2026-09-25-inline-triage-limit.md](tokens/2026-09-25-inline-triage-limit.md).

## What is kept

Metrics only: token counts, turn counts, sizes of tool results, tool names and their targets (a
path, a command line). Never the text a tool read or returned, and never a message. `--top` lists
the largest tool results by size, tool and target — not their content.
