# Rite

A Claude Code plugin for working through long backlogs with discipline:
**execute → review → fix**, one unit per invocation, independent reviews that *measure instead of read*,
and fixes that reproduce their evidence before touching code. Bookkeeping (status, dates, commits,
progress tables) is done by a deterministic CLI, never by hand.

Rite is agnostic of language, build tool and folder layout: each repository declares its own structure
and naming in `rite.toml`.

> Status: **v0.1 in progress.** Phase 0 (skeleton) and phase 1 (CLI) are done; the core rite
> (`execute`, `review`, `fix`), batches and lifecycle commands are next. See [Roadmap](#roadmap).

## Install

```text
/plugin marketplace add aguilasa/rite
/plugin install rite@rite
```

For local development: `claude --plugin-dir /path/to/rite`.

Requires Python 3.11+ on PATH (stdlib only) and git.

## Concepts

| Layer | Lives in | Holds |
| --- | --- | --- |
| **Rite** | this plugin | the generic procedure |
| **Repo config** | `rite.toml` | folders, naming, languages, commit policy, guarded paths, generators, gates |
| **Cycle profile** | `<profiles_dir>/<cycle>.md` | confirmed decisions, gates, hot files, phase-specific checks |
| **Item** | task / fix file | scope, `source_of_truth`, done criteria, execution log |

- A **cycle** is a folder with a `progress.md`. Tasks and fixes are one file each; their
  **frontmatter is the only state**. `progress.md` / `fixes.md` hold a generated table (between
  `<!-- rite:begin … -->` and `<!-- rite:end -->`) plus free notes.
- Finishing an item takes **two commits**: the work (`feat: …`), then `rite.py close <ID>`, which reads
  that commit and records status, date, SHA and file list in `chore(rite): close <ID>`.

## Commands

| Command | State |
| --- | --- |
| `/rite:status [cycle]` | available |
| `/rite:execute`, `/rite:review`, `/rite:fix` | phase 2 |
| `/rite:execute-batch`, `/rite:fix-all` | phase 3 |
| `/rite:init`, `/rite:new-cycle`, `/rite:plan-to-tasks`, `/rite:close-cycle`, `/rite:retro` | phase 4 |

## CLI

```sh
python3 bin/rite.py <subcommand> [--cycle C] [--root R] [--json]
```

| Subcommand | Does |
| --- | --- |
| `resolve-cycle [name]` | which cycle the rules select, with its prefix, profile and plan |
| `next task\|review\|fix` | deterministic selection (in-progress first, `depends_on`, severity for fixes) |
| `new-task`, `new-fix --origin ID` | atomic ID allocation from the templates |
| `close ID [--sha S]` | record a finished item from its work commit; commits the bookkeeping |
| `mark ID STATUS` | `pending`, `in-progress`, `blocked`, `skipped` |
| `mark-reviewed ID [--fixes F,…]` | record a review and the fixes it opened, in one commit |
| `mark-stale FIX --reason …` | close a fix whose symptom no longer reproduces |
| `sync` | regenerate the tables from frontmatter (idempotent) |
| `check [--quick]` | vocabulary, IDs, `source_of_truth` anchors, `depends_on`, links, views, profile |
| `status` | summary per cycle and the suggested next command |
| `guard PATH` | is the path read-only or generated (used by the hook) |

Exit codes: `0` ok, `1` failure / nothing selected, `3` no `rite.toml`.

## Configuration

See [docs/CONFIG.md](docs/CONFIG.md). A commented default file is in [templates/rite.toml](templates/rite.toml).

## Development

```sh
python -m unittest discover tests
```

Tests build throw-away git repositories in three layouts (sub-folder cycles, flat, and a legacy
Portuguese layout) and run the CLI against them, including planted defects that `check` must catch.
`tests/test_rite_is_agnostic.py` fails if a command names a concrete project, tool or absolute path.

## Roadmap

| Phase | Delivers | State |
| --- | --- | --- |
| 0 | plugin skeleton, templates, config schema, `/rite:status` | done |
| 1 | `rite.py` CLI + tests | done |
| 2 | shared fragments, `execute` / `review` / `fix`, agents, guard hook | next |
| 3 | `execute-batch`, `fix-all`, `batch-plan` | |
| 4 | `init`, `new-cycle`, `plan-to-tasks`, `close-cycle`, `retro`, `archive` | |
| 5 | migration guide and `rite.py migrate` | |
| 6 | release: eval suite, changelog | |

## License

MIT
