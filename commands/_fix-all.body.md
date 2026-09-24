---
description: Work through all open Rite fixes of a cycle — inline triage, agents only for the residue, then repairs in conflict-free waves
argument-hint: "[cycle] [fix-IDs] [--plan]"
parts: [cli, state, evidence, commit, batch, workspace, reporting]
---

# /rite:fix-all — every open fix, evidence first

Arguments: `$ARGUMENTS`

## Steps

1. `rite begin fix --cycle <cycle> --json`. The batch is the fix IDs given,
   or every fix open **now** (`rite batch-plan all --kind fix --cycle <cycle> --json`); fixes opened
   during the run are not added: a batch whose end moves is never done.
2. **Triage inline**: `rite reproduce --all --cycle <cycle> --json`, one call for the batch.
   Compare each output with its `recorded` Evidence; write the verdict:
   - `NOT REPRODUCED` → `rite mark-stale <FIX> --reason "<command> now prints <output>"`.
   - `REPRODUCED` → stays in the batch; paste the output into its Execution Log.
   - **Residue** — `runnable: false`, `over_limit`, `shell_error`, `CANNOT RUN`, or an output that does
     not decide: only then one `rite:rite-reproducer` per residue fix, in a single message, with the payload of
     `rite context <FIX> --json`. Handle its verdict as above; `CANNOT RUN` stays in the batch.
3. **Plan** with `--kind fix` on the remaining IDs. With `--plan`, stop here.
4. **Run the waves.** Each worker follows the single-fix rules of `/rite:fix`: reproduce again, confirm
   the root cause, repair the generator when the output is generated, never widen the scope.
5. Sweep edits go in their own commit (`docs: sweep after <FIX>`), then `rite finish <FIX> --sha
   <work-SHA> --json`.
6. **New problems** become new fixes (`rite new-fix --origin <FIX>`, fill the body,
   `rite commit-new <ID>`), reported, not worked on here.

## Report

Triage, one line per fix: verdict, inline or agent · fixes without a command (ID, `why`, origin): a
defect of the review that opened it · waves and conflict pairs · per item: result, work SHA,
bookkeeping SHA · gates · new fixes opened · what to run next.

<!-- rite:parts -->
