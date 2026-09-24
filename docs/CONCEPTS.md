# Concepts

## The loop

```
plan ──/rite:plan-to-tasks──► tasks (one file each) + progress.md + profile
                                   │
   /rite:execute ─► 1 task ─► work commit ─► rite close (bookkeeping commit) ─► reviewed_on: pending
   /rite:execute-batch N ─► N tasks in conflict-free waves
                                   │
   /rite:review ─► rite-reviewer agent measures (does not read) the oldest task awaiting review
                   ─► fixes + reviewed_on: <date>, one commit
                                   │
   /rite:fix ─► reproduce evidence ─► repair ─► sweep ─► close        (or: stale, symptom gone)
   /rite:fix-all ─► inline triage, agents for the residue, then waves
                                   │
   /rite:close-cycle ─► archive ─► /rite:retro ─► pitfalls kept, rules promoted, rite issues reported
```

## Four layers

Each layer knows only what is its own. The rite never names a project, a path, a tool or an ID.

| Layer | Where | Holds |
| --- | --- | --- |
| **Rite** | the plugin: `commands/` (assembled from `parts/`), `agents/` | the generic procedure: selection, order, evidence, commits |
| **Repo config** | `rite.toml` | folders, naming, languages, commit policy, guarded paths, generators, global gates, serialized resources |
| **Cycle profile** | `<profiles_dir>/<cycle>.md` + pitfalls file | confirmed decisions, sources of truth, cycle gates, hot files, pull-ahead precedents, phase-specific checks; dated pitfalls live in the pitfalls file, searched on demand |
| **Item** | task / fix file | scope, `source_of_truth`, done criteria, execution log |

## Cycles

A **cycle** is a folder holding a progress file. Its tasks and fixes live in it, one file per item.
`depends_on` never crosses cycles. A cycle's `prefix` is in every ID it allocates. Tasks run in ID
order, or in the order the progress file's `order:` lists. Closed cycles move to the archive folder and
keep their history (`git mv`).

## State

- **Frontmatter is the only state.** `status`, `done_on`, `done_commit`, `reviewed_on`,
  `review_commit` are written by the CLI only.
- **Tables are views.** `progress.md` and `fixes.md` contain a generated region between
  `<!-- rite:begin … -->` and `<!-- rite:end -->`; the rest is free text. `rite sync` regenerates the
  region; `rite check` fails when it is stale.
- **Vocabulary is closed**: task status `pending | in-progress | done | blocked | skipped`; fix status
  `pending | in-progress | done | stale`; severity `critical | high | medium | low`;
  `reviewed_on` is `null` (not reviewable), `pending`, or a date.

## Two commits per item

The work commit (`feat: …`, `fix: …`) carries code, docs and the item's prose. Then `rite close <ID>`
reads that commit and writes `done_on` (the commit's date), `done_commit`, and the file list from git,
and commits that as `chore(rite): close <ID>`. A commit cannot contain its own SHA, so the record is
a second commit — and it is always consistent with the first.

Work commits name what they belong to with trailers from `rite commit-refs <ID>`: `Refs: <ID>`, and
the cycle's `ticket` if it has one (see `[commit].ticket_format`).

A squash or rebase rewrites the work commit and leaves `done_commit` pointing at a commit outside
HEAD's history; `rite check` warns (errors once the old commit is gone) and `rite rebind <ID> --sha
<commit>` repoints it without reopening the item or its review.

Some items have no work commit: their only artifact is a document outside git, such as a workspace
document. `rite close <ID> --no-repo --reason "…"` (or `finish`) records `done_commit: none`, dates the
item today and puts the reason in its Execution Log; `check` accepts the sentinel instead of resolving
it. Never borrow HEAD for such an item, and never write the fields by hand. If a work commit turns up
later, `rebind` attaches it.

## Local cycles

Some work is planned only for yourself: the code goes to the repository, the tasks never do.
`local: true` in the progress file's frontmatter (`rite new-cycle --local`) makes such a cycle:

- **State is unchanged.** Status, dates and `done_commit` are in the item files as always, and
  `next`, `status`, review and fix selection read them the same way. The CLI never took state from git.
- **No bookkeeping commits.** `close`, `mark-reviewed`, `mark-stale`, `mark --commit`, `commit-new`,
  `new-cycle --commit` and `archive` write the files and commit nothing (`"commit": null,
  "local": true`). `close` still reads the work commit — that is code, and it is in the repository.
- **No `Refs: <ID>`** in work commits: the ID would name a file nobody else has. The ticket, if any,
  stays — the tracker is outside the repository.
- **Keep the documents ignored.** Add the cycle folder, its profile and pitfalls file (and the archive
  folder) to `.gitignore`; `rite check` warns when a local cycle is not ignored, and when an ignored
  one is not local (its bookkeeping commits would fail).
- **No backup.** The documents live only on your disk; losing them loses the cycle's history, not the
  code. `rite publish <cycle>` turns a local cycle into a tracked one — `local: false` and one commit
  with its documents — once you have removed its `.gitignore` lines.

## Workspaces

`rite.toml` may sit in a plain folder that holds several git repositories — one plan for two
projects, say. Rite detects it (the root is not a git repository) and runs in workspace mode:

- **Every item names its repository** in `repo:` — `rite new-task --repo api`; a fix inherits its
  origin's. `check` reports an item without one and lists the repositories found.
- `close`, `rebind`, `mark-reviewed` and `mark-stale` read commits and HEAD in that repository;
  `check` resolves each `done_commit` there. Commit the work inside it (`git -C api commit`).
- **Every cycle is local**: the documents live in the workspace folder, outside every repository, and
  no bookkeeping commit is made. There is nothing to `publish` to.
- **One item, one repository.** Work spanning two becomes two items; `/rite:plan-to-tasks` splits it.
- `batch-plan` reads `files:` relative to each item's repository, so the same path in two
  repositories is not a conflict.

## Engineering disciplines

- **Measure, do not read.** Logs and ticked boxes are leads; only commands run now count.
- **Every number has a tool** versioned in the repository.
- **Control before test**: show a checker can fail before trusting it.
- **Reproduce before fixing**; a fix whose symptom is gone is **stale**, not fixed.
- **Fix the generator, not the generated.** The guard hook enforces it.
- **Negative results are results.**
- **Discrepancy sweep** after every item: grep what you changed across docs, config and other items.

## Batches

A batch relaxes one rule — more than one item per invocation — and nothing else. Items share a wave
only when they share no file, no serialized resource and no dependency. Workers (subagents) edit; the
main thread commits, one item at a time. Default size 2; never "all" for tasks.

## Delegation cost

A subagent is a fresh context: it pays for reading its payload again, but not for the main thread's
history. Everything here is in tokens; where two sides are compared the unit is
`effective = billed + 0.1 × cache read` — the weight is the rate of a cache read relative to an input
token, not a price. Measured on `node-minimal` with Sonnet 5 (`tools/experiment.py`, report in
[tokens/2026-09-23-fixall-as-is.md](tokens/2026-09-23-fixall-as-is.md)), one more fix in `/rite:fix-all`
adds:

| | Billed tokens |
| --- | ---: |
| main thread | 9,912 |
| **subagents (the floor)** | **7,122** |
| `rite-reproducer` | 2,367 |
| `rite-worker` | 4,756 |
| all | 17,034 |

A `/rite:review` (the control) spends 12,686 billed tokens in its reviewer.

**The rule: delegate work that would cost the main thread more than a fresh context does.** A fresh
context is paid per call; a main-thread turn is paid on a context that keeps growing, but one turn
can serve many items.

Applied to the `/rite:fix-all` triage — reproducers per batch against **one** main-thread turn that
runs `rite reproduce --all` and holds its output (effective tokens, medians of two repetitions):

| N | reproducers (agent) | inline (1 turn per batch) | effective agent | effective inline |
| ---: | --- | --- | ---: | ---: |
| 1 | 5,327 billed + 8,556 cache read | 3,154 billed + 44,162 cache read | 6,183 | 7,570 |
| 2 | 6,058 + 21,572 | 2,459 + 50,764 | 8,215 | **7,535** |
| 4 | 12,100 + 43,164 | 3,430 + 58,355 | 16,416 | **9,266** |

**Inline wins from N = 2 up, and the gap grows with the batch**: one turn serves the whole batch while
the agents multiply a fresh context per fix. At N = 1 the agent is ahead, but within the dispersion
between repetitions, so the rule is stated from N = 2. What the main thread holds is the output: past
about 7 KB per fix, holding it costs more than that fix's reproducer, hence
`[limits].inline_triage_max_output_kb = 6`. So the triage is **inline by default, at any batch size;
an agent only for the residue** — no command, output over the limit, `CANNOT RUN`, or an output that
does not decide.

`rite tokens` (`tools/token_report.py`) reports the agent side apart, per agent type. With the agent
fields in a baseline, `--check` fails on one agent more than the baseline, whatever the tolerance, so
a new agent in the rite shows up in the gate.
