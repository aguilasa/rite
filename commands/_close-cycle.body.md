---
description: Close a finished Rite cycle — verify preconditions, archive it with links rewritten, suggest a retro
argument-hint: "<cycle> [--yes]"
parts: [cli, asking, reporting]
---

# /rite:close-cycle

Arguments: `$ARGUMENTS`

## Steps

1. **Resolve**: `rite resolve-cycle <cycle> --json`. A cycle is required; never pick one yourself.
2. **Preconditions**: `rite archive <cycle> --dry-run --json` lists every blocker — tasks not done or
   skipped, done tasks not reviewed, open fixes, views out of sync. Blockers → report them grouped,
   each with the command that resolves it, and stop. Closing is a checkpoint, not a place to finish
   work in a hurry.
3. **Consistency**: `rite check --cycle <cycle> --json` must be clean. Errors → report and stop.
4. **Confirm** with the user: the folder moves to `[paths].archive_dir` and links pointing into it are
   rewritten across the repository.
5. **Archive**: `rite archive <cycle> --json` moves the folder (`git mv`), rewrites links in prose and
   link fields but not inside code blocks, and commits `chore(rite): archive <cycle>`. It refuses when
   the index has staged changes — report that as is. A local cycle is moved on disk and nothing is
   committed; its archive folder must be ignored by git too, or `check` warns.
6. **Verify**: `rite check --all --json` and `rite status --all --json`.

## Report

Cycle, from → to · preconditions passed or the blockers · files whose links were rewritten · commit
SHA · next: `/rite:retro <cycle>`.

<!-- rite:parts -->
