---
description: Open a live, read-only board of the Rite cycles in the browser — open and closed cycles, tasks, fixes, each item's markdown
argument-hint: "[--port P] [--no-browser]"
allowed-tools: Bash, Read
parts: [cli]
---

# /rite:board

Arguments: `$ARGUMENTS`

Read-only: change nothing, commit nothing. The board is a local web page the user reads; it follows
every state change by itself, so nothing here re-runs once it is up.

1. Start `rite serve` with the `--port` / `--no-browser` given in `$ARGUMENTS` — **in the background**
   (Bash `run_in_background`): it serves until stopped and would hold the turn. It tries port 3000,
   then 3001, 3002… and opens the system's browser once it listens.
2. Wait for its first output line, `rite board: <url>  (Ctrl+C to stop)`. Exit `3` instead →
   answer exactly `No rite.toml in this repository — run /rite:init first.` and stop. Exit `1` →
   report its stderr (no free port, bad `--host`) and stop.

## Report

Three lines at most: the URL · that the page updates itself when a task or fix changes · how to stop
it (stop the background task, or Ctrl+C where `rite serve` runs). A "could not open a browser" line
on stderr → say to open the URL by hand.

<!-- rite:parts -->
