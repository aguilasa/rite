# Commit policy

Read `[commit]` in `rite.toml`.

- **Message**: `style = "conventional"` gives `<type>(<scope>): <summary>` with types `feat`, `fix`,
  `refactor`, `test`, `docs`, `build`, `chore`; `style = "free"` gives a plain imperative summary.
  Written in `commit_language`. Put the item ID in the body as `Refs: <ID>`. Why: `git log --grep <ID>`
  must find every commit of an item.
- **Footer**: when `co_author_footer = true`, end work commits with the co-author footer your harness
  provides. Bookkeeping commits come from the CLI and carry none.
- **Staging**: stage explicit paths (`git add -- <paths>`), never `git add -A` or `git add .`, and never
  paths matching `never_stage`. Why: batch runs and humans leave unrelated changes in the tree.
- **Always commit**: every run ends with at least one commit. Why: the log is the audit trail; a silent
  run cannot be told apart from a skipped one.
- **Never** amend, rebase, force, skip hooks (`--no-verify`) or push. Push only when `push =
  "on-request"` and the user asked in this conversation.
- If a hook rejects the commit, fix the cause and commit again; report what the hook said.
