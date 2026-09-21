---
description: Close a finished Rite cycle — verify preconditions, archive it with links rewritten, suggest a retro
argument-hint: "<cycle> [--yes]"
---

# /rite:close-cycle

Arguments: `$ARGUMENTS`

Read from `${CLAUDE_PLUGIN_ROOT}/shared/`: `cli.md`, `asking.md`.

## Steps

1. **Resolve** the cycle: `rite resolve-cycle <cycle> --json`. A cycle is required; do not pick one.
2. **Preconditions**: `rite archive <cycle> --dry-run --json`. It lists every blocker: tasks not done
   or skipped, done tasks not reviewed, open fixes, views out of sync.
   - Blockers → report them grouped, each with the command that resolves it (`/rite:execute`,
     `/rite:review`, `/rite:fix`, `rite sync`), and stop. Do not resolve them here. Why: closing is a
     checkpoint, not a place to finish work in a hurry.
3. **Consistency**: `rite check --cycle <cycle>` must be clean. Errors → report and stop.
4. **Confirm** with the user: the cycle folder moves to `[paths].archive_dir` and links pointing into it
   are rewritten across the repository.
5. **Archive**: `rite archive <cycle> --json`. It moves the folder with `git mv`, rewrites links in
   prose and link fields (not inside code blocks), and commits `chore(rite): archive <cycle>`. It
   refuses when the index has staged changes — report that as is. A local cycle is moved on disk and
   nothing is committed; the archive folder must be ignored by git too, or `check` warns.
6. **Verify**: `rite check --all` and `rite status --all`.

## Report (fixed format)

1. **Cycle** — name, from → to.
2. **Preconditions** — passed, or the blockers.
3. **Links rewritten** — files.
4. **Commit** — SHA + subject.
5. **Next** — `/rite:retro <cycle>`.
