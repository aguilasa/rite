# Tokens of /rite:fix-all on node-minimal — 2026-09-24

## Setup

- Example: `node-minimal`, command `/rite:fix-all`, model `sonnet`.
- Fixes per run (N): 1, 2, 4; 2 repetition(s) each; 12 run(s) in all.
- Label `as-is`: plugin 0.5.0 at `79f56d7`.
- Label `inline`: plugin 0.6.0 at `f42859c`.
- Each run: a fresh copy of the example, its tasks finished from a reference solution, N defects planted and N fixes opened through the CLI; only the command under measurement calls the model.
- Effective = billed + 0.1 × cache read: w is the rate of a cache read relative to an input token, not a price. Every comparison below is in effective tokens.

## Matrix

Billed = input + cache writes + output. Main thread and subagents apart.

| label | N | rep | main billed | main cache read | main turns | ceremony | agents | agent billed | agent cache read |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| as-is | 1 | 1 | 31,771 | 603,819 | 13 | 0 | 2 | 15,711 | 48,064 |
| as-is | 1 | 2 | 32,444 | 508,397 | 11 | 0 | 2 | 11,421 | 57,335 |
| as-is | 2 | 1 | 39,664 | 856,956 | 17 | 1 | 4 | 15,734 | 74,014 |
| as-is | 2 | 2 | 39,524 | 744,983 | 15 | 1 | 4 | 20,593 | 121,093 |
| as-is | 4 | 1 | 58,047 | 1,073,993 | 18 | 0 | 8 | 41,433 | 210,714 |
| as-is | 4 | 2 | 50,229 | 887,239 | 16 | 0 | 8 | 40,835 | 238,744 |
| inline | 1 | 1 | 28,416 | 401,271 | 9 | 5 | 0 | 0 | 0 |
| inline | 1 | 2 | 27,160 | 494,300 | 11 | 5 | 0 | 0 | 0 |
| inline | 2 | 1 | 36,727 | 646,382 | 13 | 8 | 2 | 14,617 | 75,454 |
| inline | 2 | 2 | 41,736 | 707,291 | 14 | 6 | 2 | 9,815 | 61,182 |
| inline | 4 | 1 | 44,724 | 558,753 | 11 | 4 | 4 | 19,634 | 96,495 |
| inline | 4 | 2 | 43,634 | 623,874 | 12 | 3 | 4 | 28,468 | 134,775 |

Per agent type (billed / turns / shell output bytes):

| label | N | rep | rite:rite-reproducer | rite:rite-worker |
| --- | ---: | ---: | ---: | ---: |
| as-is | 1 | 1 | 1× 7,664 / 2 / 11 | 1× 8,047 / 5 / 1,910 |
| as-is | 1 | 2 | 1× 3,087 / 2 / 11 | 1× 8,334 / 5 / 365 |
| as-is | 2 | 1 | 2× 6,245 / 4 / 12 | 2× 9,489 / 7 / 1,547 |
| as-is | 2 | 2 | 2× 6,298 / 4 / 12 | 2× 14,295 / 11 / 1,941 |
| as-is | 4 | 1 | 4× 12,215 / 8 / 121 | 4× 29,218 / 19 / 3,342 |
| as-is | 4 | 2 | 4× 12,264 / 8 / 193 | 4× 28,571 / 22 / 1,490 |
| inline | 1 | 1 | — | — |
| inline | 1 | 2 | — | — |
| inline | 2 | 1 | — | 2× 14,617 / 9 / 1,198 |
| inline | 2 | 2 | — | 2× 9,815 / 8 / 707 |
| inline | 4 | 1 | — | 4× 19,634 / 13 / 4,636 |
| inline | 4 | 2 | — | 4× 28,468 / 16 / 6,402 |

## Fitted line

Least squares over every valid repetition, billed tokens against N. The intercept is the fixed ceremony of an invocation; the slope is what one more fix adds. **The subagent floor is the slope of the agent side**: what the rite spends in fresh contexts per fix.

### `as-is`

- Total: intercept 26,916, slope 16,851 per fix.
- Main thread: intercept 24,836, slope 7,333 per fix.
- **Subagent floor: intercept 2,081, slope 9,517 per fix.**
  - `rite:rite-reproducer`: intercept 2,392, slope 2,387 per fix.
  - `rite:rite-worker`: intercept -311, slope 7,130 per fix.
- Effective (w = 0.1) — main thread: intercept 71,464, slope 20,745 per fix; subagents: intercept 992, slope 15,341 per fix.

### `inline`

- Total: intercept 19,397, slope 12,754 per fix.
- Main thread: intercept 25,314, slope 5,037 per fix.
- **Subagent floor: intercept -5,918, slope 7,717 per fix.**
  - `rite:rite-worker`: intercept -5,918, slope 7,717 per fix.
- Effective (w = 0.1) — main thread: intercept 74,369, slope 8,526 per fix; subagents: intercept -8,283, slope 11,359 per fix.

## Reading

- `as-is`: each fix adds 9,517 billed tokens in subagents — `rite:rite-reproducer` 2,387, `rite:rite-worker` 7,130. An agent added to the rite takes at least its own per-call share of this on every invocation that starts it, before it does any work.
- `inline`: each fix adds 7,717 billed tokens in subagents — `rite:rite-worker` 7,717. An agent added to the rite takes at least its own per-call share of this on every invocation that starts it, before it does any work.

## Triage decision

Is a `rite:rite-reproducer` per fix dearer than running the evidence in the main thread? Judged per batch, in effective tokens (w = 0.1). The agent side is what the reproducers used. The inline side is **one** main-thread turn for the whole batch (`reproduce --all`: the run's average main turn) plus the output it holds — shell bytes / 4 as tokens, bounded by `--tail`, written once and read back on each main-thread turn that followed a reproducer's result. A side wins an N only by more than the dispersion between repetitions. The output limit is what one fix may hold inline before its own reproducer would have been cheaper.

### `as-is`

| N | reproducers (agent) | inline (1 turn per batch) | effective agent | effective inline | per fix agent | per fix inline | dispersion | side | output limit per fix |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| 1 | 5,376 billed + 8,561 cache read | 2,699 billed + 46,356 cache read | 6,232 | 7,335 | 6,232 | 7,335 | 4,132 | open | 13.2 KB |
| 2 | 6,272 billed + 21,750 cache read | 2,487 billed + 50,073 cache read | 8,447 | 7,494 | 4,223 | 3,747 | 227 | inline | 7.5 KB |
| 4 | 12,240 billed + 43,236 cache read | 3,221 billed + 58,061 cache read | 16,563 | 9,027 | 4,141 | 2,257 | 473 | inline | 7.0 KB |

**apply** — inline triage is cheaper from N = 2 up, and the gap grows with the batch; at N = 1 the difference is within the dispersion. Turn-over: N = 2. `[limits].inline_triage_max_output_kb` = 7.

### `inline`

**none** — no cell measured a reproducer.

## Labels compared

The whole invocation — main thread plus subagents — in effective tokens (w = 0.1), median per N, against `as-is`. The change counts only beyond the dispersion.

| N | `as-is` | `inline` | `inline` vs `as-is` |
| ---: | ---: | ---: | ---: |
| 1 | 106,554 ± 12,232 (12 turns, 2 agents) | 72,567 ± 8,047 (10 turns, 0 agents) | -32% |
| 2 | 147,610 ± 1,770 (16 turns, 4 agents) | 125,963 ± 4,871 (13.5 turns, 2 agents) | -15% |
| 4 | 215,806 ± 24,288 (17 turns, 8 agents) | 138,925 ± 18,084 (11.5 turns, 4 agents) | -36% |

## Caveats

- 2 repetition(s) per N: the line is a trend, not a law. Two points per N bound the noise only loosely.
- `as-is`: spread of total billed between repetitions — N=1: 3,617, N=2: 4,719, N=4: 8,416. Invalid runs: 0; runs with an unknown agent side: 0.
- `inline`: spread of total billed between repetitions — N=1: 1,256, N=2: 207, N=4: 7,744. Invalid runs: 0; runs with an unknown agent side: 0.
- Not controlled: the model's own variance; fixes written by the seeding harness rather than by a review (same evidence and files, plainer prose); prompt-cache state across runs.
- The inline side is modelled, not measured: 4 bytes per token, and the cost of its one turn is the run's average main-thread turn, while a later turn costs more than an early one.
