---
description: Retrospective of a Rite cycle — group fixes by root cause and propose what to keep, promote, report and prune
argument-hint: "<cycle> [--yes]"
parts: [cli, asking, evidence, commit, reporting]
---

# /rite:retro

Arguments: `$ARGUMENTS`

The retro is how the system learns: a pitfall proven in this cycle protects the next one, a rule proven
twice belongs in the repo config, and a failure of the rite itself belongs to the plugin.

## Steps

1. **Resolve** the cycle (`rite resolve-cycle <cycle> --json`; archived cycles resolve too).
2. **Numbers**: `rite stats <cycle> --json`. Every number in the retro comes from this output.
3. **Read** every fix of the cycle (`fix_files`) — Problem, Root cause, Fix — and skim the Execution
   Logs of the tasks with the most fixes (`fixes_by_origin`). Read the profile and, by search, the
   pitfalls entries that those fixes touch; read earlier retros in `[paths].archive_dir` if any.
4. **Group** fixes by root cause, not by symptom: one line and a count per group, each marked
   **bookkeeping** (state, links, logs) or **engineering** (code, data, numbers).
5. **Propose**, every proposal carrying its fix IDs as evidence:
   - **Keep** — pitfalls for the next cycle's pitfalls file, in the template's format.
   - **Promote** — a rule that caused fixes here and in an earlier cycle → a line in `rite.toml`
     (guards, gates, resources) or `CLAUDE.md`.
   - **Report** — a failure of the rite itself → the text of an issue for the plugin repository.
   - **Prune** — profile or pitfall entries no fix touched and that no longer apply; profile entries
     that should move to the pitfalls file to stay under `[profile].max_kb`.
6. **Write** `retro.md` in the cycle folder from `${CLAUDE_PLUGIN_ROOT}/templates/retro.md`.
7. **Ask** which proposals to apply (multi-select, grouped by kind) and apply only those. Issues are
   drafted in `retro.md`; open them (`gh issue create`) only if the user explicitly asks.
8. **Validate** `rite check --all --json`, then commit the retro and the applied edits:
   `docs(rite): retro <cycle>`.

## Report

The numbers from `rite stats` · root-cause groups with counts and kind · proposals per kind with
their fix IDs, applied or not · commit SHA.

<!-- rite:parts -->
