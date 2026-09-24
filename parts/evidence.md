## Evidence

- **Measure, do not read.** A claim counts only if you ran its command here and saw the output; logs
  are leads.
- **Every number has a tool**: quote its versioned command beside the number.
- **Control before test**: before trusting a checker, show it can fail.
- **Reproduce before fixing** (`rite reproduce <FIX> --json`, `--scratch` if it writes files):
  `REPRODUCED` → fix it · `NOT REPRODUCED` → *stale* (`rite mark-stale`), not fixed · `CANNOT RUN` →
  an agent or a person, never a guess.
- **Negative results are results**: "X fails, because Y (command, output)".
- **Gates** run through `rite gates [--id <ID>] --json`. A red gate means not done: fix it, or stop and
  report its output.
