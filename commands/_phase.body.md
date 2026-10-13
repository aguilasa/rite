---
description: Summarise what one phase of a Rite cycle delivered, finished or in progress (read-only)
argument-hint: "[cycle] [phase]"
allowed-tools: Bash, Read
parts: [cli, reporting]
---

# /rite:phase

Arguments: `$ARGUMENTS`

Read-only: change nothing, commit nothing. An account of what was done, not lessons — those belong to
`/rite:retro`.

1. Two words in `$ARGUMENTS` → cycle, then phase. One word → the cycle if `rite resolve-cycle <word>
   --json` exits 0, else the phase. None → both default.
2. `rite phase [cycle] [--phase <phase>] --json`. Without a phase it takes the last one with a task
   done. Exit `3` → answer exactly `No rite.toml in this repository — run /rite:init first.` and stop.
   Exit `1` → report its stderr (no task done yet, or the phases that exist) and stop.
3. For each task, read its `log.text`: the Execution Log as the task recorded it. Its closing notes
   say what was delivered and which gates ran with what result. `log.truncated` → read the task file
   at `path` only if the tail does not say it.

## Report

- First line: cycle, phase, `finished` or in progress, and the phase's place in `phases`.
- Each task in the order given: ID, status, short `done_commit`, and one or two lines of what it
  delivered, taken from its log. Never re-tell the plan or the task's goal; a task without a log says
  `no log`.
- The fixes: ID, severity, status, title — one line each.
- The last gate result the logs record, with what was skipped named as skipped. None recorded →
  `no gate recorded`; never infer one.
- In progress: what is pending, what is `blocked` and on what, and `next` as the command to run with
  its reason.

<!-- rite:parts -->
