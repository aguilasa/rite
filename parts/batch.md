## Batches — waves, workers, serial commits

A batch relaxes one rule only: more than one item per invocation. Evidence, guards, sweep and two
commits per item still hold per item; `batch-plan` builds the waves.

**Plan.** `rite batch-plan <count|IDs> --kind <task|fix> --cycle <cycle> --json`. An item whose `files`
is empty or inferred runs alone, so read it, record its predicted paths with `rite set <ID> --files …
[--resources …]` — never any other field — and plan again. Show items, conflict pairs and waves; with
`--plan`, stop and commit those edits (`chore(rite): plan batch <IDs>`). With `--plan`, only planning
fields (`files`, `resources`) are written; status, dates, SHAs and the Execution Log never are: a plan
decides no item's fate.

**Each wave.**

1. `rite begin <kind> --id <ID>` per item; then one `rite:rite-worker` agent per item, **in parallel,
   in one message**, each given the payload of `rite context <ID> --json`, its repository, its allowed
   `files`, the serialized resources assigned to it (one worker per resource) and the gates it may run.
2. For each report, `git status --porcelain` must show only that item's allowed files; a stray file is
   a failure of that item.
3. `rite gates --cycle <cycle> --json` once, on the combined tree. Red → abort the wave: commit
   nothing, items stay `in-progress`; report the output with each item's files. Still red with the
   wave's edits stashed (`git stash -u`, gates, `git stash pop`) → the defect predates the wave: open
   a `high` fix with that output as Evidence (`rite new-fix`, `rite commit-new`).
4. **Serially, in item order**, for each DONE item: set the later items' files aside (`git stash push
   -u -- <their files>`), `rite gates --id <ID> --json` — its commit is this tree: the only gate
   result its Notes record — stage exactly its files, work commit with the references from `rite
   begin`, `rite finish <ID> --json`, `git stash pop`. Red → stop committing: it and the later items
   stay `in-progress`; report.
5. STALE → `rite mark-stale`; BLOCKED → `rite mark <ID> blocked --reason "…" --commit` (a fix adds
   `--unblocked-by "<command>"`); one failure does not stop the batch. Forwarded notes go into the
   destination items' Notes, committed together.
