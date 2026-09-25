---
description: Work through all open Rite fixes of a cycle — inline triage, agents only for the residue, then repairs in conflict-free waves
argument-hint: "[cycle] [fix-IDs] [--plan]"
parts: [cli, state, evidence, commit, batch, workspace, reporting]
---

# /rite:fix-all — every open fix, evidence first

Arguments: `$ARGUMENTS`

## Steps

1. `rite begin fix --cycle <cycle> --json` (`--no-claim` with `--plan`: it takes no item). The batch:
   the fix IDs given, or every fix open **now** (`rite batch-plan all --kind fix --cycle <cycle>
   --json`); fixes opened mid-run wait: a batch that grows never ends.
2. **Triage inline**: `rite reproduce --all --cycle <cycle> --json`, one call for all.
   Compare each output with its `recorded` Evidence; write the verdict:
   - `blocked: true` → its `unblock` ran its `unblocked_by` — the gesture `/rite:execute` makes with a
     blocked task. Exit 0 → `rite mark <FIX> pending --reason "<command> now passes" --commit`, then
     `rite reproduce <FIX> --json` and it joins the batch; else it stays blocked: report command and output.
   - `NOT REPRODUCED` → `rite mark-stale <FIX> --reason "<command> now prints <output>"`.
   - `REPRODUCED` → stays in the batch; paste the output into its Execution Log.
   - **Residue** — `runnable: false`, `over_limit`, `shell_error`, `CANNOT RUN`, or an output that does
     not decide: only then one `rite:rite-reproducer` per residue fix, in a single message, with the payload of
     `rite context <FIX> --json`. Handle its verdict as above; `CANNOT RUN` stays in the batch.
   - **With `--plan` the triage is dry**: `--plan` measures and reports, never writes — report each
     verdict and whether it was decided inline or is residue, with no `mark-stale` or `mark`, no Execution Log and
     no `rite:rite-reproducer` (residue is counted, not sent). `mark-stale` closes a fix: a planning run
     must not take it out of the backlog, and the inline/residue split is what a plan is run to measure.
3. **Plan** with `--kind fix` on the remaining IDs (with `--plan`: all but the `NOT REPRODUCED`).
   With `--plan`, stop here.
4. **Run the waves.** Each worker follows the single-fix rules of `/rite:fix`: reproduce again, confirm
   the root cause, repair the generator when the output is generated, never widen the scope.
5. Sweep edits go in their own commit (`docs: sweep after <FIX>`), then `rite finish <FIX> --sha
   <work-SHA> --json`.
6. **New problems** become new fixes (`rite new-fix --origin <FIX>`, fill the body,
   `rite commit-new <ID>`), reported, not worked on here.

## Report

Triage, one line per fix: verdict, inline or agent · fixes without a command (ID, `why`, origin): a
defect of their review · waves and conflict pairs · per item: result, work SHA,
bookkeeping SHA · gates · new fixes opened · what to run next.

<!-- rite:parts -->
