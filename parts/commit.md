## Committing

- **Message**: `[commit].style` `conventional` gives `<type>(<scope>): <summary>` (`feat`, `fix`,
  `refactor`, `test`, `docs`, `build`, `chore`), `free` a plain imperative one, in `commit_language`.
  Put your subject into the `subject_template` from `rite begin` and end the body with its `trailers`
  (`Refs: <ID>`, the ticket): `git log --grep` finds an item's commits.
- **Staging**: explicit paths (`git add -- <paths>`), never `git add -A`, never a `never_stage` path.
  In a local cycle, never stage the cycle folder, its profile or its pitfalls file.
- **Never** amend, rebase, force, skip hooks or push; push only when `[commit].push = "on-request"`
  and the user asked in this conversation. A hook that refuses is reported, never bypassed.
- Every run ends with a commit, except in a local cycle, where a run touching only item files does not.
