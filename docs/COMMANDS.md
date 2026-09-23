# Commands

Every command re-reads its own file on each invocation, takes the cycle as an optional first argument,
respects `rite.toml`, and ends with a fixed, numbered report. Commands that ask questions accept
`--yes` to take the recommended answers (listed as `assumed` in the report).

## Work

| Command | Does | Commits |
| --- | --- | --- |
| `/rite:execute [cycle] [task]` | One task: resolve, read layers, do the work, verify each done criterion, gates, sweep. | work + `chore(rite): close` |
| `/rite:execute-batch [cycle] [N\|IDs] [--plan]` | N tasks (default 2, max 8) in waves built by `rite batch-plan`; `rite-worker` agents edit in parallel, the main thread commits serially. | per item: work + close |
| `/rite:review [cycle] [task]` | Delegates to the `rite-reviewer` agent in a clean context; four universal questions + the profile's phase checks; opens fixes. | `chore(rite): review <ID> (…)` — also with no finding |
| `/rite:fix [cycle] [fix]` | Reproduce evidence → root cause → repair (in the generator if output is generated) → verify → sweep. Stale if the symptom is gone. | work + sweep + close, or `stale` |
| `/rite:fix-all [cycle] [IDs] [--plan]` | All fixes open now: parallel `rite-reproducer` triage, then waves of `rite-worker`. | per item |

## Lifecycle

| Command | Does |
| --- | --- |
| `/rite:init [--yes]` | Detects layout, ID conventions, languages, commit style, protected paths and documented gates; asks the rest; writes `rite.toml` and a short `CLAUDE.md` block. Never moves files. |
| `/rite:new-cycle <name> [--prefix X] [--plan P] [--ticket KEY] [--local]` | `rite new-cycle`: folder, views, profile skeleton, pitfalls file; seeds the profile only with facts. Asks for the tracker ticket and whether the cycle is local ([CONCEPTS.md](CONCEPTS.md#local-cycles)). |
| `/rite:plan-to-tasks <plan> [cycle] [--dry-run]` | Proposes phases, tasks with anchored `source_of_truth` (from `rite anchors`), verifiable criteria, `depends_on`, a closing task per phase, a graph and phase checks; writes after confirmation; `rite check` must pass. |
| `/rite:status [cycle]` | Read-only summary and the suggested next command. |
| `/rite:close-cycle <cycle>` | `rite archive --dry-run` blockers, else archive with link rewriting. |
| `/rite:retro <cycle>` | `rite stats` numbers, fixes grouped by root cause; proposes keep / promote / report / prune; applies what the user approves. |

## Agents

| Agent | Tools | Used by |
| --- | --- | --- |
| `rite-reviewer` | Read, Grep, Glob, Bash — never edits | `/rite:review` |
| `rite-worker` | edits; no git state, no bookkeeping | `/rite:execute-batch`, `/rite:fix-all` |
| `rite-reproducer` | Read, Grep, Glob, Bash — never edits | `/rite:fix-all` triage |

## CLI

`sh "${CLAUDE_PLUGIN_ROOT}/bin/rite" <subcommand> [--cycle C] [--root R] [--json]`

| Subcommand | Does |
| --- | --- |
| `begin task\|fix\|review [--id ID]` | resolve the cycle, take the item, return paths, config digest and commit template |
| `context ID` | the item, its anchored source-of-truth section, the profile rules that apply and matching pitfalls, capped |
| `gates [--id ID]` | run the global and profile gates; tail of a passing one, whole output of a red one |
| `sweep --terms a,b [--id ID]` | mentions of what an item changed, across cycle, plans and top-level docs |
| `finish ID [--sha S \| --no-repo --reason R]` | close the item, `check --quick`, and name the next one |
| `resolve-cycle [name]` | cycle chosen by the rules, with prefix, profile, pitfalls, plan, ticket, local, workspace and its repos |
| `next task\|review\|fix` | deterministic selection |
| `new-task`, `new-fix` `[--repo R]`, `commit-new ID` | atomic ID allocation (`--repo`: the item's repository in a workspace); commit a new filled-in item |
| `commit-refs ID` | subject template and trailers for an item's work commit |
| `close ID [--sha S \| --no-repo --reason R]` | record a finished item from its work commit; `--no-repo` when it has none (`done_commit: none`) |
| `rebind ID --sha S` | repoint `done_commit` after a squash or rebase rewrote the work commit |
| `mark ID STATUS`, `mark-reviewed ID [--fixes …]`, `mark-stale FIX --reason …` | other transitions |
| `sync`, `check [--quick]`, `status` | views, validation, summary; `sync`/`check`/`relink` take `--include-archived` |
| `batch-plan N\|IDs\|all [--kind task\|fix]` | inventory, conflict matrix, waves |
| `new-cycle NAME --prefix X [--ticket K] [--local]`, `archive NAME [--dry-run]`, `publish NAME` | lifecycle; `publish` makes a local cycle tracked |
| `anchors FILE`, `stats NAME` | plan anchors for `source_of_truth`; retro numbers |
| `relink [--write]`, `migrate --from we2002 [--write]` | normalize link style; convert a legacy backlog (see [MIGRATING.md](MIGRATING.md)) |
| `guard PATH` | read-only / generated verdict (the hook uses it) |

Exit codes: `0` ok · `1` failure or nothing selected · `3` no `rite.toml`.
