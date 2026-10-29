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
   rewritten across the repository. When the dry-run's `unrewritten` is not empty (bare paths, comments,
   code outside the folder that would still name it), list each `path:line` and ask once, with the
   move, whether to rewrite them too. With `--yes` the invocation is the confirmation of the move, not
   of those lines: they are left and reported, since a path in code may be meant.
5. **Archive**: `rite archive <cycle> [--rewrite-bare] --json` (the flag only when the user said yes in
   step 4) moves the folder (`git mv`), rewrites links in prose and link fields but not inside code
   blocks, rewrites the old folder everywhere in the cycle's profile, pitfalls file and `retro.md`
   (`bare_rewritten`), and commits `chore(rite): archive <cycle>`. It refuses when
   the index has staged changes — report that as is. A local cycle is moved on disk and nothing is
   committed; its archive folder must be ignored by git too, or `check` warns. Its `unrewritten` lists
   the tracked lines still naming the old folder: report each `path:line` and leave them.
6. **Verify**: `rite check --all --json` and `rite status --all --json`.

## Report

Cycle, from → to · preconditions passed or the blockers · files whose links were rewritten · bare paths rewritten · lines
not rewritten · commit SHA · next: `/rite:retro <cycle>`.

<!-- rite:parts -->
