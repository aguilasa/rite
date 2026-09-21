# Rite

A Claude Code plugin for working through long backlogs with discipline:
**execute → review → fix**, one unit per invocation, independent reviews that *measure instead of read*,
and fixes that reproduce their evidence before touching code. Bookkeeping (status, dates, commits,
progress tables) is done by a deterministic CLI, never by hand.

Rite is agnostic of language, build tool and folder layout: each repository declares its own structure
and naming in `rite.toml`.

> Status: **0.1.0 released.** CLI, core rite, batches, lifecycle and migration; the end-to-end runs pass
> on both examples (Python and Node). See [CHANGELOG.md](CHANGELOG.md) and the [Roadmap](#roadmap).

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

| Command | Does |
| --- | --- |
| `/rite:init` | adopt Rite: detect conventions, write `rite.toml` |
| `/rite:new-cycle <name>` | create a cycle: folder, views, profile, pitfalls |
| `/rite:plan-to-tasks <plan>` | break a plan into tasks with anchored sources of truth and verifiable criteria |
| `/rite:status [cycle]` | where things stand; the next command to run |
| `/rite:execute [cycle] [ID]` | one task, two commits |
| `/rite:execute-batch [cycle] [N]` | N tasks in conflict-free waves |
| `/rite:review [cycle] [ID]` | independent review by the `rite-reviewer` agent; opens fixes |
| `/rite:fix [cycle] [ID]` | reproduce evidence, repair, sweep |
| `/rite:fix-all [cycle]` | parallel triage, then repairs in waves |
| `/rite:close-cycle <cycle>` | check preconditions, archive with links rewritten |
| `/rite:retro <cycle>` | root-cause groups; keep, promote, report, prune |

Details: [docs/COMMANDS.md](docs/COMMANDS.md) · concepts: [docs/CONCEPTS.md](docs/CONCEPTS.md).

## CLI

Commands never touch state by hand; they call a stdlib-only CLI:

```sh
sh bin/rite <subcommand> [--cycle C] [--root R] [--json]     # finds Python 3.11+ (RITE_PYTHON overrides)
python3 bin/rite.py <subcommand> ...                          # direct
```

`resolve-cycle`, `next`, `new-task`, `new-fix`, `commit-new`, `close`, `mark`, `mark-reviewed`,
`mark-stale`, `sync`, `check`, `status`, `batch-plan`, `new-cycle`, `archive`, `anchors`, `stats`,
`relink`, `migrate`, `guard` — see [docs/COMMANDS.md](docs/COMMANDS.md#cli). Exit codes: `0` ok, `1` failure / nothing
selected, `3` no `rite.toml`.

## Configuration

See [docs/CONFIG.md](docs/CONFIG.md). A commented default file is in [templates/rite.toml](templates/rite.toml).
Adopting an existing backlog: [docs/MIGRATING.md](docs/MIGRATING.md).

## Development

```sh
python -m unittest discover tests
```

Tests build throw-away git repositories in three layouts (sub-folder cycles, flat, and a legacy
Portuguese layout) and run the CLI against them, including planted defects that `check` must catch.
`tests/test_rite_is_agnostic.py` fails if a command names a concrete project, tool or absolute path.

## Examples

| Example | Stack | Gate | Generated artifact |
| --- | --- | --- | --- |
| [examples/python-minimal](examples/python-minimal) | Python, stdlib only | `python -m unittest discover -s tests` | — |
| [examples/node-minimal](examples/node-minimal) | Node 20+, no dependencies | `npm test` (`node --test`) | `src/index.mjs` from `tools/gen-exports.mjs` |

Each example carries an `e2e.json` manifest (cycle, prefix, plan, gate, a read-only path to probe and
a declarative defect). `tests/test_examples.py` keeps every example green under `rite check` and its
manifest honest — the end-to-end runs read the manifest, so they name no project, path or tool.

End to end, with a real headless Claude Code (costs tokens). Both runs take `--example`
(default `python-minimal`) and work on a throw-away copy:

```sh
python tests/e2e/run_loop.py --example node-minimal --model sonnet
```

Execute → planted defect → review (must open a fix) → fix → write to the read-only path (must be
blocked by the hook).

```sh
python tests/e2e/run_lifecycle.py --example node-minimal --model sonnet
```

From zero (the example stripped of its `rite.toml` and cycle): init → new-cycle → plan-to-tasks →
execute-batch → planted defect → an autopilot that runs whatever `rite status` suggests
(execute-batch / execute / review / fix-all) → close-cycle → retro, asserting `rite check` and one
close commit per done item after every step.

## Guards

`hooks/hooks.json` registers a `PreToolUse` hook on Edit/Write/MultiEdit/NotebookEdit that blocks
paths listed in `[guards].read_only` and `[[guards.generated]]` (pointing at the generator instead).
It is inert in repositories without `rite.toml`. Shell writes are not visible to hooks; the rite
forbids them in prose.

## Roadmap

| Phase | Delivers | State |
| --- | --- | --- |
| 0 | plugin skeleton, templates, config schema, `/rite:status` | done |
| 1 | `rite.py` CLI + tests | done |
| 2 | shared fragments, `execute` / `review` / `fix`, agents, guard hook | done; e2e loop passes on both examples |
| 3 | `execute-batch`, `fix-all`, `batch-plan` | done; e2e lifecycle passes on both examples |
| 4 | `init`, `new-cycle`, `plan-to-tasks`, `close-cycle`, `retro`, `archive` | done; e2e lifecycle passes on both examples |
| 5 | migration guide, `rite.py migrate --from we2002`, `relink` | done; measured on a clone of the source repository (no delta against the old tables) |
| 6 | release: changelog, version tag | done — 0.1.0 |

## License

MIT
