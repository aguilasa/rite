## The CLI

Every state read and every state change goes through it; never edit `status`, dates, SHAs or the
generated tables by hand — hand-written bookkeeping drifts.

```sh
sh "${CLAUDE_PLUGIN_ROOT}/bin/rite" <subcommand> [args] --json
```

Find it in that order, never by searching the disk: `${CLAUDE_PLUGIN_ROOT}/bin/rite`, `$RITE_HOME/bin/rite`,
`rite` on `PATH`; none → ask the user. Below, `rite <sub>` means that invocation, run inside the
repository or with `--root <repo>`. Prefer `--json`.

Exit codes: `0` ok · `1` failure or nothing selected (stderr names the rule; do not retry with
`--force` unless asked) · `3` no `rite.toml` — stop and tell the user to run `/rite:init`.
