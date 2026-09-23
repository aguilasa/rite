# Cost of /rite:review on node-minimal — 2026-09-23

## Setup

- Example: `node-minimal`, command `/rite:review`, model `sonnet`.
- Fixes per run (N): 1, 2, 4; 1 repetition(s) each; 1 run(s) in all.
- Label `as-is`: plugin 0.4.0 at `6143762-dirty`.
- Prices (USD per million tokens, from `docs/cost/prices.toml`, used on 2026-09-23): input 2.0, output 10.0, cache_write 2.5, cache_read 0.2.
- Each run: a fresh copy of the example, its tasks finished from a reference solution, N defects planted and N fixes opened through the CLI; only the command under measurement calls the model.

## Matrix

Billed = input + cache writes + output. Main thread and subagents apart.

| label | N | rep | main billed | main cache read | main turns | ceremony | agents | agent billed | agent cache read | USD main | USD agent |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| as-is | 1 | 1 | 28,364 | 351,287 | 8 | 4 | 1 | 12,686 | 53,123 | $0.1700 | $0.0548 |

Per agent type (billed / turns / shell output bytes):

| label | N | rep | rite:rite-reviewer |
| --- | ---: | ---: | ---: |
| as-is | 1 | 1 | 1× 12,686 / 5 / 8,774 |

## Fitted line

Least squares over every valid repetition, billed tokens against N. The intercept is the fixed ceremony of an invocation; the slope is what one more fix costs. **The subagent floor is the slope of the agent side**: what the rite spends in fresh contexts per fix.

### `as-is`

- Total: n/a (fewer than two values of N).
- Main thread: n/a (fewer than two values of N).
- **Subagent floor: n/a (fewer than two values of N).**
  - `rite:rite-reviewer`: n/a (fewer than two values of N).
- In dollars — total: n/a (fewer than two values of N); **agent: n/a (fewer than two values of N)**.
  - `rite:rite-reviewer`: n/a (fewer than two values of N).

## Reading

- `as-is`: no floor — fewer than two values of N measured the agent side.

## Triage decision

Is a `rite:rite-reproducer` per fix dearer than running its evidence in the main thread? Inline, the main thread pays twice: for holding the output (estimated: bytes / 4 as tokens, written once, then read from cache on every later turn) and for the turns spent running the commands, which only a run with inline triage can count. Each N is judged with no extra turn and with one extra turn per fix; the break-even is the number of main-thread turns per fix at which both cost the same.

- `as-is`: **none** — no cell measured a reproducer.

## Caveats

- 1 repetition(s) per N: the line is a trend, not a law. One repetition measures no dispersion at all.
- `as-is`: spread of total billed between repetitions — N=1: 0. Invalid runs: 0; runs with an unknown agent side: 0.
- Not controlled: the model's own variance; fixes written by the seeding harness rather than by a review (same evidence and files, plainer prose); prompt-cache state across runs; the price table's date.
- The inline estimate assumes 4 bytes per token and that the output would be held until the end of the invocation. The cost of one main-thread turn is the run's main-thread dollars divided by its turns: an average, while a later turn costs more than an early one.
