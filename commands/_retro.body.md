---
description: Retrospective of a Rite cycle — group fixes by root cause and propose what to keep, promote, report and prune
argument-hint: "<cycle> [--phase <p>[,<p>…] … | --since-last] [--yes]"
parts: [cli, asking, evidence, commit, reporting]
---

# /rite:retro

Arguments: `$ARGUMENTS`

The retro is how the system learns: a pitfall proven in this cycle protects the next one, a rule proven
twice belongs in the repo config, and a failure of the rite itself belongs to the plugin.

With `--phase` or `--since-last` it is a **partial retro** of some phases of an open cycle: what they
taught reaches the pitfalls file now, and `rite context` hands it to the tasks still to run. Without
them it covers the whole cycle, normally after `/rite:close-cycle`.

## Steps

1. **Resolve** the cycle (`rite resolve-cycle <cycle> --json`; archived cycles resolve too).
   **Scope** — partial only: `rite retro-scope <cycle> (--phase <p> … | --since-last) --json`. Exit 1
   or `ready` false → report, per phase of `detail`, what is left with its command — `pending` or
   `blocked` (`/rite:execute-phase`), `unreviewed` (`/rite:review-all`), `open_fixes`
   (`/rite:fix-all`) — and stop. `exists` → ask once whether to rewrite that file; no → stop. A phase
   whose `phase_review` is null: say it had no `/rite:review-phase`, and go on. From here, `<scope>` is
   `--phase <p>` for each of its `phases`, and nothing for a whole-cycle retro.
2. **Numbers**: `rite stats <cycle> <scope> --json`. Every number in the retro comes from this output.
3. **Candidates**: `rite retro-suggest <cycle> <scope> --json` — per fix, its paths and the pitfalls
   entries they match; entries proven in two or more cycles; entries whose paths are gone; a profile
   over `[profile].max_kb`; profile sections the previous cycle filled and this one left empty;
   `partials`, the partial retros already written. It measures; you decide.
4. **Read** every fix in `fix_files` — Problem, Root cause, Fix — and skim the Execution Logs of the
   tasks with the most fixes (`fixes_by_origin`). Read the profile and, by search, the pitfalls entries
   that those fixes touch; read earlier retros in `[paths].archive_dir` if any. Read each file of
   `partials`: a proposal one of them already applied or declined (its `## Applied`) is not proposed
   again unless a fix it did not see brings new evidence — then say which partial decided it.
5. **Group** fixes by root cause, not by symptom: one line and a count per group, each marked
   **bookkeeping** (state, links, logs) or **engineering** (code, data, numbers). The bookkeeping and
   engineering totals are the sums of these counts — `rite stats` does not classify fixes.
6. **Propose**, every proposal carrying its fix IDs as evidence, starting from the candidates and
   marked `(retro-suggest)`, or `(added)` when it is yours. Give each an ID (`K1`, `P1`, `R1`, `X1`
   for Keep, Promote, Report, Prune) and a verdict with a one-line reason: **recommended** when the
   evidence is measured — a candidate of `retro-suggest`, a lesson two or more fixes of one root-cause
   group share, a Report whose fix shows the rite itself failed; **optional** when it rests on one fix,
   on reading alone, or on a choice that is the user's (the wording of a rule, pruning an entry no fix
   touched):
   - **Keep** — pitfalls, in the template's format, written to this cycle's pitfalls file: the tasks
     still to run read it through `rite context`, and `/rite:new-cycle` starts the next cycle's file as
     a copy of it (`--pitfalls-from`). A fix whose `suggest` is `update-existing` extends that entry
     (its `proven by`, its `rule`), never a second entry for the same lesson.
   - **Promote** — a rule that caused fixes here and in an earlier cycle → a line in `rite.toml`
     (guards, gates, resources) or `CLAUDE.md`: the `promote` entries, and each `carry_over` section
     (content the new profile lost), promoted or copied back.
   - **Report** — a failure of the rite itself → the text of an issue for the plugin repository.
   - **Prune** — the `prune` candidates; profile or pitfall entries no fix touched and that no longer
     apply; profile entries that should move to the pitfalls file to stay under `[profile].max_kb`. In
     a partial retro, prune only what the `prune` candidates measured: later phases may still need the
     rest.
7. **Write** the retro from `${CLAUDE_PLUGIN_ROOT}/templates/retro.md`, its `Phases:` line the scope's
   `phases` (comma-separated) or `all`: partial → the `file` of `retro-scope`, else `retro.md` in the
   cycle folder. `retro-scope --since-last` reads that line to know what was covered.
8. **Ask** which proposals to apply: one call, one multi-select question per kind that has proposals.
   Up to 4 in a kind: one option each, the recommended first with `(Recommended)` at the end of the
   label, the reason and fix IDs as its description. More than 4: `Recommended (<IDs>) (Recommended)`,
   `All <n>`, `None` — other IDs can be typed. Apply only what was chosen and list every ID under
   `## Applied` as applied or declined. Issues are drafted in the retro; open them (`gh issue
   create`) only if the user explicitly asks. With `--yes`, apply nothing: report the recommended IDs.
9. **Validate** `rite check --all --json`, then commit the retro and the applied edits:
   `docs(rite): retro <cycle>`, or `docs(rite): retro <cycle> phase <p>[, <q>…]` for a partial one.

## Report

Scope (whole cycle, or phases and file) · the numbers from `rite stats` · root-cause groups with
counts and kind · proposals per kind with their ID, verdict and fix IDs, applied or not, and those a
partial retro already decided · commit SHA.

<!-- rite:parts -->
