# Workspace — rite.toml outside git

Applies when `rite resolve-cycle --json` says `"workspace": true`: `rite.toml` sits in a plain folder
whose sub-folders are the git repositories (listed in `repos`). Otherwise skip this fragment.

- **Every item names its repository** in `repo:` (a folder under the root). Code, tests, gates and
  git commands for the item run **inside that folder**; paths in the item (`files:`, Scope, Evidence)
  are relative to it. `rite commit-refs <ID> --json` repeats it as `repo`.
- **Commit in the item's repository**: `git -C <repo> add -- <paths>` and `git -C <repo> commit`.
  Never run git at the workspace root — it is not a repository. `rite close <ID>` reads the work
  commit from `<repo>`, so commit there first.
- **Every cycle is local.** The cycle's documents stay in the workspace folder, outside every
  repository: never copy or stage them into one. The CLI records state in the files and commits nothing.
- **One item, one repository.** Work that must change two repositories is two items (with a
  `depends_on` between them when order matters). Why: `done_commit` is one commit in one repository,
  and the review measures exactly that commit.
- **Reviews and reproductions** run their evidence commands from `<repo>`; `review_commit` is the
  HEAD of that repository.
- Commands in `[gates].global` and in the profile run from the workspace root unless they say
  otherwise; write them with the folder (`cd <repo> && <test command>`) when they belong to one
  repository.
