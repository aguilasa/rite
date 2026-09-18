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
python3 <plugin>/bin/rite.py migrate --from we2002            # dry run: report only
python3 <plugin>/bin/rite.py migrate --from we2002 --write    # convert
python3 <plugin>/bin/rite.py relink --all --write             # links to [paths].link_style
python3 <plugin>/bin/rite.py check --all
python3 <plugin>/bin/rite.py status --all                      # compare with the old tables
```

What it does:

| Legacy | Rite |
| --- | --- |
| state in the progress table (`✅ Concluído`, `⬜ Pendente`, `🔄`, `❌`) and in `status:` (`concluído`, `pendente`, …) | `status: done / pending / in-progress / blocked` in frontmatter; the table wins when they disagree (reported) |
| "Concluída em" column | `done_on` |
| "Revisado em" column (date / `⬜ pendente` / `—`) | `reviewed_on` (date / `pending` / `null`) |
| work commit: not recorded | `done_commit`: the newest non-docs commit whose message names the ID; else the last commit that touched the item file (reported as *approximated*) |
| `fonte_de_verdade: "/docs/P.md §4.2 (…)"` | `source_of_truth: "/docs/P.md#4.2"` when the heading exists; the file only otherwise (reported) |
| fix table: origin, "Criticidade" (`Alta`, `Média`, …), status (`[x] concluída`) | `origin`, `severity` (`high`, `medium`, …), `status` in the fix's frontmatter |
| `type: fechamento` | `type: closing` (batches run closing tasks alone, last) |
| progress/fix tables | generated regions (`<!-- rite:begin … -->`); the prose around them stays |
| "**Perfil deste ciclo:** [...]" | `profile:` in the progress file's frontmatter |

It also writes `rite.toml`: Portuguese file names and section headings (`Log de Execução`,
`Verificações específicas por fase`, `Fase N`), `CORR-{prefix}-{n:03}` fix IDs, the observed task types,
and `[profile].max_kb` raised to the largest existing profile so the migration starts green. Bring that
limit back down with `/rite:retro`, which moves measured pitfalls into the pitfalls file.

What it does not do:

- rename or move any file (items whose names do not match `[naming]` are listed and left alone);
- rewrite the old prompts and wrappers — delete them once the plugin is in use;
- decide anything about approximated commits — review them in the diff.

## After migrating

1. Replace `.claude/commands/*` wrappers with the plugin: `/plugin install rite@rite`.
2. Remove the rules that `rite.py check` now enforces mechanically, or point them at `rite.toml`.
3. Move repo-specific facts that lived in the old "agnostic" prompts (paths, displays, tools) into
   `rite.toml` (`[guards]`, `[gates]`, `[resources]`) and `CLAUDE.md`.
4. Run `/rite:status` and compare with the last version of the old tables.
