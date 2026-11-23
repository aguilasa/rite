# Decisions at the end

Read by `execute`, `execute-batch`, `execute-phase`, `review`, `review-all`, `review-phase`, `fix`
and `fix-all` before their report, and only when `rite.toml` sets `[decisions] recommend = true`
(`decisions.recommend` in `rite begin` / `rite resolve-cycle`). Off — the default — they report as
before and never open this file.

- Only decisions this run leaves to the user are asked. The next `/rite:` command is never a
  question: it stays the report's `next:` line, as with the flag off. No decision left: no question.
- Gather the run's open decisions. One with **two or more viable paths** becomes a question in **one**
  AskUserQuestion call at the end of the run (at most 4 questions, 2–4 options each) — in a batch or a
  phase, after the last wave, never during one. One with a single path stays a line of the report.
- Each option: a short label; the recommended first, ` (Recommended)` at the end of its label; its
  description is the reason, measured (command and decisive output, IDs, counts), never bare opinion.
  Mark two recommended when the evidence supports both, and say in which case each wins. The
  automatic "Other" is the user's own instruction: follow it.
- **Local decisions** — the run applies the choice:
  - item **blocked** → recommended: `rite mark <ID> blocked` with the cause and its command; else
    narrow the scope (a note in the item), `skipped`, or a fix on the dependency;
  - **gate red** you could not fix → recommended: blocked, with the command and its output; else
    commit the partial work and go on with another item;
  - **`outside_files`** of `finish` → recommended: `--amend-files` when Notes justify the paths; else
    revert them, or a task of their own;
  - **finding dropped** by the screen → recommended: dropped (no runnable evidence); else the user
    gives the evidence and it becomes a fix;
  - **phase with no phase-checks entry** → recommended: add it to the profile; else go on;
  - **push failed** → recommended: report and go on (the commit stands); else retry.
  Anything else follows the same rules of options and reasons.
- `/rite:review-phase` asks its gaps in that same final call, with the other decisions.
- The report says what was asked and what was chosen, next to what the run did.
- With `--yes`, or when questions cannot be asked: ask nothing, apply the recommended option of each
  local decision and list `assumed: <decision> → <choice>`; never one that deletes, moves or
  overwrites files.
