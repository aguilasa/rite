# Step 0 — resolve the cycle and the item

1. Split `$ARGUMENTS`: a token shaped like an item ID of this repository is the **item**; the first
   other plain token is the **cycle**; flags and counts are handled by the command.
2. Run `rite resolve-cycle [cycle] --json`. It applies the rules in order: explicit argument,
   `default_cycle`, flat layout, the only live cycle. If it reports several live cycles, stop and ask
   which one — do not guess. Why: work landing in the wrong cycle corrupts two ledgers.
3. Keep from its output: `path`, `prefix`, `progress`, `fixes`, `profile`, `pitfalls`, `plan`,
   `ticket` and `local` (see `commit-policy.md` for what a local cycle changes).
4. If no item was given, the command selects it with `rite next <kind> --cycle <cycle> --json`.
   When that exits `1`, report its `reason` and `blocked_by` and stop. If an item was given, confirm
   it lives in this cycle's folder and that its `depends_on` are `done`, `skipped` or `stale`; if not,
   stop and report what blocks it.
