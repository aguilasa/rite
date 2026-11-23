---
description: Update the Rite plugin to its latest version, then say how to load it
argument-hint: ""
parts: [cli, reporting]
---

# /rite:update-plugin

Arguments: `$ARGUMENTS`

Updates the installed plugin only: no repository file, no cycle, no commit. Needs no `rite.toml`.
Deletes nothing — old versions are `/rite:clear-cache`. A session keeps running the version it
started with: only the user can load the new one, with `/reload-plugins` or a restart; no command
can run that for them.

## Steps

1. `rite plugin-info --json`. `state: not-installed` → this rite runs from `running.root`, not from
   an installed copy: say it updates by its own means (git), and stop.
2. Run `commands.refresh` (it fetches the marketplace), then `rite plugin-info --json` again.
3. By `state`:
   - `up-to-date` → say the version, and stop.
   - `reload-needed` → the latest is installed but this session runs `running.version`: tell the
     user to run `/reload-plugins`, and stop.
   - `update-available` → run `commands.update`, then `rite plugin-info --json`: `installed.version`
     must equal `latest`; else report the command's output and stop.
4. A `claude plugin` command refused by a permission prompt or a policy: do not work around it —
   give the user the exact command to run, and stop.

## Report

Version before → after (or "already up to date") · the commands run · next: `/reload-plugins` (or a
restart) to load it, and `/rite:clear-cache` when `cache` holds versions that are neither running
nor installed — or will, once the reload leaves the old one unused.

<!-- rite:parts -->
