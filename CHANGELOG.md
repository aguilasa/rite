# Changelog

All notable changes to this project are documented here. Versions follow [SemVer](https://semver.org/).

## [Unreleased]

Section titles are configurable, all of them. In a pt-BR repository `rite reproduce` returned six
open fixes as "no command" though each had `$ ` lines under `## Evidência`: the heading was looked for
in English only, it did not match, and the empty result read like a clean fix. The inline triage of
0.6.0 never ran there, and nothing said why. Now every title comes from `[sections]`, a repository can
have its own proposed from its files, and a missing title is reported instead of silent.

### Added

- **`[sections]` names every section Rite reads**: `evidence`, `verification`, `files`, `scope`,
  `gates`, `serialized_resources`, `confirmed_decisions` and `generated_artifacts` join
  `execution_log`, `phase_checks` and `phase_label`, with English defaults — a 0.6.0 `rite.toml` is
  valid unchanged. Each value may be a list: the first title is the one Rite writes, all are read.
- **`rite sections [--all] [--write]`** proposes the block from the titles items and profiles already
  use, recognising each section by what it holds, never by its words; every guess carries its
  evidence, a key nothing matches reliably comes out commented with its candidates, and `--write`
  merges only what matched, keeping comments and order. `/rite:init` uses it on an existing backlog.
- `rite reproduce` gives each fix `why`: `ok`, `no_section` (with `looked_for`, and `near`: headings
  that begin with a title without naming it), `no_command` or `unterminated`, and `heading`, the
  title it found.

### Changed

- `rite check` warns about an open fix with neither an evidence nor a verification title, and about a
  live profile with no gates title.
- `batch-plan` reads a files section listing bare paths (`- src/a.py (the parser)`) when the path
  exists. Gates stay bullets only: the one gates table measured was a catalogue of sixty tools, some
  starting an emulator, and every item runs its gates before closing. `rite sections` shows such a
  table as a commented candidate.
- **Multi-line evidence runs whole.** A `$ ` line ending in a backslash goes on over the next one,
  and a heredoc takes its body up to its delimiter. Run line by line, `python - <<'EOF'` got no body
  and waited on stdin, and exit 2 read like a reproduced symptom. A heredoc never closed runs nothing
  (`why: unterminated`). Evidence and gates run with stdin closed.
- **A heading with a separated suffix names its section**: `Evidência — e as três vezes`, `Log de
  Execução *(preenchido após execução)*`. An exact heading wins; a plain space is not a separator, so
  `Evidência de que não é artefato` stays another section, and `check` names it as a near miss.
- `rite sections` lets `files` and `scope` share a title, and leaves a key commented when the title
  Rite would write holds in under a tenth of the files.
- **Evidence must run from the repository as written.** The reviewer agent may still experiment in a
  scratch copy, but a `$` line may cite only versioned files, and a script it wrote goes whole into a
  heredoc. A fix opened by a review cited `python run.py` from a copy that no longer existed, and a
  heredoc holding its output instead of its script; neither could ever be reproduced. `rite check`
  now warns about both in an open fix: a script the repository does not have, and a `python -`
  heredoc that is not Python.
- `migrate --from we2002` writes the pt-BR titles in the `rite.toml` it generates.
- The plugin templates write the canonical titles, so a new fix in a pt-BR repository gets
  `## Evidência`.

## [0.6.0] — 2026-09-24

Tokens, not money, and the triage decided. The report stops pricing and counts: four kinds of token
apart, one cache-weighted number to compare, and every use of Claude Code, not only the rite's. With
the triage judged per batch instead of per fix, `/rite:fix-all` now triages inline and starts a
reproducer only for what inline cannot decide — and a run against 0.5.0 confirms it: the whole
invocation costs 15–36% less, with fewer main-thread turns.

### Changed

- **`rite cost` is now `rite tokens`**, and it counts, never prices. The `[cost]` table is gone (a
  `[cost]` section is now an unknown section); `docs/cost/` is `docs/tokens/`, `docs/COST.md` is
  [docs/TOKENS.md](docs/TOKENS.md). The measured matrices lost only their dollar fields; every token
  count is unchanged.
- **The unit.** Input, cache writes, cache reads and output are printed apart, with `billed` and
  turns. Comparisons use `effective = billed + w × cache_read`, `w = --cache-weight` (default 0.1),
  printed beside every effective number: a ratio of rates, not a price.
- **`/rite:fix-all` triages inline.** `rite reproduce --all` runs the whole batch's evidence in one
  call and the main thread writes each verdict. A `rite-reproducer` starts only for the residue: no
  command, output over `[limits].inline_triage_max_output_kb`, `CANNOT RUN`, or an output that does
  not decide. `/rite:fix` reproduces with `rite reproduce <FIX>`. The three verdict tokens live in
  `parts/evidence.md`, shared by inline triage and the agent.
- **Gates run in bash** — Git Bash on Windows, where `rite gates` used cmd.exe and a gate with POSIX
  quoting (`test "$(…)" = '…'`, `CI=1 npm test`) was red there and green in the model's own shell.
  `[gates].shell = "system"` keeps cmd.exe for gates written for it. The e2e harness checks symptoms
  in the same shell.
- The triage verdict of `tools/experiment.py` is judged per batch, in effective tokens: one
  main-thread turn serves the whole batch. It reports the turn-over N and the output one fix may hold
  inline, never a cap on the number of fixes. With several labels, its report compares them on the
  whole invocation.

### Added

- **`rite tokens` covers all of Claude Code.** A plain prompt is the row `(no command)`; other
  plugins' commands and skills keep their names. `--by command|session|day|project|agent`,
  `--since/--until` (UTC days), `--project` (`--glob` kept), `--markdown FILE` (deterministic),
  and a **Totals** block with the subagent and ceremony shares.
- **`rite reproduce <FIX>|--all [--tail N] [--scratch]`**: runs the `$ ` commands of a fix's fenced
  Evidence (else its Verification) in the gates' shell, and reports commands, exit codes, output, the
  recorded Evidence, `runnable` and `over_limit`. It measures and never judges.
- `[limits].inline_triage_max_output_kb = 6` and `[gates].shell = "bash"`.

### Fixed

- **A batch no longer loops on a gate that was red before it.** A wave whose gate is red aborts and
  leaves its items in progress; when the defect was already in HEAD, `rite status` resumed the same
  task and the next batch hit the same gate — the e2e lifecycle of both examples ran
  `/rite:execute-batch` until it was out of steps (a rule of 0.4.0, unnoticed since the baselines were
  from 0.3.0). The main thread now reruns the gates with the wave's edits stashed; still red, the
  defect is opened as a `high` fix with the gate output as Evidence, and `/rite:fix-all` repairs it
  before the wave resumes.
- **`/rite:close-cycle --yes` archives.** "Never choose an option that moves files" under `--yes` was
  read as forbidding the move the command exists for; the invocation is the confirmation.

### Measured

- **Inline triage wins from N = 2 up**, recomputed in effective tokens from the 0.5.0 matrix
  ([docs/tokens/2026-09-23-fixall-as-is.md](docs/tokens/2026-09-23-fixall-as-is.md)): reproducers
  against one main-thread turn per batch, 6,183 vs 7,570 at N = 1 (within the dispersion), 8,215 vs
  7,535 at N = 2, 16,416 vs 9,266 at N = 4. The gap grows with the batch, so there is no fix-count
  limit. Past about 7 KB of output per fix (6.8 KB at N = 4, 7.1 KB at N = 2), holding it inline costs
  more than that fix's reproducer: hence 6 KB.
- **Confirmed by a run against 0.5.0**: twelve runs of `/rite:fix-all` on `node-minimal` with Sonnet 5,
  N = 1, 2, 4, two repetitions each; every run valid, every symptom repaired. The whole invocation, in
  effective tokens, drops by 32%, 15% and 36%; main-thread turns drop too (12 → 10, 16 → 13.5,
  17 → 11.5), and no reproducer was started
  ([docs/tokens/2026-09-24-fixall-as-is-vs-inline.md](docs/tokens/2026-09-24-fixall-as-is-vs-inline.md)).
- **Baselines** of both examples re-recorded from a passing `run_loop` and `run_lifecycle` each; against
  the 0.3.0 ones, every command is 37–70% lower in billed tokens.

## [0.5.0] — 2026-09-23

Measuring what delegation costs. Until now the token report counted only the main thread, so every
command that hands work to a subagent looked cheaper than it is. It now counts the subagents, and a
seeded experiment turns their cost into a number: what one more fix costs a `/rite:fix-all`, with the
main thread and each agent type reported apart.

### Added

- `close`/`finish --no-repo --reason "…"`: close an item that has no work commit — its only artifact
  is a document outside git, as in a workspace. `done_commit` records the sentinel `none`, which `check`
  accepts; before, the item either borrowed an unrelated HEAD or had its frontmatter edited by hand and
  left `check` red.
- **`rite cost`** (`tools/token_report.py`) counts the subagents. Their turns sit next to the session,
  in `subagents/agent-<id>.jsonl`, and the report used to drop them, so delegating commands looked
  cheaper than they are. Each command now reports `agents` and `agent` (billed, cache reads, turns,
  per agent type) apart from the main thread. It adds USD when a `[cost]` table is declared. An agent
  call with no trace is `"unknown"`, never 0. `--check` fails on one agent more than the baseline.
  Only metrics are kept ([docs/COST.md](docs/COST.md)).
- **`tools/experiment.py`** measures what one more fix costs a `/rite:fix-all`. Each run starts from a
  fresh copy of an example with its tasks finished from a reference solution and N fixes opened
  through the CLI, so only the command under measurement calls the model. It fits a line (intercept =
  fixed ceremony, slope = cost per fix) and writes a deterministic report to `docs/cost/`.

### Measured

- **The subagent floor**: 7,122 billed tokens, $0.036, per fix in `/rite:fix-all`, split into a
  `rite-reproducer` at 2,367 tokens ($0.010) and a `rite-worker` at 4,756 ($0.026). The main thread
  adds 9,912 per fix on a fixed ceremony of 19,373. Run on `node-minimal` with Sonnet 5, N = 1, 2, 4,
  two repetitions each ([docs/cost/2026-09-23-fixall-as-is.md](docs/cost/2026-09-23-fixall-as-is.md)).
  An agent call costs about half a main-thread turn to one, so **delegate work that would cost the
  main thread more than about one turn**.
- **Inline triage for `/rite:fix-all`: inconclusive.** Holding the reproduction output inline is
  nearly free, but a reproducer costs only 0.49–0.90 main-thread turns per fix. Inline triage wins
  only if it adds fewer turns than that, which only a run with inline triage can count.

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
