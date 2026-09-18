---
description: Show where each Rite cycle stands and which command to run next (read-only)
argument-hint: "[cycle]"
allowed-tools: Bash, Read
---

# /rite:status

Read-only. Change nothing, commit nothing.

Follow `${CLAUDE_PLUGIN_ROOT}/shared/cli.md` for how to call the CLI.

1. If `$ARGUMENTS` names a cycle, run `rite.py status --cycle <cycle> --json`; otherwise run
   `rite.py status --all --json` (every live cycle).
2. If the CLI exits `3`, answer exactly: `No rite.toml in this repository — run /rite:init first.` and stop.
3. Run `rite.py check --quick --json` for the same cycles. Why: a status built on inconsistent
   bookkeeping is wrong; errors here outrank the suggestion.

Answer in this fixed format, one block per cycle:

1. **Cycle** — name, prefix, folder.
2. **Tasks** — done / in-progress / pending / blocked / skipped, of total.
3. **Review queue** — count, IDs, and those older than the configured age.
4. **Open fixes** — by severity; name critical and high ones.
5. **Blocked** — what waits on what (from `next_task.blocked_by`), if anything.
6. **Next step** — the CLI `suggestion` as a command (`/rite:execute`, `/rite:review`, `/rite:fix`,
   `/rite:plan-to-tasks`, `/rite:close-cycle`), with its reason. If `check` reported errors, the
   next step is to resolve them first; list them.

Keep it under 20 lines per cycle. Do not speculate beyond what the CLI reported.
