---
description: Execute every remaining task of one phase of a Rite cycle in conflict-free waves, the closing task last
argument-hint: "<cycle> <phase> [--plan]"
parts: [cli, state, evidence, commit, batch, workspace, reporting]
---

# /rite:execute-phase — one phase, in waves

Arguments: `$ARGUMENTS`

A batch the size of a phase: the same waves, workers, gates and two commits per item as
`/rite:execute-batch`, with no count — the phase is where review catches up.

## Steps

1. `rite resolve-cycle <cycle> --json`. The phase is required: missing → ask, never pick one. With
   `--plan`, nothing becomes `in-progress` and only planning fields are written.
   - Tasks of the phase `blocked` → re-run the check behind each recorded cause; gone →
     `rite mark <ID> pending --reason "..." --commit` (with `--plan`, report the causes that are gone
     and mark nothing).
2. **Plan**: `rite batch-plan --phase <phase> --kind task --cycle <cycle> --json` — every pending or
   in-progress task of the phase whose dependencies can be met; the closing task alone, last. Nothing
   selectable → report each task of the phase and its status, and stop. `--plan` → stop after the
   plan, per the batch rules.
3. **Loop**: run the plan's **first wave** per the batch rules, then plan again with the same command
   and run its first wave, until nothing is selectable. Planning again reads the state after the wave:
   a task that went blocked or stale drops out with the tasks that depend on it. A wave aborted by red
   gates stops the run. Each worker follows the single-task rules of `/rite:execute`: scope, done
   criteria verified by running them, sweep inside its own files, negative results recorded. **No
   pull-ahead**: the plan was built from each task's declared scope.
4. The closing task runs only once every task it depends on is satisfied; if the loop ends without
   it, name the tasks it still waits on.
5. Every closed task now awaits review: next `/rite:review-all <cycle>`.

## Report

Waves run, each with its task IDs and the conflict pairs that shaped it · per task: result (done /
stale / blocked / aborted), work SHA, bookkeeping SHA, `outside_files` from `finish` if any · gates ·
tasks of the phase left and why · forwarded notes · what to run next.

<!-- rite:parts -->
