## Committing

- **Message**: `[commit].style` `conventional` gives `<type>(<scope>): <summary>` (`feat`, `fix`,
  `refactor`, `test`, `docs`, `build`, `chore`), `free` a plain imperative one, in `commit_language`.
  Put your subject in the `subject_template` from `rite begin` and end the body with its `trailers`
  (`Refs: <ID>`, the ticket: what `git log --grep` finds). With `co_author_footer: false`, add no
  `Co-Authored-By` trailer, whatever your attribution asks.
- **Staging**: explicit paths (`git add -- <paths>`), never `git add -A`, never a `never_stage` path.
  In a local cycle, never stage the cycle folder, its profile or its pitfalls file.
- **Never** amend, rebase, force, skip hooks or push by hand; push only when `[commit].push = "on-request"`
  and the user asked in this conversation. With `after-each-item`, `rite finish` and `rite commit-new`
  push: report a failed entry of their `pushed`, never retry it with force. A hook that refuses is reported, never bypassed.
- Every run ends with a commit, except in a local cycle, where a run touching only item files does not.
