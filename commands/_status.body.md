---
description: Show where each Rite cycle stands and which command to run next (read-only)
argument-hint: "[cycle]"
allowed-tools: Bash, Read
parts: [cli]
---

# /rite:status

Arguments: `$ARGUMENTS`

Read-only: change nothing, commit nothing.

1. `$ARGUMENTS` names a cycle → `rite status --cycle <cycle> --json`; otherwise `rite status --all
   --json`.
2. Exit `3` → answer exactly `No rite.toml in this repository — run /rite:init first.` and stop.
3. `rite check --quick --json` for the same cycles: a status built on inconsistent bookkeeping is
   wrong, and its errors outrank the suggestion.

## Report

One block per cycle, at most 20 lines: name, prefix and folder · tasks by status of the total ·
review queue with the IDs and those older than the configured age · open fixes by severity, naming
critical and high ones — blocked fixes included, and how many (`open_fixes_blocked`) with the command
each waits on · what is blocked on what (`next_task.blocked_by`) · the next step, as the
command the CLI suggests, with its reason — or, if `check` reported errors, resolving those first,
listed. Do not speculate beyond what the CLI reported.

<!-- rite:parts -->
