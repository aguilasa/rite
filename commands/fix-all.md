---
description: Work through all open Rite fixes of a cycle — parallel read-only triage, then repairs in conflict-free waves
argument-hint: "[cycle] [fix-IDs] [--plan]"
---

# /rite:fix-all — every open fix, evidence first

Arguments: `$ARGUMENTS`

Before step 1, read these fragments from `${CLAUDE_PLUGIN_ROOT}/shared/` and follow them:
`cli.md`, `cycle-resolution.md`, `evidence.md`, `guards.md`, `discrepancy-sweep.md`,
`commit-policy.md`, `bookkeeping.md`, `batch.md`.

## Steps

1. **Resolve** the cycle (Step 0). The batch is the given fix IDs, or else every fix open **now**
   (`rite batch-plan all --kind fix --cycle <cycle> --json`).
   Fixes opened during this run are not added. Why: a batch whose end moves is never done.
2. **Triage — reproduce in parallel.** Launch one `rite-reproducer` agent (namespaced
   `rite:rite-reproducer`) per fix, in one message. Exception: fixes that declare a serialized resource
   are reproduced one at a time, never alongside another user of that resource.
   - `NOT REPRODUCED` → `rite mark-stale <FIX> --reason "<command> now prints <output>"`.
   - `REPRODUCED` or `CANNOT RUN` → stays in the batch; paste the reproducer's output into the fix's
     Execution Log so the worker starts from it.
3. **Phase 0 — plan** (`batch.md`) with `--kind fix` on the remaining IDs. With `--plan`, stop here.
4. **Phase 1 — waves** (`batch.md`). Each worker follows the single-fix rules of `/rite:fix`:
   reproduce again, confirm root cause, repair in the generator when output is generated, verify
   before/after, never widen scope.
5. **Sweep commits.** After each item's work commit, commit its sweep edits separately
   (`docs: sweep after <FIX>`) when there are any, then `rite close <FIX> --sha <work-SHA>`.
6. **New problems** reported by workers become new fixes (`rite new-fix --origin <FIX>`, fill the body,
   `rite commit-new <ID>`). They are listed in the report, not worked on in this run.

## Report

Use the fixed format in `batch.md`, plus:

- **Triage** — per fix: reproduced / not reproduced (stale) / cannot run.
- **New fixes** — IDs opened during the run, or "none".
