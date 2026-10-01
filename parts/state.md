## State

The cycle's `progress.json` (meta + tasks) and `fixes.json` are the only state; item files hold prose
and their `id`; the tables in the progress and fixes files are views the CLI renders from the JSON.

- `rite begin <kind> [--cycle C] [--id ID] --json` resolves the cycle, takes the item and returns its
  paths, the config digest and the commit template. Idempotent.
- `rite finish <ID> [--sha S] --json` closes the item from its work commit, runs `check --quick` and
  names the next one. Two commits per item — the work, then the CLI's record (a commit cannot hold its
  own SHA). No work commit, only a document outside git: `--no-repo --reason "…"`, never borrow HEAD.
- Others: `rite mark <ID> blocked|skipped --reason "…" --commit`, `mark-reviewed <ID> [--fixes …]`,
  `mark-stale <FIX> --reason "…"`, `rebind <ID> --sha <commit>` after a squash.
- A fix blocked by the environment adds `--unblocked-by "<command that passes once it is there>"`.
  Partial work: commit what is coherent, then `mark blocked` with the `--reason` naming what is
  missing and the partial SHA — never `close` (not done), never `mark-stale` (the symptom is there).
- A **local cycle** (`"local": true`) writes the same fields and commits nothing, by design; never
  commit its documents yourself.

- Planning fields: `rite set <ID> --files a,b --resources r`; the cycle's `order`, `ticket`, `plan`:
  `rite set-cycle --cycle C --order <IDs>`. The only fields you write, and only through these.

Never edit `progress.json` / `fixes.json` (the guard refuses it), never put fields back into an item's
frontmatter, never edit between `<!-- rite:begin … -->` and `<!-- rite:end -->`, never invent an ID.
