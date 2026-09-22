---
description: Execute a small batch of Rite tasks in conflict-free waves (default 2, never "all")
argument-hint: "[cycle] [N | task-IDs] [--plan]"
parts: [cli, state, evidence, commit, batch, workspace, reporting]
---

# /rite:execute-batch — N tasks, in waves

Arguments: `$ARGUMENTS`

## Steps

1. `rite begin task --cycle <cycle> --json` resolves the cycle and its config; its item is the first of
   the batch. Parse the rest of the arguments:
   - a number `N` → the next `N` selectable tasks; nothing given → `N = 2`;
   - task IDs → exactly those;
   - "all", "everything" or a number above 8 → refuse and ask for a number: review must keep pace;
   - `--plan` → stop after the plan.
   - Nothing selectable but `blocked` tasks exist → re-run the check behind each recorded cause; gone →
     `rite mark <ID> pending --reason "..." --commit`. Plan again; still nothing → report and stop.
2. **Plan** with `--kind task`. Closing tasks always run alone, in the last wave.
3. **Run the waves.** Each worker follows the single-task rules of `/rite:execute`: scope, done
   criteria verified by running them, sweep inside its own files, negative results recorded. **No
   pull-ahead in a batch**: the plan was built from each item's declared scope.
4. After the last wave, say that every closed task now awaits `/rite:review`.

## Report

Waves with their item IDs and the conflict pairs that shaped them · per item: result (done / stale /
blocked / aborted), work SHA, bookkeeping SHA · gates · forwarded notes · what to run next.

<!-- rite:parts -->
