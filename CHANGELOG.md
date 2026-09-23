# Changelog

All notable changes to this project are documented here. Versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added

- `close`/`finish --no-repo --reason "…"`: close an item that has no work commit — its only artifact
  is a document outside git, as in a workspace. `done_commit` records the sentinel `none`, which `check`
  accepts; before, the item either borrowed an unrelated HEAD or had its frontmatter edited by hand and
  left `check` red.

## [0.4.0] — 2026-09-22

Cutting what an invocation costs. The measurement came first: `tools/token_report.py` reads Claude
Code's transcripts and reports, per command, the median billed tokens, cache reads, turns and the tool
calls behind them. On the 0.3.0 runs of the examples it found the three generators — ceremony in
separate turns (8 fragment reads plus 8 CLI calls around one trivial task), whole documents read (a
84 KB profile, a 191 KB plan), and untruncated command output.

### Added

- **Composite subcommands**, each answering a whole step instead of a part of it: `begin` (resolve,
  select, take, config digest, commit template — idempotent), `context` (the item, its anchored
  source-of-truth section, the profile rules that apply and the matching pitfalls, capped by
  `[output].context_kb`), `gates` (global and profile gates, truncated unless red), `sweep` and
  `finish` (close + check + next).
- `tools/token_report.py` and `tests/baselines/*.json`: the 0.3.0 measurement, with `--check` failing
  when a command regresses beyond a tolerance.
- `tools/build_commands.py`: commands are assembled from `commands/_<name>.body.md` plus the rules in
  `parts/`, each rule written once. `--check` (in the test suite) fails when a command on disk differs.
- `[output].context_kb`, `[limits].read_kb`, `[limits].delegate_above_kb`, `[limits].sweep_hits`.

### Changed

- **Commands carry their rules**: `shared/` is gone and no command sends the reader to another file.
  Each stays under 8 KB, enforced by a test.
- The work commands run `begin → context → work → gates → sweep → commit → finish`: **5 CLI calls and
  no fragment reads**, against 8 reads plus 8 calls in 0.3.0.
- Reading rules are explicit: never open a document above `[limits].read_kb` whole, never read one
  twice, and reports stop at 15 lines. The reviewer, worker and reproducer agents are handed the
  `rite context` payload and may not reopen what it contains.
- `/rite:execute` delegates the implementation to a worker when the repository is above
  `[limits].delegate_above_kb` — the pattern that made `review` cost three times less.
- The CLI is found by `${CLAUDE_PLUGIN_ROOT}`, then `RITE_HOME`, then `PATH`; no command searches the
  disk for it.

### Measured, on the two repositories that use Rite

| | 0.3.0 | 0.4.0 |
| --- | --: | --: |
| Ceremony per `/rite:execute` (fragment reads + CLI calls) | 16 | 5 |
| Documents loaded for `LOOKS-TASK-39` (84 KB profile + 191 KB plan + item) | 277 KB | 33 KB (24 KB context + the 8 KB command) |
| `context` for `TOOL-TASK-04` (12-task cycle, `mastersystem`) | — | 4 KB |

The end-to-end token comparison per command was not re-measured: the examples' e2e runs were replaced
by exercising the new CLI against both real repositories (`begin`, `context`, `gates`, `sweep`,
`finish`, `check`), which is where the budget-sharing defect below was found.

### Fixed

- `context` shares its budget smallest-first instead of filling it in order: a 26 KB item file used to
  leave the plan section and the profile rules at zero bytes.

## [0.3.0] — 2026-09-21

### Added

- **Workspace mode.** `rite.toml` may live in a plain folder whose sub-folders are git repositories.
  Each task and fix names its repository in `repo:` (`new-task --repo`; a fix inherits its origin's);
  `close`, `rebind`, `mark-reviewed`, `mark-stale` and `check` read commits there, and every cycle is
  local. `resolve-cycle` reports `workspace` and `repos`; `commit-refs` reports the item's `repo`;
  `batch-plan` compares `files:` only within one repository. New `shared/workspace.md` tells the
  commands and agents to work and commit inside the item's repository.

## [0.2.0] — 2026-09-21

### Added

- **Ticket per cycle.** `ticket: PROJ-123` in a progress file (`new-cycle --ticket`) puts the key in
  every commit of the cycle, work and bookkeeping alike; `[commit].ticket_format` chooses a trailer
  (default `Refs: {ticket}`) or a subject template (`{ticket} {subject}`).
- **Local cycles.** `local: true` (`new-cycle --local`) keeps a cycle's documents out of git: the CLI
  writes state to the item files and makes no bookkeeping commit, and work commits carry no
  `Refs: <ID>`. `check` warns when `local` and `.gitignore` disagree. `publish <cycle>` turns a local
  cycle into a tracked one in one commit.
- `commit-refs <ID>`: the subject template and trailers an item's work commit must carry; commands take
  references from it instead of writing `Refs: <ID>` themselves.
- `rebind <ID> --sha <commit>`: repoint `done_commit` after a squash or rebase, keeping the review.
- `check` warns when a `done_commit` is not in HEAD's history, and its errors for a missing commit
  suggest `rebind`.

### Fixed

- `close` recognises a bookkeeping commit at HEAD when a ticket precedes its subject.

## [0.1.1] — 2026-09-21

### Added

- `order:` in a progress file's frontmatter sets the execution order of its tasks (listed IDs
  first, the rest by number); `next`, `batch-plan` and the generated table follow it. `migrate` writes it
  when a legacy table's row order was not the ID order.

### Fixed

- `check` reads phase ranges in a profile's phase-checks section ("Phase 4-5", "Fase 6–7") as covering
  every phase in them; single phases were the only form it recognised.

## [0.1.0] — 2026-09-21

First release.

### Added

- `rite.py` CLI (Python 3.11+, stdlib only): `resolve-cycle`, `next`, `new-task`, `new-fix`, `commit-new`,
  `close`, `mark`, `mark-reviewed`, `mark-stale`, `sync`, `check`, `status`, `batch-plan`, `new-cycle`,
  `archive`, `relink`, `anchors`, `stats`, `guard`, `migrate --from we2002`.
- Commands: `/rite:init`, `/rite:new-cycle`, `/rite:plan-to-tasks`, `/rite:status`, `/rite:execute`,
  `/rite:execute-batch`, `/rite:review`, `/rite:fix`, `/rite:fix-all`, `/rite:close-cycle`, `/rite:retro`.
- Agents: `rite-reviewer`, `rite-worker`, `rite-reproducer`.
- Hooks: `PreToolUse` guard for read-only and generated paths; optional `Stop` check.
- `rite.toml` repo config with validation; templates for items, views, profiles, plans and retros.
- `[naming]` templates accept a list: the first names new items, the others are read-only shapes kept
  for items an earlier convention named differently.
- `sync`, `check` and `relink` take `--include-archived`.
- Two examples, `python-minimal` and `node-minimal` (Node 20+, `node --test`, a generated entry point
  with a `--check` generator), each with an `e2e.json` manifest.
- Tests: unit and CLI suites over three fixture layouts, every example checked by `rite check`, and two
  end-to-end runs with headless Claude Code (`run_loop`, `run_lifecycle`) driven by `--example`.

### Migration (`migrate --from we2002`)

- Moves legacy state (emoji tables, pt-BR statuses, dates in columns, `§` section references) into
  frontmatter and turns the tables into generated regions — every state table of a file, not just the
  first.
- Records an approximated `done_commit` in the item's Execution Log, not only in the report.
- Never invents an anchor or a phase: it keeps what it can prove and lists, per item, what the operator
  has to decide.
- Measured on the source repository (four cycles, 407 items): every cycle matches its old tables with no
  delta — see `docs/MIGRATING.md`.
