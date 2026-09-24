---
description: Fix exactly one Rite fix item — reproduce its evidence first, then repair and record
argument-hint: "[cycle] [fix-ID]"
parts: [cli, state, reading, evidence, guards, sweep, commit, workspace, reporting]
---

# /rite:fix — one fix, evidence first

Arguments: `$ARGUMENTS`

One fix per invocation, then stop. Batches are `/rite:fix-all`.

## Steps

1. `rite begin fix [--cycle <cycle>] [--id <FIX>] --json` — an `in-progress` fix first, then the most
   severe open one whose `depends_on` are satisfied.
2. `rite context <FIX> --json`. A fix is self-contained by design: open its origin task or the source
   of truth only when its text is ambiguous, and say so in the report.
3. **Reproduce** at the current HEAD: `rite reproduce <FIX> --json`.
   - *Symptom gone* → change nothing: `rite mark-stale <FIX> --reason "<command> now prints <output>"`,
     report, stop. "Fixing" right code is how regressions get in.
   - *No runnable evidence* → write one that shows the problem into the Evidence section first. If the
     problem cannot be made observable, `rite mark <FIX> blocked --reason "..." --commit` and stop.
   - *Reproduced* → paste the decisive output under the Execution Log and continue.
4. **Root cause**: confirm or correct that section before changing anything. A defect in generated
   output is fixed in the generator.
5. **Repair** inside the fix's scope. Where the project has tests, add one that fails without the
   repair. Rerun the Verification command and record output before and after.
6. `rite gates --id <FIX> --json`.
7. **Work commit** (`fix: …`) with the fix file's prose (Root cause, Verification).
8. **Sweep** — its edits go in their **own commit** (`docs: sweep after <FIX>`), so a reviewer can tell
   the repair from its ripple.
9. `rite finish <FIX> --sha <work-commit-SHA> --json`.

**Unrelated problem found**: do not widen this fix. `rite new-fix --origin <FIX> …`, fill its body with
evidence, `rite commit-new <NEW-FIX>`, mention it in the report.

## Report

Fix (ID, severity, origin) · reproduction output before, or "stale" · root cause, confirmed or
corrected · files changed and the test added · verification output after, and gates · sweep commit
or "none needed" · work and bookkeeping SHAs · new fixes · the `next` from `finish`.

<!-- rite:parts -->
