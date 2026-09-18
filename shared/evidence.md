# Evidence rules

- **Measure, do not read.** A claim ("tests pass", "N rows", "output identical") counts only when you
  ran the command in this invocation and saw the output. Logs, commit messages and the item's own
  Execution Log are leads, not truth. Why: reviews that read instead of ran approved broken work.
- **Every number has a tool.** A number written into docs, items or reports comes from a command
  versioned in the repository; quote the command next to it. No hand counts, no estimates presented
  as measurements.
- **Control before test.** Before trusting a comparison or checker, show it can fail: original against
  original reports zero differences, and a deliberately planted defect turns it red. Why: a checker
  that cannot fail proves nothing.
- **Reproduce before fixing.** Run the evidence command first. If the symptom is gone, the fix is
  *stale*: record it with `rite mark-stale`; do not "fix" code that is now right.
- **Negative results are results.** "Approach X does not work, because Y (command, output)" completes
  a research item. Record it; do not bend the conclusion to fit the plan.
- **Gates.** Before closing, run `[gates].global` from `rite.toml` and the profile's Gates. A failing
  gate means the item is not done: fix it, or stop and report with the output.
