---
description: Open a live, read-only board of the Rite cycles in the browser — open and closed cycles, tasks, fixes, each item's markdown
argument-hint: "[--restart] [--port P] [--no-browser]"
allowed-tools: Bash, Read
parts: [cli]
---

# /rite:board

Arguments: `$ARGUMENTS`

Read-only: change nothing, commit nothing. The board is a local web page the user reads; it follows
every state change by itself, so nothing here re-runs once it is up. One board per repository: a
board this rite already serves is reused; one an older install started (it serves old code) is
replaced, on the same port.

1. Start `rite serve --if-stale` — `rite serve --restart` when `$ARGUMENTS` has `--restart` — with
   the `--port` / `--no-browser` given, **in the background** (Bash `run_in_background`): it serves
   until stopped and would hold the turn. A new board tries port 3000, then 3001… (or the port of the
   board it replaced) and opens the system's browser once it listens.
2. Wait for its first output line, `rite board: <url> …`:
   - `(already running, pid N)` → that board serves this repository with this rite; the process
     just started has exited. Report its URL; start nothing else.
   - `; stopped pid N (rite X)` → the old board was stopped and this one replaces it: say so.
   - Exit `3` → answer exactly `No rite.toml in this repository — run /rite:init first.` and stop.
     Exit `1` → report its stderr (no free port, bad `--host`, an old board to stop by hand) and stop.

## Report

Three lines at most: the URL · that the page updates itself when a task or fix changes (and, when a
board was replaced, the rite version it served) · how to stop it (stop the background task, or
Ctrl+C where `rite serve` runs). A "could not open a browser" line on stderr → say to open the URL
by hand.

<!-- rite:parts -->
