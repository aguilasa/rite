## Evidence

- **Measure, do not read**: a claim counts only if you ran its command here; logs are leads.
- **Every number has a tool**: quote its versioned command beside it.
- **Control before test**: before trusting a checker, show it can fail.
- **Reproduce before fixing** (`rite reproduce <FIX> --json`, `--scratch` if it writes files):
  `REPRODUCED` → fix it · `NOT REPRODUCED` (`why: ok`, output contradicts the Evidence) → *stale*
  (`rite mark-stale`) · else `CANNOT RUN` (other `why`, `shell_error`, missing path) → an agent or a
  person, never *stale*. An exit code is not a verdict.
- **Negative results are results**: "X fails, because Y (command, output)".
- **Gates**: `rite gates [--id <ID>] --json`. Red means not done: fix it, or stop and report its
  output.
