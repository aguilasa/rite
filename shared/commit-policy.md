# Commit policy

Read `[commit]` in `rite.toml`.

- **Message**: `style = "conventional"` gives `<type>(<scope>): <summary>` with types `feat`, `fix`,
  `refactor`, `test`, `docs`, `build`, `chore`; `style = "free"` gives a plain imperative summary.
  Written in `commit_language`.
- **References**: take them from `rite commit-refs <ID> --json`, never from memory. Put your subject
  into its `subject_template` (replace `{subject}`) and end the body with its `trailers`, one per line.
  A tracked cycle gets `Refs: <ID>` — why: `git log --grep <ID>` must find every commit of an item.
  A cycle with a `ticket` gets the ticket too, where `[commit].ticket_format` puts it. A **local** cycle
  gets no `Refs: <ID>`: its documents are not in the repository, so the ID would point nowhere.
- **Footer**: when `co_author_footer = true`, end work commits with the co-author footer your harness
  provides. Bookkeeping commits come from the CLI and carry none.
- **Staging**: stage explicit paths (`git add -- <paths>`), never `git add -A` or `git add .`, and never
  paths matching `never_stage`. Why: batch runs and humans leave unrelated changes in the tree.
  In a **local** cycle never stage the cycle folder, its profile or its pitfalls file — the work commit
  carries the code only; prose you wrote in the item file stays on disk.
- **Always commit**: every run ends with at least one commit. Why: the log is the audit trail; a silent
  run cannot be told apart from a skipped one. In a local cycle the item files are the audit trail and
  runs that change only them (review, stale, blocked) commit nothing.
- **Never** amend, rebase, force, skip hooks (`--no-verify`) or push. Push only when `push =
  "on-request"` and the user asked in this conversation.
- If a hook rejects the commit, fix the cause and commit again; report what the hook said.
