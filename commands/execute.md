---
description: Execute exactly one task of a Rite cycle, commit it, and record it
argument-hint: "[cycle] [task-ID]"
---

# /rite:execute — one task

Arguments: `$ARGUMENTS`

This command does **one task** and stops. Why: one unit per invocation keeps every run small,
reviewable and resumable; batches are `/rite:execute-batch`.

Before step 1, read these fragments from `${CLAUDE_PLUGIN_ROOT}/shared/` and follow them:
`cli.md`, `cycle-resolution.md`, `layers.md`, `evidence.md`, `guards.md`, `discrepancy-sweep.md`,
`commit-policy.md`, `bookkeeping.md`, `workspace.md`.

## Steps

1. **Resolve** (Step 0, kind `task`). The CLI selects: an `in-progress` task first, otherwise the lowest
   pending task whose `depends_on` are satisfied. Nothing selectable → report why and stop.
   A task named explicitly with `status: blocked`: re-run the check behind the cause recorded in its
   Execution Log. Cause gone → `rite mark <ID> pending --reason "<command> now <output>" --commit` and
   continue; cause still there → report it and stop.
2. **Read the layers** for this task, in order.
3. **Fix the scope.** The task's Scope and Done criteria are the contract. Do exactly that:
   - Work that belongs to a later task is **not** pulled ahead unless the user asked for it in this
     conversation. If they did, add a line to the profile's "Pull-ahead precedents" (what, why, date).
   - Anything you notice for another item goes in that item's Notes, not into this task's diff.
   - If a done criterion is not verifiable (no command, number or file), make it verifiable in the
     task file first and say so in the report.
4. **Start**: `rite mark <ID> in-progress`.
5. **Do the work.** Follow the evidence rules: run what you claim; numbers come from versioned tools;
   generated output changes only through its generator plus its check; a negative result is recorded,
   not bent.
6. **Verify every done criterion** by running it. Tick a criterion (`- [x]`) only after seeing its
   output; paste the command and the decisive line of output under Notes.
7. **Gates**: run `[gates].global` and the profile's Gates. Red → fix and rerun; if you cannot, go to
   *Blocked* below.
8. **Discrepancy sweep.**
9. **Work commit** — code, docs, sweep edits and the task file's prose together, with the references
   from `rite commit-refs <ID>`. In a local cycle the task file stays out of the commit.
10. **Close**: `rite close <ID> --json`, then `rite check --quick --cycle <cycle>`.

**Blocked**: if the task cannot be finished (missing dependency, failing gate you cannot fix, guarded
path in the way, contradiction with the source of truth), commit any useful partial work, run
`rite mark <ID> blocked --reason "<cause, with the command and output>" --commit`, and report.
Do not close a task whose criteria are not met.

## Report (fixed format)

1. **Task** — ID, title, cycle.
2. **Done criteria** — one line each: `[x]` or `[ ]`, the command, the decisive result.
3. **Gates** — command → pass/fail.
4. **Sweep** — terms searched; mentions updated; notes forwarded to other items.
5. **Commits** — work SHA + subject; bookkeeping SHA.
6. **Check** — `rite check --quick` result.
7. **Next** — output of `rite next task --cycle <cycle>`; remind that this task now awaits `/rite:review`.
