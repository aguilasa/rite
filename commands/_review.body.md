---
description: Independently review one finished Rite task in a clean context and open fixes for what fails
argument-hint: "[cycle] [task-ID]"
parts: [cli, state, evidence, workspace, reporting]
---

# /rite:review — one task, independent

Arguments: `$ARGUMENTS`

Review only: never change code, docs or the task's work. The one who executed cannot see their own
blind spots, so the review happens in a separate context that **measures instead of reads**.

## Steps

1. `rite begin review [--cycle <cycle>] [--id <ID>] --json` — the lowest-ID task that is `done` with
   `reviewed_on: pending`. A named task must be in that state.
2. **Delegate** to a fresh `rite:rite-reviewer` agent — never this context. Give it facts only: the
   payload of `rite context <ID> --json`, the repository root (in a workspace, the task's `repo`), the
   CLI invocation, the task's `done_commit`, and the instruction "Review this task per your procedure
   and return findings in your format." Do not tell it what you think of the work.
3. **Screen the findings.** Keep one only if it carries a runnable evidence command and its output. Do
   not re-review, soften or add findings of your own; list what you dropped, with the reason.
4. **Open one fix per kept finding**: `rite new-fix --cycle <cycle> --origin <ID> --title "<title>"
   --severity <critical|high|medium|low> --json`, then fill the body sections (Problem, Evidence, Root
   cause, Fix, Files, Verification) — never its frontmatter. A finding about a phase with no entry in
   the profile's phase checks is itself a `medium` fix: the reviewer could not apply that phase's checks.
5. `rite mark-reviewed <ID> [--fixes <FIX-ID>,…] --json`. This single commit carries the new fix files,
   `reviewed_on` and the views — also when there is no finding, because a review without a record
   leaves the task to be selected again. In a local cycle it writes the files and commits nothing.
6. `rite check --quick --cycle <cycle> --json`.

## Report

Task and `done_commit` · the reviewer's verdict on each of its four universal questions, one line
each · phase checks, pass/fail or "no entry for phase N" · fixes opened (ID, severity, title) ·
dropped findings with reasons · the commit SHA, or "local cycle" · what to run next.

<!-- rite:parts -->
