# Calling the Rite CLI

Every state read and every state change goes through `rite.py`; never edit `status`, dates,
commits or the generated tables by hand. Why: bookkeeping written by hand drifts, and drift
was the largest single source of fixes in the system Rite was extracted from.

Invoke it as:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/bin/rite.py" <subcommand> [args] --json
```

Use `python` when `python3` is not on PATH. Python 3.11+ is required; the CLI is stdlib only.
Run it from the repository (it finds `rite.toml` upward) or pass `--root <repo>`.

Exit codes: `0` ok · `1` failure, or nothing selected by `next` · `3` no `rite.toml` in this repository.
On exit `3`, stop and tell the user to run `/rite:init`; do not create files.

Prefer `--json` and read the fields; the text output is for humans.
