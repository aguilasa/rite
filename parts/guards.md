## Guarded paths

`rite begin` returns them as `config.read_only` and `config.generated`; `rite guard <path> --json`
answers about one.

- `read_only` — written by no tool. The hook blocks Edit/Write, and shell writes (redirects, in-place
  edits, scripts) are equally forbidden: the hook cannot see them.
- `generated` — fix the generator or its input, run it, then its `check`, and commit both together. A
  hand-edited output is reverted by the next regeneration.

An item impossible without writing a guarded path stops and is reported — never closed on a note:
`rite mark <ID> blocked --reason "<path> needs <change>, by the user" --commit`; a fix adds
`--unblocked-by "! git diff --quiet <HEAD now> HEAD -- <path>"`, which passes once that path is changed
(a path in another repository than the fix's: `git -C <its folder> …`, `<HEAD now>` read there).
