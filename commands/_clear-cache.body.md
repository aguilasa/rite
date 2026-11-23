---
description: Delete the cached versions of the Rite plugin that are neither running nor installed
argument-hint: "[--yes]"
parts: [cli, asking, reporting]
---

# /rite:clear-cache

Arguments: `$ARGUMENTS`

Touches only the plugin cache: no repository file, no cycle, no commit. Needs no `rite.toml`. The
version this session runs and the one installed always stay — the commands of this session are read
from the first. `rite clear-cache` decides what may go; never delete a folder of the cache yourself.

## Steps

1. `rite clear-cache --dry-run --json`. Exit 1 → report its stderr (no installed entry, or a rite
   running from a checkout) and stop. `would_remove` empty → say what stays (`kept`, with `why`) and
   stop.
2. **Confirm**, always — the deletion cannot be undone; a version deleted is downloaded again only
   by reinstalling it. One AskUserQuestion: the versions of `would_remove` with their size, and what
   stays; options `Delete <n> version(s), <MB> (Recommended)` and `Keep them`. With `--yes`: delete
   nothing and report the dry run (asking's rule: never an option that deletes).
3. Yes → `rite clear-cache --json`. A refusal by a permission prompt or a policy: give the user the
   command, do not work around it.

## Report

Versions removed and the space freed, or "nothing removed" · what stayed and why (running,
installed) · when `state` is `reload-needed`: a `/reload-plugins` lets the next clear remove the
version this session still runs.

<!-- rite:parts -->
