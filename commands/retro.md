---
description: Retrospective of a Rite cycle — group fixes by root cause and propose what to keep, promote, report and prune
argument-hint: "<cycle> [--yes]"
---

# /rite:retro

Arguments: `$ARGUMENTS`

Read from `${CLAUDE_PLUGIN_ROOT}/shared/`: `cli.md`, `evidence.md`, `commit-policy.md`, `asking.md`.

The retro is how the system learns: a pitfall proven in this cycle protects the next one; a rule
proven twice belongs in the repo config; a failure of the rite itself belongs to the plugin.

## Steps

1. **Resolve** the cycle (`rite resolve-cycle <cycle> --json`; archived cycles resolve too).
2. **Numbers**: `rite stats <cycle> --json`. Every number in the retro comes from this output.
3. **Read** every fix of the cycle (`fix_files`) — Problem, Root cause, Fix — and skim the Execution
   Logs of the tasks with the most fixes (`fixes_by_origin`). Read the cycle's profile and pitfalls
   file, and the previous cycles' retros if they exist in `[paths].archive_dir`.
4. **Group** fixes by root cause, not by symptom. Name each group in one line and count it. Mark
   groups that are **bookkeeping** (state, links, logs) versus **engineering** (code, data, numbers).
5. **Propose**, each proposal with its evidence (fix IDs):
   - **Keep** — pitfalls to carry into the next cycle's pitfalls file (format in the template: tags,
     paths, proven by, rule).
   - **Promote** — a rule that caused fixes in this and at least one earlier cycle → a line in
     `rite.toml` (guards, gates, resources) or `CLAUDE.md`.
   - **Report** — a failure of the rite itself (a command's instruction that led to the error) → the
     text of an issue for the plugin repository.
   - **Prune** — profile or pitfall entries that no fix touched and that no longer apply; profile
     entries that should move to the pitfalls file to keep the profile under `[profile].max_kb`.
6. **Write** `retro.md` in the cycle folder from `${CLAUDE_PLUGIN_ROOT}/templates/retro.md`.
7. **Ask** which proposals to apply (AskUserQuestion, multi-select, grouped by kind). Apply only the
   approved ones. Issues are drafted in `retro.md`; open them (`gh issue create`) only if the user
   explicitly asks.
8. **Validate** with `rite check --all`, then **commit** the retro and the applied edits:
   `docs(rite): retro <cycle>`.

## Report (fixed format)

1. **Numbers** — from `rite stats`.
2. **Root-cause groups** — name, count, bookkeeping/engineering.
3. **Proposals** — per kind, with fix IDs; applied or not.
4. **Commit** — SHA + subject.
