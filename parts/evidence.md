## Evidence

- **Measure, do not read.** A claim counts only when you ran its command in this invocation and saw
  the output; logs are leads. Reviews that read instead of ran approved broken work.
- **Every number has a tool** versioned in the repository; quote the command beside the number.
- **Control before test**: before trusting a checker, show it can fail.
- **Reproduce before fixing.** Symptom gone → the fix is *stale* (`rite mark-stale`), not fixed.
- **Negative results are results**: record "X does not work, because Y (command, output)".
- **Gates** run through `rite gates [--id <ID>] --json`. A red gate means the item is not done: fix it,
  or stop and report the output it returned.
