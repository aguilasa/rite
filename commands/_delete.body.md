---
description: Delete Rite tasks or fixes created by mistake — never-worked items only, confirmed first, IDs never reused
argument-hint: "[cycle] <ID…> [--detach]"
parts: [cli, state, asking, reporting]
---

# /rite:delete — remove an item that should not exist

Arguments: `$ARGUMENTS`

Deleting is for mistakes: a duplicate, an item created in the wrong cycle or from a misread plan.
Giving work up is not deleting — a task is `rite mark <ID> skipped --reason "…" --commit`, a fix
`rite mark-stale` — because both keep the record. Only an item never worked on (`pending`,
`blocked`, `skipped`, no `done_commit`) can go; its ID stays under `deleted` and is never handed out
again.

## Steps

1. `rite delete <ID> --dry-run [--detach] --json` per ID. `eligible: false` → report its
   `blockers` and the way out, and leave it:
   - started or done → give it up instead (skipped / stale), as the message says;
   - a fix with it as `origin` → that fix must go first (delete it too, if it is also a mistake);
   - another item's `depends_on` → `--detach` drops it there; say which items lose the dependency;
   - a link in a document (`path:line`) → the user rewrites that prose; never edit it to unblock.
2. **Confirm every deletion** with AskUserQuestion: each eligible item with its title and status,
   what `--detach` releases (`detach`) and whether it leaves the cycle's `order`. Ask for the reason in
   the same round when the arguments give none. A deletion is never assumed — not with `--yes`, not
   when questions cannot be asked: then report the dry run and stop.
3. For each confirmed ID, fixes before the tasks they came from: `rite delete <ID> --reason "<reason>"
   [--detach] --json`. One commit per item (`chore(rite): delete <ID> (<reason>)`) carrying the
   removed file, the JSON and the views; in a local cycle it writes the files and commits nothing.
4. `rite check --quick --cycle <cycle> --json`.

## Report

Per ID: deleted (commit SHA, or "local cycle") or refused (blockers, way out) · dependencies dropped
by `--detach` · what to run next.

<!-- rite:parts -->
