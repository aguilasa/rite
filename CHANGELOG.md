# Changelog

All notable changes to this project are documented here. Versions follow [SemVer](https://semver.org/).

## [Unreleased]

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
