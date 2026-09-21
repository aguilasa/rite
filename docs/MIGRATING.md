# Migrating an existing backlog

Two ways in:

- **Map, do not convert** — `/rite:init` detects your folders and names and writes a `rite.toml` that
  describes them (`[paths]`, `[naming]`, `[sections]`). Nothing is renamed. Works when your items already
  keep state in frontmatter with Rite's vocabulary.
- **Convert in place** — `rite.py migrate --from <format>` rewrites a known legacy format so frontmatter
  becomes the single source of state. Today: `we2002`.

Always convert **on a branch**, and review the diff before merging.

## `migrate --from we2002`

For the system Rite was extracted from: `docs/tasks/` as the root cycle, sub-folder cycles, an archive
folder `docs/tasks/concluidos/`, `progresso.md` / `correcoes-progresso.md` tables with emoji statuses,
`CORR-<PFX>-NNN` fixes and `fonte_de_verdade` with `§` section references.

```sh
git switch -c adopt-rite
python3 <plugin>/bin/rite.py migrate --from we2002                          # dry run: report only
python3 <plugin>/bin/rite.py migrate --from we2002 --write                  # convert
python3 <plugin>/bin/rite.py relink --all --include-archived --write        # links to [paths].link_style
python3 <plugin>/bin/rite.py check --all --include-archived
python3 <plugin>/bin/rite.py status --all                                    # compare with the old tables
```

What it does:

| Legacy | Rite |
| --- | --- |
| state in the progress tables (`✅ Concluído`, `⬜ Pendente`, `🔄`, `❌`) and in `status:` (`concluído`, `pendente`, …) | `status: done / pending / in-progress / blocked` in frontmatter; the table wins when they disagree (reported) |
| "Concluída em" column | `done_on` |
| "Revisado em" column (date / `⬜ pendente` / `—`) | `reviewed_on` (date / `pending` / `null`) |
| "Fase" column, when the frontmatter has no `phase` | `phase`; with neither, `phase: null` and an action for the operator |
| work commit: not recorded | `done_commit`: the newest non-docs commit whose message names the ID; else the last commit that touched the item file — *approximated*, reported and recorded in the item (below) |
| `fonte_de_verdade: "/docs/P.md §4.2 (…)"` | `source_of_truth: "/docs/P.md#4.2"` when the heading exists; otherwise the file only, plus an action for the operator |
| fix table: origin, "Criticidade" (`Alta`, `Média`, …), status (`[x] concluída`, `[x] envelhecida`) | `origin`, `severity` (`high`, `medium`, …), `status` (`done`, `stale`) in the fix's frontmatter |
| `type: fechamento` | `type: closing` (batches run closing tasks alone, last) |
| every state table of a progress/fix file (an appendix can hold a second one) | the first becomes the generated region (`<!-- rite:begin … -->`); later ones become a one-line pointer to it; the prose around them stays |
| items named by ID (`PAR-TASK-01.md`) next to `NN-slug.md` ones | read through a second `[naming].task_file` template; new items still use the first |
| "**Perfil deste ciclo:** [...]" | `profile:` in the progress file's frontmatter |
| row order of the state tables, when it is not the ID order (a task split late runs before lower numbers) | `order:` in the progress file's frontmatter |

An approximated `done_commit` is recorded where it will be read — at the end of the item's Execution Log:

```text
_Migrated on 2026-09-21: done_commit approximated from the last commit touching this file._
```

`check` does not fail those items: the commit exists; the line records its provenance.

It also writes `rite.toml`: Portuguese file names and section headings (`Log de Execução`,
`Verificações específicas por fase`, `Fase N`), `CORR-{prefix}-{n:03}` fix IDs, both task file shapes,
the observed task types, and `[profile].max_kb` raised to the largest existing profile so the migration
starts green. Bring that limit back down with `/rite:retro`, which moves measured pitfalls into the
pitfalls file.

What it does not do:

- rename or move any file;
- invent an anchor or a phase — it keeps what it can prove and lists, per item, what the operator has
  to decide (`action required` in its report);
- rewrite the old prompts and wrappers — delete them once the plugin is in use;
- convert the per-phase checklists in the old progress files — they are prose now and will drift; delete
  or keep them as history.

## Measured on the source repository

2026-09-21, on a throw-away clone (`git clone -s -n`, branch `adopt-rite`) of the repository Rite was
extracted from, at `62a9269`. Nothing from the clone went back to the source.

`migrate --write` then `relink --all --include-archived --write`: 407 items in 4 cycles, 419 files
changed, 427 links rewritten to root-absolute in 137 files.

**Old tables against `rite status` / `rite stats`**, per cycle. "Old" is counted twice — by the same
table parser the migration uses, and independently by `grep` on the table rows of
`git show main:<file>` — and both agree:

| Cycle | Tasks old → new | Done | Open (pending / in-progress / blocked) | Fixes old → new | Fixes closed (done + stale) | Fixes open | Δ |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `pes2` (`docs/tasks`) | 35 → 35 | 8 → 8 | 26 / 1 / 0 → 26 / 1 / 0 | 32 → 32 | 32 → 32 | 0 → 0 | none |
| `looks` (`docs/tasks/looks`) | 35 → 35 | 30 → 30 | 5 / 0 / 0 → 5 / 0 / 0 | 65 → 65 | 65 → 65 | 0 → 0 | none |
| `port-mcr` (`docs/tasks/port-mcr`) | 17 → 17 | 17 → 17 | 0 → 0 | 30 → 30 | 30 → 30 | 0 → 0 | none |
| `wte`, archived (`docs/tasks/concluidos`) | 51 → 51 | 48 → 48 | 0 / 0 / 3 → 0 / 0 / 3 | 142 → 142 | 141 + 1 stale → 141 + 1 stale | 0 → 0 | none |

`check --all` (live cycles): **0 errors, 0 warnings**. With `--include-archived`: 0 errors and
11 warnings — `PAR-TASK-01` … `11` keep their `PAR` prefix inside the `WTE` cycle, as intended by the
second `task_file` template. (A first measurement reported 3 errors for phases 1, 5 and 7 of
`perfil-wte.md`; the profile covers them with ranges — "Fase 0-1", "Fase 4-5", "Fase 6-7" — which
`check` did not read until then.)

What the migration left for the operator (`action required`, 15):

- 4 section references with no heading: `WTE-TASK-28`, `29`, `32`, `33` point at §5.1–§5.4 of
  `PLAN-WTE-LAZARUS.md`, which has no such headings. Add the headings, or repoint each task
  (`rite anchors /docs/PLAN-WTE-LAZARUS.md`).
- 11 tasks with no phase: `PAR-TASK-01` … `11`. Their table has a `§` column, not a phase, and the
  progress file says why: they belong to another project and "do not enter phases 0 to 7". `phase: null`
  is the right answer there, not a gap.
- 21 approximated `done_commit` values (`CORR-LOOKS-*` and `CORR-WTE-*` whose messages never named
  the ID), each with the provenance line above.

Found and fixed while measuring (each now has a test in `tests/test_migrate.py`):

- the tables' row order was the execution order (`looks` runs 36–40 before 32) and was lost;
- a second state table in an appendix was ignored, so its eleven `PAR-TASK-*` rows had no dates;
- phase ranges in a profile ("Fase 4-5") were not read as covering each phase;
- a `|` inside a code span in a title (`` `cor|grade` ``) shifted the columns of that row, losing the
  severity and date of `CORR-WTE-079`;
- single-number section references (`§1`) never became anchors;
- an archived cycle whose name comes from its progress file (`concluidos/` is cycle `wte`) could not be
  resolved by name.

## After migrating

1. Replace `.claude/commands/*` wrappers with the plugin: `/plugin install rite@rite`.
2. Remove the rules that `rite.py check` now enforces mechanically, or point them at `rite.toml`.
3. Move repo-specific facts that lived in the old "agnostic" prompts (paths, displays, tools) into
   `rite.toml` (`[guards]`, `[gates]`, `[resources]`) and `CLAUDE.md`.
4. Resolve the `action required` list, then run `/rite:status` and compare with the last version of the
   old tables.
