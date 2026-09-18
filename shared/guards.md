# Guards

`rite.toml [guards]` declares paths no command may write:

- `read_only` — never written, by any tool. The plugin's hook blocks Edit/Write; you must not write
  them through the shell either (redirects, in-place edits, scripts). Why: the hook cannot see shell writes.
- `generated` — output of a generator. The defect is in the generator or its input: edit that, run
  the generator, then its `check` command, and commit generator and output together. Never hand-edit
  output: the next regeneration silently reverts it.

If the item cannot be done without writing a guarded path, stop and report why; do not work around it.
When unsure, `rite guard <path> --json`.
