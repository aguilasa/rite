# Discrepancy sweep

After every item, before its work commit, search the repository for what you changed:

1. List the changed *terms*: renamed symbols, files, flags, commands, config keys, numbers you
   re-measured, behaviours you altered.
2. For each, `grep -rn` across docs, the plan, `CLAUDE.md`, `rite.toml`, the profile, the pitfalls
   file, other items of the cycle, scripts and CI config.
3. Fix every stale mention this item owns. For a mention owned by another pending item, write a note
   in *that* item's Notes section — the destination — not only in your report. Why: a follow-up that
   lives only in a chat transcript is lost.
4. State in the report what you searched and what you updated, or `sweep: no stale mentions`.

Once per item, not once per batch. Why: stale mentions compound — the next item builds on them.
