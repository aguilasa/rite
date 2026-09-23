# Cost of /rite:fix-all on node-minimal — 2026-09-23

## Setup

- Example: `node-minimal`, command `/rite:fix-all`, model `sonnet`.
- Fixes per run (N): 1, 2, 4; 2 repetition(s) each; 6 run(s) in all.
- Label `as-is`: plugin 0.4.0 at `6143762`.
- Prices (USD per million tokens, from `docs/cost/prices.toml`, used on 2026-09-23): input 2.0, output 10.0, cache_write 2.5, cache_read 0.2.
- Each run: a fresh copy of the example, its tasks finished from a reference solution, N defects planted and N fixes opened through the CLI; only the command under measurement calls the model.

## Matrix

Billed = input + cache writes + output. Main thread and subagents apart.

| label | N | rep | main billed | main cache read | main turns | ceremony | agents | agent billed | agent cache read | USD main | USD agent |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| as-is | 1 | 1 | 28,825 | 398,001 | 9 | 5 | 2 | 20,744 | 44,272 | $0.1774 | $0.0717 |
| as-is | 1 | 2 | 27,900 | 396,663 | 9 | 5 | 2 | 10,015 | 44,356 | $0.1722 | $0.0410 |
| as-is | 2 | 1 | 37,398 | 799,396 | 16 | 7 | 4 | 20,276 | 109,824 | $0.2867 | $0.0892 |
| as-is | 2 | 2 | 43,765 | 875,351 | 17 | 7 | 4 | 20,093 | 107,383 | $0.3259 | $0.0878 |
| as-is | 4 | 1 | 55,696 | 830,000 | 15 | 6 | 8 | 36,492 | 210,210 | $0.3643 | $0.1727 |
| as-is | 4 | 2 | 61,424 | 1,207,888 | 20 | 8 | 8 | 36,074 | 165,683 | $0.4753 | $0.1544 |

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

Least squares over every valid repetition, billed tokens against N. The intercept is the fixed ceremony of an invocation; the slope is what one more fix costs. **The subagent floor is the slope of the agent side**: what the rite spends in fresh contexts per fix.

### `as-is`

- Total: intercept 26,703, slope 17,034 per fix.
- Main thread: intercept 19,373, slope 9,912 per fix.
- **Subagent floor: intercept 7,330, slope 7,122 per fix.**
  - `rite:rite-reproducer`: intercept 2,306, slope 2,367 per fix.
  - `rite:rite-worker`: intercept 5,024, slope 4,756 per fix.
- In dollars — total: intercept $0.1369, slope $0.1141 per fix; **agent: intercept $0.0188, slope $0.0360 per fix**.
  - `rite:rite-reproducer`: intercept $0.0061, slope $0.0101 per fix.
  - `rite:rite-worker`: intercept $0.0127, slope $0.0259 per fix.

## Reading

- `as-is`: each fix adds 7,122 billed tokens in subagents ($0.0360) — `rite:rite-reproducer` 2,367, `rite:rite-worker` 4,756. An agent added to the rite costs at least its own per-call share of this on every invocation that starts it, before it does any work.

## Triage decision

Is a `rite:rite-reproducer` per fix dearer than running its evidence in the main thread? Inline, the main thread pays twice: for holding the output (estimated: bytes / 4 as tokens, written once, then read from cache on every later turn) and for the turns spent running the commands, which only a run with inline triage can count. Each N is judged with no extra turn and with one extra turn per fix; the break-even is the number of main-thread turns per fix at which both cost the same.

- `as-is`: **inconclusive** — inline triage is cheaper only if it adds fewer than 0.49–0.90 main-thread turns per fix, which this matrix does not measure; apply it and measure the turns.
  - N=1: reproducer $0.0175 per fix; output held inline $0.0000 per fix; one main-thread turn $0.0194; break-even 0.90 turns per fix; dispersion $0.0104.
  - N=2: reproducer $0.0121 per fix; output held inline $0.0000 per fix; one main-thread turn $0.0185; break-even 0.65 turns per fix; dispersion $0.0004.
  - N=4: reproducer $0.0118 per fix; output held inline $0.0000 per fix; one main-thread turn $0.0240; break-even 0.49 turns per fix; dispersion $0.0003.

## Caveats

- 2 repetition(s) per N: the line is a trend, not a law. Two points per N bound the noise only loosely.
- `as-is`: spread of total billed between repetitions — N=1: 11,654, N=2: 6,184, N=4: 5,310. Invalid runs: 0; runs with an unknown agent side: 0.
- Not controlled: the model's own variance; fixes written by the seeding harness rather than by a review (same evidence and files, plainer prose); prompt-cache state across runs; the price table's date.
- The inline estimate assumes 4 bytes per token and that the output would be held until the end of the invocation. The cost of one main-thread turn is the run's main-thread dollars divided by its turns: an average, while a later turn costs more than an early one.
