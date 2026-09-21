---
description: Fix exactly one Rite fix item — reproduce its evidence first, then repair and record
argument-hint: "[cycle] [fix-ID]"
---

# /rite:fix — one fix, evidence first

Arguments: `$ARGUMENTS`

This command handles **one fix** and stops. Batches are `/rite:fix-all`.

Before step 1, read these fragments from `${CLAUDE_PLUGIN_ROOT}/shared/` and follow them:
`cli.md`, `cycle-resolution.md`, `evidence.md`, `guards.md`, `discrepancy-sweep.md`,
`commit-policy.md`, `bookkeeping.md`.

## Steps

1. **Resolve** (Step 0, kind `fix`). The CLI selects an `in-progress` fix first, then the most severe
   open fix whose `depends_on` are satisfied.
2. **Read** `rite.toml`, the profile, matching pitfalls entries, and **only this fix's file**. Why: the
   fix is self-contained by design; opening its origin task invites re-doing the review. Open the
   origin or source of truth only when the fix's text is ambiguous, and say so.
3. **Start**: `rite mark <FIX> in-progress`.
4. **Reproduce.** Run the Evidence command(s) at the current HEAD.
   - **Symptom gone** → do not change code. `rite mark-stale <FIX> --reason "<command> now prints
     <output>; <why it went away, if known>"`, report, stop. Why: "fixing" code that is already right
     is how regressions are introduced.
   - **No runnable evidence** → write one that shows the problem into the Evidence section first. If you
     cannot make the problem observable, `rite mark <FIX> blocked --reason "..." --commit` and stop.
   - **Reproduced** → paste the decisive output under the Execution Log and continue.
5. **Root cause.** Confirm or correct the fix's Root cause section before changing anything. If the
   defect is in generated output, the change goes in the generator.
6. **Repair**, keeping to the fix's scope. Where the project has tests, add one that fails without the
   repair. Rerun the Verification command: it must now pass — record before/after output.
7. **Gates**: `[gates].global` and the profile's Gates.
8. **Work commit** (`fix: ...`, references from `rite commit-refs <FIX>`), including the fix file's prose
   (Root cause, Verification) — except in a local cycle, where the fix file stays out of the commit.
9. **Discrepancy sweep** — with its **own commit** (`docs: sweep after <FIX>`) when it changed anything.
   Why: separate commits let a reviewer tell the repair from its ripple.
10. **Close**: `rite close <FIX> --sha <work-commit-SHA> --json`, then `rite check --quick --cycle <cycle>`.

**Unrelated problem found** while fixing: do not widen this fix. `rite new-fix --origin <FIX> ...`,
fill its body with evidence, `rite commit-new <NEW-FIX>`, and mention it in the report.

## Report (fixed format)

1. **Fix** — ID, severity, title, origin.
2. **Reproduction** — command → output before (or "stale: symptom gone" with output).
3. **Root cause** — one or two sentences; "confirmed" or "corrected".
4. **Repair** — files changed; test added.
5. **Verification** — command → output after; gates → pass/fail.
6. **Sweep** — terms searched; mentions updated; sweep commit SHA or "none needed".
7. **Commits** — work SHA; bookkeeping SHA.
8. **New fixes** — IDs opened, or "none".
9. **Next** — `rite next fix --cycle <cycle>` result.
