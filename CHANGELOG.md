# Changelog

All notable changes to this project are documented here. Versions follow [SemVer](https://semver.org/).

## [Unreleased]

`[limits].inline_triage_max_output_kb = 7` came from a small example. Measured on a real repository,
a reproducer costs twenty times what it costs there, and the break-even is 72 KB, not 7: the limit
is the repository's, not the plugin's. Now the repository measures it.

### Added

- **`rite tokens --suggest-limits`**: from the window's `/rite:fix-all` runs, a reproducer against a
  main-thread turn of the same project, the limit per batch size (N = 1, 2, 4) and the value to put in
  `rite.toml`, with the inputs, how many invocations and agents back them, the formula and the weight.
  Fewer than 3 measured reproducers, or no `/rite:fix-all`, give `insufficient data` naming what is
  missing (exit 2). It states its scope and honours `--project`, `--since`, `--until`, `--latest`;
  `--json` has the raw numbers.

### Changed

- The default stays 7, but `templates/rite.toml`, `docs/CONFIG.md` and the config comment say what it
  is — the break-even of a small example — and point to `--suggest-limits`. Triage itself is unchanged.
- Measurement recorded in `docs/tokens/2026-09-25-inline-triage-limit.md`.

## [0.10.1] — 2026-09-25

A blocked fix is waiting, not gone. The first run with the new state showed the rest of Rite
treating it as out of the backlog: `check` stopped verifying its Evidence — hiding a broken one for
exactly as long as there was time to fix it — and `status` counted three waiting fixes as zero.

### Fixed

- **One definition of an open fix**: `pending`, `in-progress` or `blocked` (`OPEN_FIX_STATUSES`);
  `done` and `stale` are closed. `check` verifies the sections and Evidence of every open fix,
  blocked included, and stays silent on closed ones.
- **`status` counts blocked fixes** in `open_fixes` by severity and apart in `open_fixes_blocked`;
  the text line reads ``blocked: N — <ID> until `<command>` passes, …``. A blocked critical or high
  fix does not suggest `/rite:fix`: there is nothing to pick.
- **Counting is not picking**: `next fix` and `batch-plan` leave blocked fixes out where they pick.
- **`mark-stale` on a blocked fix** says why not: stale needs the symptom measured, so mark it
  pending once `unblocked_by` passes and reproduce. `archive` still refuses a cycle holding one.

## [0.10.0] — 2026-09-25

A fix the environment would not let finish — an emulator, a credential, hardware missing — had no
state: `mark … blocked` was refused for a fix, so it stayed `in-progress` with nobody on it, or went
back to `pending` and the next run tripped on the same block. A blocked fix now names the command
that unblocks it, and Rite runs that command to re-evaluate the block.

### Added

- **`rite mark <FIX> blocked --reason "…" --unblocked-by "<command>"`.** The command goes to the
  fix's `unblocked_by`; without it the mark is refused — a block with no exit test is a lost item.
  Leaving `blocked` clears it.
- **`next fix` skips a blocked fix** and names the command that unblocks it, with a pick or without.
- **`reproduce --all` includes blocked fixes**: their `unblocked_by` runs in place of the evidence,
  reported under `unblock`. `/rite:fix-all` triage marks a fix `pending` when it passes.
- **`check`**: error on a blocked fix without `unblocked_by`; warning when the command runs a script
  that is not in the repository. `status` lists blocked fixes; `archive` refuses a cycle holding one.

### Changed

- **Partial work is blocked, not pending** (`parts/state.md`): commit what is coherent, `mark blocked`
  with the missing part and the partial SHA in the reason. `/rite:fix` and the batch rules pass
  `--unblocked-by`, which they needed and the CLI refused.
- **`migrate`** does not invent a command: a legacy blocked fix becomes `pending`, with a warning.

## [0.9.3] — 2026-09-25

`rite tokens --check` compared a baseline of one measurement against every run a glob matched — 27
e2e runs of many versions, 109 invocations against 18. The gate was red on history, not on a
regression. A measurement now carries its scope, and the check compares it before any number.

### Fixed

- **`--check` compares scope before numbers.** A measurement records in `window` how many sessions
  and project folders it spans. When it spans more than the baseline, the check fails with a scope
  line naming both sides — `SCOPE this measurement spans 109 invocation(s) in 109 session(s) across
  27 project folder(s); the baseline 14 in 14 across 1 — not a regression` — and exits 3, not 1. A
  baseline without scope is named, not trusted blindly.
- **A `--dir` that does not exist** is nothing measured (exit 2), not a traceback.

### Added

- **`rite tokens --latest`** keeps only the project folder written last among those matched: the run
  just made, not the sum of every run. For a baseline, measure one run: `--dir` of its folder, or
  `--latest`.
- **The e2e runs check their own tokens.** `run_loop.py` and `run_lifecycle.py` end with a check of
  that run's transcripts against its baseline. It reports, it does not fail the run: tokens vary
  between runs of the same model, and the run's verdict is behaviour.

### Changed

- **One baseline per e2e script:** `tests/baselines/<example>.loop.json` and
  `<example>.lifecycle.json`, each one run. The old files each summed a loop run and a lifecycle run.
  Re-recorded from the same 0.6.0 transcripts: each pair reproduces the old file number for number,
  so only the scope is new.

## [0.9.2] — 2026-09-25

`rite tokens` saw a command only when it was typed. A command entered through the `Skill` tool — a
pasted instruction, a model-invoked skill — fell into `(no command)`, so a real `/rite:fix-all` run
was missing from the report. Both doors now count, under the same name.

### Fixed

- **`rite tokens` counts commands invoked through the `Skill` tool.** An invocation opened only on
  `<command-name>`, the marker of a typed slash command. A `Skill` call now opens one too, named as
  the typed door (`rite:fix-all` is `/rite:fix-all`); a `Skill` call naming the invocation already
  open continues it, so a typed command is never counted twice. The invocation starts at the turn of
  the call: in a pasted instruction, the turns spent reading it stay in `(no command)`. The baselines
  are unchanged — both e2e transcript sets report the same numbers before and after.

## [0.9.1] — 2026-09-25

What 0.9.0 left behind. `/rite:fix-all --plan` still ran a triage that could close a fix, the
pinned-revision warning flagged `git log <sha>..HEAD`, and the 8 KB command cap had started to decide
the wording of rules. `--plan` now measures and reports without writing item state, an open range is
not a pinned revision, and the cap is 10 KB.

### Changed

- **The command cap is 10 KB.** The 8 KB cap was a guess, not a measure, and it had started to decide
  the wording: `fix-all.md` sat at 8191 bytes and 0.9.0 condensed the `cli`, `commit` and `evidence`
  parts to fit. A command is read whole on every invocation; 10 KB is about 2.8k tokens, 0.6k more.
  Past it, prose moves to a shared part or to `docs/CONCEPTS.md` — the cap does not go up again. The
  condensed lines are restored where they had lost a rule: every state read and change goes through
  the CLI, the trailers exist so `git log --grep` finds an item's commits, and a red gate is reported
  with its output.

### Fixed

- **`--plan` measures and reports, never writes item state.** `/rite:fix-all --plan` ran the whole
  inline triage before it stopped, and the triage runs `rite mark-stale` — it closes a fix and commits
  — and pastes output into the Execution Log: a planning run could take a fix out of the backlog. With
  `--plan` the triage is now dry: each verdict is reported, inline or residue, with no `mark-stale`, no
  Execution Log and no reproducer agent; the plan covers every fix but the `NOT REPRODUCED` ones.
  `/rite:execute-batch --plan` no longer moves a `blocked` task whose cause is gone back to `pending`;
  it reports it. The batch rule says it in one sentence: with `--plan`, only planning fields (`files:`,
  `resources:`) are written; status, dates, SHAs and the Execution Log never are.
- **An open range is not a pinned revision.** The 0.9.0 warning took any hash in a `git log` or
  `git diff` for a fixed revision, so `git log <sha>..HEAD` — legitimate evidence that a change is not
  in yet, and whose output moves with HEAD — was flagged. A range is fixed only between two hashes;
  one with `HEAD`, a branch, a tag or an empty side (`<sha>..HEAD`, `<sha>...main`, `<sha>..`) is not.

## [0.9.0] — 2026-09-25

What the first real `/rite:fix-all --plan` exposed. A planning run marked its first fix `in-progress`
and so chose what the next run resumed; a file cited as `grep -n` prints it (`docs/x.md:512`) slipped
past the conflict matrix, and two fixes editing it shared a wave; and Evidence that reads a pinned git
revision reproduced forever. `--plan` now takes no item, a location suffix is dropped before a path
is compared, and `rite check` warns on a command that can never turn green.

### Fixed

- **`--plan` takes no item.** `/rite:fix-all --plan` and `/rite:execute-batch --plan` called `rite
  begin` before they knew they would only plan, and `begin` marked the first item `in-progress` — a
  read-only run then decided what the next run resumed first (`in-progress fix resumes first`).
  `rite begin --no-claim` resolves cycle, item, paths and config without marking; both bodies pass it
  under `--plan`.
- **A path cited at a line still conflicts.** `batch-plan` inferred `docs/x.md:512` (a code span) as
  that string and dropped a bare `- docs/x.md:512`, so two fixes naming one file, one of them as
  `grep -n` prints it, shared a wave. `paths_in` now drops `:12`, `:12:7`, `#L12` and `#L12-L20` before
  it tests the path, and returns each file once.

### Added

- **`rite check` warns on Evidence that can never turn green.** A command that reads a commit named by
  its hash (`git show <sha>`, `git log <sha>`, `git ls-tree <sha>`, `git diff <sha> <sha>`, a `for rev
  in <sha> …` loop) prints the same before and after the repair, so the triage reads `REPRODUCED`
  forever. The warning names the fix and the command; `git diff <sha>` alone compares with the working
  tree and is not flagged. `parts/evidence.md` says Evidence must pass once fixed, and `/rite:review`
  keeps a finding only when one of its commands runs on the working tree. To stay under the 8 KB per
  command, `parts/cli.md`, `commit.md` and `state.md` say the same in fewer words.

## [0.8.0] — 2026-09-24

The triage cannot close a fix by mistake. `mark-stale` is its one destructive outcome, and until now
nothing said which results never lead there: a missing heading, no command, a shell that could not
run the command. Now only an output measured under `why: ok` that contradicts the recorded Evidence
marks a fix stale; everything else goes to the residue. The inline limit is the number the
2026-09-24 run measured, 7 KB, and the lifecycle e2e checks that the triage stays inline and sends
only the residue to an agent.

### Added

- **The lifecycle e2e asserts the triage, not only that it ran.** Every autopilot `/rite:fix-all`
  must triage the example's small evidence with no `rite-reproducer`, and a new step plants the
  manifest's `residue_defect`, whose evidence prints past `[limits].inline_triage_max_output_kb`, and
  expects exactly one. A unit test checks, without a model, that the planted fix is over the limit.
- `rite reproduce` tests for a quoted path with a space and a leading `VAR=x`: a missing path or
  command is exit 127 with `shell_error` set.

### Changed

- **`[limits].inline_triage_max_output_kb` defaults to 7**, the break-even the 2026-09-24 run measured
  (7.5 KB at N = 2, 7.0 KB at N = 4). The default was 6, from the 2026-09-23 matrix, while
  `docs/CONFIG.md` said "about 7 KB": two numbers, one citation out of date. The template, the config
  defaults, `docs/CONFIG.md` and `docs/CONCEPTS.md` now cite the 2026-09-24 report; a test pins the
  default to what that matrix computes.
- **Only a measured contradiction marks a fix stale.** `mark-stale` closes a fix without repairing
  anything, and nothing said what does not authorize it. Now the evidence rules, `/rite:fix`,
  `/rite:fix-all` and `rite-reproducer` agree: `NOT REPRODUCED` needs `why: ok` and an output that
  contradicts the recorded Evidence; `no_section`, `no_command`, `unterminated`, a `shell_error` or a
  missing command or path is `CANNOT RUN`, never stale. The `/rite:fix-all` report lists the fixes
  without a command as a finding against the review that opened them.

## [0.7.0] — 2026-09-24

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

### Fixed

- **Multi-line evidence runs whole.** A `$ ` line ending in a backslash goes on over the next one,
  and a heredoc takes its body up to its delimiter. Run line by line, `python - <<'EOF'` got no body
  and waited on stdin until killed, and exit 2 read like a reproduced symptom. A heredoc never closed
  runs nothing (`why: unterminated`). Evidence and gates run with stdin closed.
- **A bold line is not a bullet.** Gates and the verification fallback took any line opening with a
  star as a list item, so `**But `ctest` is reachable**` under a gates title became a gate.

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
