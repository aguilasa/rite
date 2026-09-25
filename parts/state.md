## State

Item frontmatter is the only state; the tables are views the CLI regenerates.

- `rite begin <kind> [--cycle C] [--id ID] --json` resolves the cycle, takes the item and returns its
  paths, the config digest and the commit template. Idempotent.
- `rite finish <ID> [--sha S] --json` closes the item from its work commit, runs `check --quick` and
  names the next one. Two commits per item — the work, then the CLI's record (a commit cannot hold its
  own SHA). No work commit, only a document outside git: `--no-repo --reason "…"`, never borrow HEAD.
- Others: `rite mark <ID> blocked|skipped --reason "…" --commit`, `mark-reviewed <ID> [--fixes …]`,
  `mark-stale <FIX> --reason "…"`, `rebind <ID> --sha <commit>` after a squash.
- A **local cycle** (`"local": true`) writes the same fields and commits nothing, by design; never
  commit its documents yourself.

Never write `status`, `done_on`, `done_commit`, `reviewed_on` by hand, never edit between
`<!-- rite:begin … -->` and `<!-- rite:end -->`, never invent an ID.
