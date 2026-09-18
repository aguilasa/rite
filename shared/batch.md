# Batches — waves, workers, serial commits

A batch relaxes exactly one rule of the single-item commands: more than one item per invocation.
Everything else (evidence, guards, sweep, two commits per item) still holds per item.

**Batch ≠ parallel.** Items share a wave only when they share no file, no serialized resource and no
dependency. The dependency graph speaks of logical order; the conflict matrix speaks of physical
contention. When they disagree, the matrix wins.

## Phase 0 — plan

1. `rite batch-plan <count|IDs> --kind <task|fix> --cycle <cycle> --json`.
2. For each item whose `files` is empty or inferred, read the item and write its predicted paths into
   the `files:` (and `resources:`) planning fields of its frontmatter — never the state fields. Rerun
   `batch-plan` until no item has unknown files. Why: an item with unknown files must run alone.
3. Show the plan: items, predicted files, conflict pairs with reasons, waves, warnings. With `--plan`,
   stop here and commit the planning-field edits (`chore(rite): plan batch <IDs>`) if any.

## Phase 1 — run wave by wave

For each wave, in order:

1. `rite mark <ID> in-progress` for each item of the wave.
2. Launch one `rite-worker` agent (namespaced `rite:rite-worker`) per item, **in parallel, in one
   message**. Give each only: repository root, cycle, item path, its allowed files (`files`), the
   serialized resources assigned to it (at most one worker per resource), the gates it may run
   (none that use a resource held by another worker), and the CLI invocation.
3. Wait for all workers. For each report, check with `git status --porcelain` that the worker only
   changed its allowed files. A stray file is a failure of that item.
4. Run `[gates].global` and the profile's Gates **once, on the combined tree**.
   - **Green** → go to 5.
   - **Red** → abort the batch: commit nothing from this wave, leave items `in-progress`, and report
     the gate output with the per-item file lists so the user can decide. Why: a broken global gate
     cannot be attributed safely after parallel edits.
5. **Serially, in item order**, for each item that reported DONE: stage exactly its files
   (`git add -- <files>`), work commit with `Refs: <ID>`, then `rite close <ID> --json`. Why: the
   subagent edits, the main thread commits — no races on the index or the views.
6. Items that reported STALE (fixes) → `rite mark-stale`; BLOCKED → `rite mark <ID> blocked
   --reason "..." --commit`. An isolated failure does not stop the batch.
7. Write each worker's forwarded notes into the destination items' Notes and commit them
   (`docs: forward notes from <IDs>`).

After the last wave: `rite check --quick --cycle <cycle>`.

## Report (fixed format)

1. **Plan** — waves with item IDs; conflict pairs and reasons.
2. **Per item** — ID, result (done / stale / blocked / aborted), work SHA, bookkeeping SHA.
3. **Gates** — per wave, command → pass/fail.
4. **Forwards** — notes written to other items.
5. **Check** — `rite check --quick` result.
6. **Next** — `rite status --cycle <cycle>` suggestion.
