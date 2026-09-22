---
description: Create a new Rite cycle — folder, progress and fixes views, profile skeleton and pitfalls file
argument-hint: "<name> [--prefix X] [--plan path] [--ticket KEY] [--local] [--yes]"
parts: [cli, asking, reporting]
---

# /rite:new-cycle

Arguments: `$ARGUMENTS`

## Steps

1. **Parse** `<name>` (required; letters, digits, `.`, `_`, `-`), `--prefix`, `--plan`.
   - No name → ask for one and stop until answered.
   - No prefix → propose 2–4 upper-case letters derived from the name that no live cycle uses
     (`rite status --all --json` lists prefixes) and confirm: the prefix is in every ID of the cycle
     and cannot change later without renaming every file.
   - No plan → look in `[paths].plans_dir` for one whose name matches; confirm it, or proceed without.
   - Unless `--yes`, ask in one question: the cycle's **ticket** in an external tracker (optional; every
     commit of the cycle carries it) and whether the cycle is **local** (its documents stay out of git;
     code commits still go to the repository). In a workspace, skip the local question — every cycle
     there is local.
2. **Create**: `rite new-cycle <name> --prefix <X> [--plan <path>] [--ticket <KEY>] [--local] --commit
   --json`. It writes the cycle folder with its progress and fixes files, the profile skeleton and an
   empty pitfalls file, and commits them; a local cycle commits nothing. It refuses flat layouts,
   existing folders and prefixes already used — report such a refusal as is. For a local cycle, show
   the paths whose `ignored` is `false` and the `.gitignore` lines that cover them, and let the user
   add them: `.gitignore` is shared with everyone, so do not edit it.
3. **Seed the profile** only with what is already established: decisions the plan states as decided,
   under "Confirmed decisions" with their plan section, and the plan under "Sources of truth". Leave
   every other section with its hint comment — a profile filled with guesses is worse than an empty
   one, because commands obey it. Commit `docs(rite): seed <name> profile` (not in a local cycle).

## Report

Cycle (name, prefix, folder, ticket, local or tracked) · created files · what was seeded and from
where · commit SHAs · next: `/rite:plan-to-tasks <plan> <name>`.

<!-- rite:parts -->
