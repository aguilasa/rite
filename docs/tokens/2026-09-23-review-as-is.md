# Tokens of /rite:review on node-minimal — 2026-09-23

## Setup

- Example: `node-minimal`, command `/rite:review`, model `sonnet`.
- Fixes per run (N): 1, 2, 4; 1 repetition(s) each; 1 run(s) in all.
- Label `as-is`: plugin 0.4.0 at `6143762-dirty`.
- Each run: a fresh copy of the example, its tasks finished from a reference solution, N defects planted and N fixes opened through the CLI; only the command under measurement calls the model.

## Matrix

Billed = input + cache writes + output. Main thread and subagents apart.

| label | N | rep | main billed | main cache read | main turns | ceremony | agents | agent billed | agent cache read |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| as-is | 1 | 1 | 28,364 | 351,287 | 8 | 4 | 1 | 12,686 | 53,123 |

Per agent type (billed / turns / shell output bytes):

| label | N | rep | rite:rite-reviewer |
| --- | ---: | ---: | ---: |
| as-is | 1 | 1 | 1× 12,686 / 5 / 8,774 |

## Fitted line

Least squares over every valid repetition, billed tokens against N. The intercept is the fixed ceremony of an invocation; the slope is what one more fix adds. **The subagent floor is the slope of the agent side**: what the rite spends in fresh contexts per fix.

### `as-is`

- Total: n/a (fewer than two values of N).
- Main thread: n/a (fewer than two values of N).
- **Subagent floor: n/a (fewer than two values of N).**
  - `rite:rite-reviewer`: n/a (fewer than two values of N).

## Reading

- `as-is`: no floor — fewer than two values of N measured the agent side.

## Triage decision

- `as-is`: **none** — no cell measured a reproducer.

## Caveats

- 1 repetition(s) per N: the line is a trend, not a law. One repetition measures no dispersion at all.
- `as-is`: spread of total billed between repetitions — N=1: 0. Invalid runs: 0; runs with an unknown agent side: 0.
- Not controlled: the model's own variance; fixes written by the seeding harness rather than by a review (same evidence and files, plainer prose); prompt-cache state across runs.
