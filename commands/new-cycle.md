---
description: Create a new Rite cycle — folder, progress and fixes views, profile skeleton and pitfalls file
argument-hint: "<name> [--prefix X] [--plan path] [--yes]"
---

# /rite:new-cycle

Arguments: `$ARGUMENTS`

Read from `${CLAUDE_PLUGIN_ROOT}/shared/`: `cli.md`, `asking.md`.

## Steps

1. **Parse** `<name>` (required; letters, digits, `.`, `_`, `-`), `--prefix`, `--plan`.
   - No name → ask for one and stop until answered.
   - No prefix → propose 2–4 upper-case letters derived from the name that no live cycle uses
     (`rite status --all --json` lists prefixes) and confirm with the user. Why: the prefix is in every
     ID of the cycle and cannot change later without renaming every file.
   - No plan → look in `[paths].plans_dir` for a plan whose name matches; confirm it, or proceed
     without one if the user says so.
2. **Create**: `rite new-cycle <name> --prefix <X> [--plan <path>] --commit --json`. It creates the
   cycle folder with its progress and fixes files, the profile skeleton (all required sections) and an
   empty pitfalls file, and commits them. It refuses flat layouts, existing folders and prefixes used
   by a live cycle — report the refusal as is.
3. **Seed the profile** only with facts already established: if the plan states decisions as
   decided, list them under "Confirmed decisions" with their plan section; list the plan under
   "Sources of truth". Leave every other section with its hint comment. Why: a profile filled with
   guesses is worse than an empty one — commands obey it. Commit with `docs(rite): seed <name> profile`.

## Report (fixed format)

1. **Cycle** — name, prefix, folder.
2. **Files** — created paths.
3. **Profile** — what was seeded, from where.
4. **Commits** — SHAs.
5. **Next** — `/rite:plan-to-tasks <plan> <name>`.
