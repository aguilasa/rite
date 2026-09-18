---
description: Execute a small batch of Rite tasks in conflict-free waves (default 2, never "all")
argument-hint: "[cycle] [N | task-IDs] [--plan]"
---

# /rite:execute-batch — N tasks, in waves

Arguments: `$ARGUMENTS`

Before step 1, read these fragments from `${CLAUDE_PLUGIN_ROOT}/shared/` and follow them:
`cli.md`, `cycle-resolution.md`, `layers.md`, `evidence.md`, `guards.md`, `discrepancy-sweep.md`,
`commit-policy.md`, `bookkeeping.md`, `batch.md`.

## Steps

1. **Resolve** the cycle (Step 0). Parse the rest of the arguments:
   - a number `N` → the next `N` selectable tasks; no number and no IDs → `N = 2`;
   - task IDs → exactly those;
   - "all", "everything" or a number above 8 → refuse and ask for a number. Why: a batch that never
     ends is not reviewable, and review must keep pace with execution.
   - `--plan` → stop after Phase 0.
2. **Read the layers** once for the batch (repo config, profile); each worker reads its own item.
3. **Phase 0 — plan** (`batch.md`) with `--kind task`. Tasks with `type: closing` always run alone,
   in the last wave: `batch-plan` enforces it.
4. **Pull-ahead** is not allowed in a batch, even if a worker proposes it. Why: the plan was built
   from each item's declared scope.
5. **Phase 1 — waves** (`batch.md`). Each worker follows the single-task rules of `/rite:execute`
   (scope, done criteria verified by running them, sweep inside its files, negative results recorded).
6. After the last wave, remind the user that every closed task now awaits `/rite:review`.

## Report

Use the fixed format in `batch.md`.
