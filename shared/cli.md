# Calling the Rite CLI

Every state read and every state change goes through the CLI; never edit `status`, dates, commit
SHAs or the generated tables by hand. Why: hand-written bookkeeping drifts, and drift was the largest
single source of fixes in the system Rite was extracted from.

```sh
sh "${CLAUDE_PLUGIN_ROOT}/bin/rite" <subcommand> [args] --json
```

The launcher finds a Python 3.11+ interpreter (set `RITE_PYTHON` to force one). Run it from inside the
repository (it finds `rite.toml` upward) or pass `--root <repo>`. In the rest of the rite, `rite <sub>`
means this invocation.

Exit codes: `0` ok · `1` failure, or nothing selected by `next` · `3` no `rite.toml`.
On `3`, stop and tell the user to run `/rite:init`; create nothing.
On `1`, read stderr: it names the rule that refused. Do not retry with `--force` unless the user asks.

Prefer `--json` and read its fields; the text output is for humans.
