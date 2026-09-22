## Batches — waves, workers, serial commits

A batch relaxes one rule only: more than one item per invocation. Evidence, guards, sweep and two
commits per item still hold per item. Items share a wave only when they share no file, no serialized
resource and no dependency; when the dependency graph and the conflict matrix disagree, the matrix wins.

**Plan.** `rite batch-plan <count|IDs> --kind <task|fix> --cycle <cycle> --json`. An item whose `files`
is empty or inferred runs alone, so read it, write its predicted paths into its `files:` (and
`resources:`) planning fields — never the state fields — and plan again. Show items, conflict pairs
and waves; with `--plan`, stop and commit those edits (`chore(rite): plan batch <IDs>`).

**Each wave.**

1. `rite begin <kind> --id <ID>` per item; then one `rite:rite-worker` agent per item, **in parallel,
   in one message**, each given the payload of `rite context <ID> --json`, its repository, its allowed
   `files`, the serialized resources assigned to it (one worker per resource) and the gates it may run.
2. For each report, `git status --porcelain` must show only that item's allowed files; a stray file is
   a failure of that item.
3. `rite gates --cycle <cycle> --json` once, on the combined tree. Red → abort the wave: commit
   nothing, leave the items `in-progress`, report the output with the per-item file lists. A broken
   gate cannot be attributed after parallel edits.
4. **Serially, in item order**, for each DONE item: stage exactly its files, work commit with the
   references from `rite begin`, then `rite finish <ID> --json`. Workers edit, the main thread commits
   — no races on the index or the views.
5. STALE → `rite mark-stale`; BLOCKED → `rite mark <ID> blocked --reason "…" --commit`; one failure
   does not stop the batch. Forwarded notes go into the destination items' Notes, committed together.
