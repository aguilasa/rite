# Tokens of /rite:fix-all on node-minimal — 2026-09-23

## Setup

- Example: `node-minimal`, command `/rite:fix-all`, model `sonnet`.
- Fixes per run (N): 1, 2, 4; 2 repetition(s) each; 6 run(s) in all.
- Label `as-is`: plugin 0.4.0 at `6143762`.
- Each run: a fresh copy of the example, its tasks finished from a reference solution, N defects planted and N fixes opened through the CLI; only the command under measurement calls the model.
- Effective = billed + 0.1 × cache read: w is the rate of a cache read relative to an input token, not a price. Every comparison below is in effective tokens.

## Matrix

Billed = input + cache writes + output. Main thread and subagents apart.

| label | N | rep | main billed | main cache read | main turns | ceremony | agents | agent billed | agent cache read |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| as-is | 1 | 1 | 28,825 | 398,001 | 9 | 5 | 2 | 20,744 | 44,272 |
| as-is | 1 | 2 | 27,900 | 396,663 | 9 | 5 | 2 | 10,015 | 44,356 |
| as-is | 2 | 1 | 37,398 | 799,396 | 16 | 7 | 4 | 20,276 | 109,824 |
| as-is | 2 | 2 | 43,765 | 875,351 | 17 | 7 | 4 | 20,093 | 107,383 |
| as-is | 4 | 1 | 55,696 | 830,000 | 15 | 6 | 8 | 36,492 | 210,210 |
| as-is | 4 | 2 | 61,424 | 1,207,888 | 20 | 8 | 8 | 36,074 | 165,683 |

Per agent type (billed / turns / shell output bytes):

| label | N | rep | rite:rite-reproducer | rite:rite-worker |
| --- | ---: | ---: | ---: | ---: |
| as-is | 1 | 1 | 1× 7,572 / 2 / 11 | 1× 13,172 / 5 / 1,899 |
| as-is | 1 | 2 | 1× 3,082 / 2 / 11 | 1× 6,933 / 4 / 824 |
| as-is | 2 | 1 | 2× 6,076 / 4 / 12 | 2× 14,200 / 10 / 2,397 |
| as-is | 2 | 2 | 2× 6,039 / 4 / 12 | 2× 14,054 / 10 / 719 |
| as-is | 4 | 1 | 4× 12,080 / 8 / 193 | 4× 24,412 / 20 / 2,512 |
| as-is | 4 | 2 | 4× 12,120 / 8 / 113 | 4× 23,954 / 15 / 1,797 |

## Fitted line

Least squares over every valid repetition, billed tokens against N. The intercept is the fixed ceremony of an invocation; the slope is what one more fix adds. **The subagent floor is the slope of the agent side**: what the rite spends in fresh contexts per fix.

### `as-is`

- Total: intercept 26,703, slope 17,034 per fix.
- Main thread: intercept 19,373, slope 9,912 per fix.
- **Subagent floor: intercept 7,330, slope 7,122 per fix.**
  - `rite:rite-reproducer`: intercept 2,306, slope 2,367 per fix.
  - `rite:rite-worker`: intercept 5,024, slope 4,756 per fix.
- Effective (w = 0.1) — main thread: intercept 50,028, slope 28,969 per fix; subagents: intercept 7,795, slope 11,793 per fix.

## Reading

- `as-is`: each fix adds 7,122 billed tokens in subagents — `rite:rite-reproducer` 2,367, `rite:rite-worker` 4,756. An agent added to the rite takes at least its own per-call share of this on every invocation that starts it, before it does any work.

## Triage decision

- `as-is`: **none** — not judged: the verdict in tokens is not written yet.

## Caveats

- 2 repetition(s) per N: the line is a trend, not a law. Two points per N bound the noise only loosely.
- `as-is`: spread of total billed between repetitions — N=1: 11,654, N=2: 6,184, N=4: 5,310. Invalid runs: 0; runs with an unknown agent side: 0.
- Not controlled: the model's own variance; fixes written by the seeding harness rather than by a review (same evidence and files, plainer prose); prompt-cache state across runs.
