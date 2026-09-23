# Tokens of /rite:fix-all on node-minimal — 2026-09-23

## Setup

- Example: `node-minimal`, command `/rite:fix-all`, model `sonnet`.
- Fixes per run (N): 1, 2, 4; 2 repetition(s) each; 7 run(s) in all.
- Label `as-is`: plugin 0.4.0 at `abc1234`.
- Each run: a fresh copy of the example, its tasks finished from a reference solution, N defects planted and N fixes opened through the CLI; only the command under measurement calls the model.

## Matrix

Billed = input + cache writes + output. Main thread and subagents apart.

| label | N | rep | main billed | main cache read | main turns | ceremony | agents | agent billed | agent cache read |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| as-is | 1 | 1 | 45,000 | 1,050,000 | 21 | 14 | 2 | 25,800 | 109,000 |
| as-is | 1 | 2 | 46,000 | 1,050,000 | 21 | 14 | 2 | 26,500 | 109,000 |
| as-is | 2 | 1 | 50,000 | 1,200,000 | 24 | 14 | 4 | 51,600 | 218,000 |
| as-is | 2 | 2 | 51,000 | 1,200,000 | 24 | 14 | 4 | 53,000 | 218,000 |
| as-is | 4 | 1 | 60,000 | 1,500,000 | 30 | 14 | 8 | 103,200 | 436,000 |
| as-is | 4 | 2 | 61,000 | 1,500,000 | 30 | 14 | 8 | 106,000 | 436,000 |
| as-is | 4 | 3 | invalid: 3 open fixes before the run, 4 planted | | | | | | |

Per agent type (billed / turns / shell output bytes):

| label | N | rep | rite:rite-reproducer | rite:rite-worker |
| --- | ---: | ---: | ---: | ---: |
| as-is | 1 | 1 | 1× 6,800 / 3 / 120 | 1× 19,000 / 7 / 2,000 |
| as-is | 1 | 2 | 1× 7,000 / 3 / 120 | 1× 19,500 / 7 / 2,000 |
| as-is | 2 | 1 | 2× 13,600 / 6 / 240 | 2× 38,000 / 14 / 4,000 |
| as-is | 2 | 2 | 2× 14,000 / 6 / 240 | 2× 39,000 / 14 / 4,000 |
| as-is | 4 | 1 | 4× 27,200 / 12 / 480 | 4× 76,000 / 28 / 8,000 |
| as-is | 4 | 2 | 4× 28,000 / 12 / 480 | 4× 78,000 / 28 / 8,000 |

## Fitted line

Least squares over every valid repetition, billed tokens against N. The intercept is the fixed ceremony of an invocation; the slope is what one more fix adds. **The subagent floor is the slope of the agent side**: what the rite spends in fresh contexts per fix.

### `as-is`

- Total: intercept 40,500, slope 31,150 per fix.
- Main thread: intercept 40,500, slope 5,000 per fix.
- **Subagent floor: intercept 0, slope 26,150 per fix.**
  - `rite:rite-reproducer`: intercept 0, slope 6,900 per fix.
  - `rite:rite-worker`: intercept 0, slope 19,250 per fix.

## Reading

- `as-is`: each fix adds 26,150 billed tokens in subagents — `rite:rite-reproducer` 6,900, `rite:rite-worker` 19,250. An agent added to the rite takes at least its own per-call share of this on every invocation that starts it, before it does any work.

## Triage decision

- `as-is`: **none** — not judged: the verdict in tokens is not written yet.

## Caveats

- 2 repetition(s) per N: the line is a trend, not a law. Two points per N bound the noise only loosely.
- `as-is`: spread of total billed between repetitions — N=1: 1,700, N=2: 2,400, N=4: 3,800. Invalid runs: 1; runs with an unknown agent side: 0.
- Not controlled: the model's own variance; fixes written by the seeding harness rather than by a review (same evidence and files, plainer prose); prompt-cache state across runs.
