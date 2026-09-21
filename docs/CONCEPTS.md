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
   /rite:fix-all ─► parallel read-only triage, then waves
                                   │
   /rite:close-cycle ─► archive ─► /rite:retro ─► pitfalls kept, rules promoted, rite issues reported
```

## Four layers

Each layer knows only what is its own. The rite never names a project, a path, a tool or an ID.

| Layer | Where | Holds |
| --- | --- | --- |
| **Rite** | the plugin: `commands/`, `shared/`, `agents/` | the generic procedure: selection, order, evidence, commits |
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
