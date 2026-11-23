---
description: Review a finished phase of a Rite cycle as a whole — regressions, contradictions, parts of the plan left out — and open fixes and tasks
argument-hint: "<cycle> <phase> [--yes]"
parts: [cli, state, asking, evidence, commit, workspace, deciding, reporting]
---

# /rite:review-phase — the phase as a whole

Arguments: `$ARGUMENTS`

Each task was reviewed alone. This looks at what only the whole phase shows: something a later task
broke in an earlier one, tasks that contradict each other, a part of the plan no task delivered.
Review only: never change code, docs or the tasks' work.

## Steps

1. `rite resolve-cycle <cycle> --json`, then `rite phase <cycle> --phase <phase> --json`. The phase is
   required: missing → ask, never pick one. `reviewable` false → the phase is not finished: report
   what is left with its command — `pending` or `blocked` tasks (`/rite:execute-phase`), `unreviewed`
   (`/rite:review-all`), `open_fixes` (`/rite:fix-all`) — and stop.
2. **Delegate** to one fresh `rite:rite-phase-reviewer` agent — never this context. Give it facts
   only: the `rite phase` payload, the payload of `rite context <ID> --json` for the phase's closing
   task (else its last task) — the profile's gates and phase checks —, the repository it works in,
   the CLI invocation, and the instruction "Review this phase per your procedure and return findings
   and gaps in your format." Do not tell it what you think of the work.
3. **Screen.** Keep a finding or a gap only if it carries a runnable evidence command and its output;
   a finding also needs one command that runs on the working tree. Drop one that a fix of the cycle
   already records, naming that fix. Do not re-review, soften or add any of your own; list what you
   dropped, with the reason.
4. **One fix per kept finding**: `rite new-fix --cycle <cycle> --origin <its origin> --title "<title>"
   --severity <critical|high|medium|low> --json`, fill the body sections (Problem, Evidence, Root
   cause, Fix, Files, Verification) — never its frontmatter or the JSON state —, then `rite commit-new
   <FIX> --json`.
5. **Gaps become tasks only when the user says so**: they change the scope. Ask once, multi-select, a
   gap whose section states the missing part outright first and marked `(Recommended)`. For each
   chosen: `rite new-task --cycle <cycle> --title "<title>" --type <type> --phase <phase>
   --source-of-truth <link> [--depends-on <IDs>] --json`, fill Scope and verifiable Done criteria,
   `rite set <ID> --files …`, `rite commit-new <ID> --json`. The phase is open again until they are
   done and reviewed. With `--yes`, create none: they stay in the document, to be decided.
6. **Write** `phase-<phase>-review.md` in the cycle folder from
   `${CLAUDE_PLUGIN_ROOT}/templates/phase-review.md` — also with nothing found: a review without a
   record was not done — and commit it: `docs(rite): review phase <phase> of <cycle>`. In a local
   cycle it is written and nothing is committed.
7. `rite check --quick --cycle <cycle> --json`.

## Report

The four verdicts, one line each · fixes opened (ID, severity, origin, title) · tasks created, gaps
declined or left to decide · dropped findings and gaps with reasons · the document and its commit
SHA, or "local cycle" · next: `/rite:fix-all`, `/rite:execute-phase <cycle> <phase>`, or "phase clean" with
`/rite:retro <cycle> --phase <phase>` when its fixes hold a lesson for the phases still to run.

<!-- rite:parts -->
