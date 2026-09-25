# The inline-triage limit, measured per repository — 2026-09-25

## Setup

- Rite 0.10.1 plus `rite tokens --suggest-limits` (`4c90bc8`). No model call: the numbers are read
  from transcripts already on disk.
- Two histories of `/rite:fix-all`: `new-we2002-editor`, a real repository (14 invocations,
  22 `rite-reproducer` runs, 54 sessions in 9 project folders), and the `node-minimal` e2e lab
  (26 invocations, 33 reproducers, 109 sessions in 27 project folders).
- Effective = billed + 0.1 × cache read: w is the rate of a cache read relative to an input token,
  not a price. Medians of billed and of cache reads, then weighed.

```sh
rite tokens --project "*new-we2002-editor*" --suggest-limits
rite tokens --project "*rite-node-minimal*" --suggest-limits
```

## Inputs

| | `new-we2002-editor` | `node-minimal` |
| --- | ---: | ---: |
| reproducer, effective | **85,420** | **4,159** |
| &nbsp;&nbsp;billed + cache read | 54,745 + 306,748 | 3,079 + 10,807 |
| main-thread turn, effective | **20,698** | **7,947** |
| &nbsp;&nbsp;billed + cache read | 2,598 + 181,000 | 2,901 + 50,464 |
| main-thread turns after a reproducer's result (median) | 25 | 12 |

A reproducer costs **20× more** in the real repository: a fresh context there carries its profile,
plan and large documents. A main-thread turn costs 2.6× more, because it re-reads 181,000 cached
tokens per turn against 50,464.

## Formula

Inline, **one** main-thread turn runs the evidence of the whole batch, so its cost divides by N; the
output it holds is written once and read back on every main-thread turn after it.

```
budget   = agent_effective - main_turn_effective / N
tokens   = budget / (1 + w * turns_after)
limit_KB = tokens * 4 / 1024          # 4 bytes per token, rough
```

## Break-even per batch size

Output one fix may hold inline before its own reproducer would have been cheaper:

| N | `new-we2002-editor` | `node-minimal` |
| ---: | ---: | ---: |
| 1 | 72.2 KB | agent always wins |
| 2 | 83.8 KB | 0.3 KB |
| 4 | 89.6 KB | 3.9 KB |

`--suggest-limits` recommends `inline_triage_max_output_kb = 72` for `new-we2002-editor` (the N = 1
value, which holds for any batch) and `1` for `node-minimal` (N = 2: below it a reproducer is cheaper
whatever the output).

## Reading

**No fixed number is right for both.** At the shipped 7 KB, the real repository sends to an
85,000-token agent a reproduction that would cost about 20,000 inline; in the lab the same 7 KB is
close to right. The limit is a property of the repository, measured — not a constant of the plugin.

**What changes in practice:** the default stays 7 (raising it blind would trade one wrong number for
another), its comment says it is the example's, and a repository puts in its `rite.toml` the value
`rite tokens --suggest-limits` measures from its own `/rite:fix-all` history.

## Caveats

- The inline side is modelled, not measured: 4 bytes per token, and the one turn costs the median
  main-thread turn of `/rite:fix-all`, while a later turn costs more than an early one.
- A glob sums every run it matches: the lab figure spans 27 runs of several plugin versions.
- Medians are taken per quantity (billed, cache reads) and then weighed. The median of each
  invocation's effective per turn would put the real repository's main-thread turn at 23,739 and the
  N = 1 limit at about 69 KB — the same order of magnitude, which is the finding.
