---
description: Independently review one finished Rite task in a clean context and open fixes for what fails
argument-hint: "[cycle] [task-ID]"
---

# /rite:review — one task, independent

Arguments: `$ARGUMENTS`

Review only: this command never changes code, docs or the task's work. It produces fixes and a
review record. Why: the one who executed cannot see their own blind spots; the review happens in a
separate context that **measures instead of reads**.

Before step 1, read these fragments from `${CLAUDE_PLUGIN_ROOT}/shared/`: `cli.md`,
`cycle-resolution.md`, `evidence.md`, `bookkeeping.md`.

## Steps

1. **Resolve** (Step 0, kind `review`). The CLI selects the lowest-ID task with `status: done` and
   `reviewed_on: pending`. An explicitly named task must be in that state.
2. **Delegate** to the `rite-reviewer` agent (namespaced `rite:rite-reviewer`). Always a fresh agent,
   never this context. Give it only facts, not opinions about the work:
   - repository root; the CLI invocation from `cli.md`;
   - cycle name and folder; paths of the task, profile, pitfalls file and `rite.toml`;
   - the task's `source_of_truth`, `done_commit`, `phase`;
   - the instruction: "Review this task per your procedure and return findings in your format."
3. **Screen the findings.** Keep a finding only if it has a runnable evidence command and its output.
   Do not re-review, soften or add findings of your own; list dropped ones in the report with the reason.
4. **Open fixes**, one per kept finding: `rite new-fix --cycle <cycle> --origin <ID> --title "<title>"
   --severity <critical|high|medium|low> --json`, then fill the created file's body sections
   (Problem, Evidence, Root cause, Fix, Files, Verification) from the finding. Never touch its frontmatter.
   A finding for a phase with no entry in the profile's "Phase-specific checks" is itself a fix
   (`medium`): the reviewer could not apply the phase's checks.
5. **Record**: `rite mark-reviewed <ID> [--fixes <FIX-ID>,...] --json`. This one commit carries the new
   fix files, the task's `reviewed_on` and the views — also when there are no findings.
   Why: a review without a commit leaves no trace, and the task would be selected again.
   In a local cycle it writes the same record to the files and commits nothing.
6. `rite check --quick --cycle <cycle>`.

## Report (fixed format)

1. **Task** — ID, title, `done_commit`.
2. **Universal questions** — the reviewer's verdict on each of the four, one line each.
3. **Phase-specific checks** — each check → pass/fail (or "no entry for phase N").
4. **Fixes opened** — ID, severity, title; or "none".
5. **Dropped findings** — with reason; or "none".
6. **Commit** — SHA + subject; or "local cycle, recorded in files".
7. **Next** — `rite status --cycle <cycle>` suggestion.
