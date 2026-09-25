# `rite.toml` reference

`rite.toml` lives at the repository root. It is the **repo config** layer: everything that belongs to
the repository (folders, naming, languages, commit policy, protected paths, generators, repo-wide gates
and resources). The plugin never assumes a path; if something is not here, it uses the default below.

Every key is optional. Unknown sections or keys are an error, so typos do not silently fall back to
defaults. A commented copy with all defaults is in [`templates/rite.toml`](../templates/rite.toml).

Where things are decided:

| Layer | Where | Changes when |
| --- | --- | --- |
| Rite | the plugin (`commands/`, built from `parts/`) | plugin version |
| Repo config | `rite.toml` | rarely |
| Cycle profile | `<profiles_dir>/<profile_file>` (+ pitfalls file) | every cycle |
| Item | task / fix file frontmatter | every item |

## `[project]`

| Key | Default | Meaning |
| --- | --- | --- |
| `name` | `""` | Display name. |
| `docs_language` | `"en-US"` | Language for tasks, fixes, profiles and generated prose. |
| `code_language` | `"en-US"` | Language for identifiers and code comments. |
| `commit_language` | `"en-US"` | Language for commit messages. |

## `[paths]`

All paths are relative to the repository root.

| Key | Default | Meaning |
| --- | --- | --- |
| `cycles_root` | `"docs/rite/cycles"` | Where cycles live. A **cycle** is any folder holding `progress_file`. If `cycles_root` itself holds one, the repository uses the flat layout (one cycle, no sub-folders). |
| `archive_dir` | `"docs/rite/cycles/archive"` | Closed cycles. Never scanned for live work; still scanned for ID uniqueness. |
| `profiles_dir` | `"docs/rite/profiles"` | Cycle profiles and pitfalls files. |
| `plans_dir` | `"docs/plans"` | Plans (sources of truth). |
| `templates_dir` | `""` | Optional folder with local overrides of the plugin templates (`task.md`, `fix.md`, …). |
| `link_style` | `"root-absolute"` | `root-absolute` (`/docs/x.md`) or `relative` (`../x.md`). `check` enforces it on every link and `source_of_truth`. |
| `default_cycle` | `""` | Cycle used when a command gets none. Empty = flat layout if present, else the only live cycle, else ask. |

## `[naming]`

Templates use Python format syntax. Fields: `{prefix}`, `{n}` (number, e.g. `{n:02}`), `{slug}`,
`{id}` (file templates only), `{cycle}` (profile templates only).

| Key | Default |
| --- | --- |
| `task_id` | `"{prefix}-TASK-{n:02}"` |
| `fix_id` | `"FIX-{prefix}-{n:03}"` |
| `task_file` | `"{n:02}-{slug}.md"` (relative to the cycle folder; may contain `/`) |
| `fix_file` | `"{id}.md"` |
| `progress_file` | `"progress.md"` |
| `fixes_file` | `"fixes.md"` |
| `profile_file` | `"{cycle}.md"` |
| `pitfalls_file` | `"{cycle}.pitfalls.md"` |

`task_id`, `fix_id`, `task_file` and `fix_file` also take a **list**. The first template is
canonical — new items are always named with it; the others are only accepted when reading, so items an
earlier convention named differently stay part of their cycle instead of being ignored. For example, a
closed cycle whose later tasks were saved as `PAR-TASK-01.md` next to `01-extract.md`:

```toml
[naming]
task_file = ["{n:02}-{slug}.md", "{id}.md"]
```

With single templates, an ID whose prefix differs from its cycle's prefix is an error (a typo). As soon
as any of those four keys is a list, it is a warning: a cycle may legitimately hold items with an older
prefix.

Task numbers are per cycle. Fix numbers are per prefix across all cycles, archived ones included.
IDs are always allocated by `rite.py new-task` / `new-fix`, which create the file atomically.

A cycle's `prefix` (and optionally `cycle`, `plan`, `profile`, `pitfalls`, `order`) comes from the
frontmatter of its `progress_file`.

**Execution order.** Tasks run in ID order unless the progress file lists `order:` — task IDs that
come first, in that order; unlisted tasks follow by number. It is how a task split late (new, higher
ID) runs before tasks numbered below it without renumbering them and breaking their links. Selection
(`next`, `batch-plan`) and the generated table both follow it; `check` rejects unknown or repeated IDs.

```yaml
order: [LOOKS-TASK-31, LOOKS-TASK-36, LOOKS-TASK-37, LOOKS-TASK-32]
```

## `[sections]`

Heading names the CLI reads or writes, so projects can keep their own language. A section is found by
its title (case-insensitive) — exactly, or followed by a separator (` — `, ` - `, `:`, ` (`, ` *`):
`Evidence — how it was seen` is the evidence, `Evidence of a harness artefact` is not. A title the
repository does not use is a section that is not there. That is why every key is configurable: one English `Evidence` once turned off the inline triage
of a whole pt-BR repository — every fix came back "no command", and nothing said why.

Each value is a **title or a list of titles**. The first is the one Rite writes (new items, a created
Execution Log); every entry is read, in order. A list is how a repository keeps items an older
convention titled differently:

```toml
evidence      = ["Evidência", "Evidence"]
execution_log = ["Log de Execução", "Log de Execução *(preenchido após execução)*"]
```

| Key | Default | Where, and who reads it |
| --- | --- | --- |
| `execution_log` | `"Execution Log"` | item; every transition appends its log line here |
| `phase_checks` | `"Phase-specific checks"` | profile; `check` and `context` |
| `phase_label` | `"Phase"` | the word looked for inside `phase_checks` (`Phase 3`, `Fase 3`, …) |
| `evidence` | `"Evidence"` | fix; `reproduce` runs the `$ ` lines of its fenced blocks |
| `verification` | `"Verification"` | fix; `reproduce`'s fallback: its `$ ` lines, else its bullets' code spans |
| `files` | `"Files"` | item; `batch-plan` predicts the paths it lists (code spans, or bullets opening with a path that exists) |
| `scope` | `"Scope"` | item; a second place `batch-plan` looks for paths |
| `gates` | `"Gates"` | profile; `gates` runs its bullets' code spans — never a table's, which was measured to be a catalogue of tools |
| `serialized_resources` | `"Serialized resources"` | profile; `batch-plan` serializes the names it lists |
| `confirmed_decisions` | `"Confirmed decisions"` | profile; part of `context` |
| `generated_artifacts` | `"Generated artifacts"` | profile; part of `context` |

`rite.py sections` proposes this block from the titles the items and profiles already use, and
`--write` merges what it matched (see [COMMANDS.md](COMMANDS.md)). `check` warns about an open fix with
no evidence or verification title, and about a live profile with no gates title.

## `[commit]`

| Key | Default | Meaning |
| --- | --- | --- |
| `style` | `"conventional"` | `conventional` (`feat: …`, bookkeeping `chore(rite): …`) or `free` (bookkeeping `rite: …`). |
| `co_author_footer` | `true` | Commands add the agent's co-author footer to work commits. |
| `bookkeeping` | `"separate-commit"` | Only mode in v1: the work commit first, then `rite.py close` records it in its own commit. |
| `push` | `"on-request"` | `never` or `on-request`. Commands never push on their own. |
| `never_stage` | `[]` | Globs never added to a commit. |
| `ticket_format` | `"Refs: {ticket}"` | Where a cycle's `ticket` goes in its commits. With `{subject}` it is the subject (`"{ticket} {subject}"` gives `PROJ-1 feat: …`, as many JIRA commit-msg hooks want); without, it is a trailer line. Must contain `{ticket}`. Applies to work commits (through `rite commit-refs`) and bookkeeping commits alike. |

The ticket itself is per cycle, not per repository: `ticket: PROJ-123` in the progress file's
frontmatter (`rite new-cycle --ticket`). A cycle without one gets no ticket reference.

## `[guards]`

Enforced by the plugin's `PreToolUse` hook on `Edit`, `Write` and `NotebookEdit`.

| Key | Default | Meaning |
| --- | --- | --- |
| `read_only` | `[]` | Globs that must never be written (`**` any depth, `*` one segment). |
| `read_only_reason` | `""` | Shown when a write is blocked. |
| `[[guards.generated]]` | — | Tables with `paths` (globs), `generator` (what to edit instead) and optional `check` (command proving output matches the generator). |

```toml
[guards]
read_only = ["vendor/**", "fixtures/golden/**"]
read_only_reason = "third-party code and golden files are never edited"

[[guards.generated]]
paths = ["src/gen/**"]
generator = "tools/gen.py"
check = "python tools/gen.py --check"
```

## `[gates]`

| Key | Default | Meaning |
| --- | --- | --- |
| `global` | `[]` | Commands every item must pass before it closes. Cycle-specific gates go in the profile. |
| `shell` | `"bash"` | The shell that runs gates and fix evidence (`rite gates`, `rite reproduce`): `bash` — Git Bash on Windows, as Claude Code runs commands, so a gate means there what it meant when it was written — or `system` (cmd.exe on Windows, `sh` elsewhere) for gates written for cmd.exe. Without a bash, `bash` falls back to the system shell; the JSON output names the shell used. |

## `[resources]`

| Key | Default | Meaning |
| --- | --- | --- |
| `serialized` | `[]` | Resources two workers cannot use at once: `{ name = "...", why = "..." }`. Batches put items sharing one in different waves. |

## `[vocab]`

| Key | Default | Meaning |
| --- | --- | --- |
| `task_types` | `["feature", "tool", "research", "verification", "closing"]` | Allowed task `type` values. Empty list = any. `closing` marks a phase's closing task. |

Statuses and severities are fixed, not configurable:

- task `status`: `pending`, `in-progress`, `done`, `blocked`, `skipped`
- fix `status`: `pending`, `in-progress`, `done`, `blocked` (with `unblocked_by`, the command that
  unblocks it), `stale`
- fix `severity`: `critical`, `high`, `medium`, `low`
- task `reviewed_on`: `null` (not reviewable yet), `pending` (awaiting review), `YYYY-MM-DD`

## `[profile]`

| Key | Default | Meaning |
| --- | --- | --- |
| `max_kb` | `12` | Size limit of a cycle profile; `check` fails above it. `0` disables. The pitfalls file has no limit — it is searched, not read whole. |

## `[output]`

| Key | Default | Meaning |
| --- | --- | --- |
| `context_kb` | `24` | Cap of what `rite.py context` prints. What does not fit is named, with the `sed -n` command that reads it. |

## `[limits]`

| Key | Default | Meaning |
| --- | --- | --- |
| `read_kb` | `8` | Above this a command slices a file (`rite.py context`, `grep -n`, `sed -n`) instead of opening it whole. |
| `delegate_above_kb` | `5000` | Repository size (git's own object count) above which `/rite:execute` hands the implementation to a worker agent. |
| `sweep_hits` | `40` | Cap of hits `rite.py sweep` prints per term. |
| `inline_triage_max_output_kb` | `7` | A fix whose reproduction prints more than this is triaged by an agent, not in the main thread. `7` is the break-even measured on a small example ([tokens report](tokens/2026-09-24-fixall-as-is-vs-inline.md)); the line is the repository's, not the plugin's — a large one usually sits an order of magnitude higher (72 KB [measured](tokens/2026-09-25-inline-triage-limit.md) on one). Measure yours: `rite tokens --project "*<repo>*" --suggest-limits`. |

## `[status]`

| Key | Default | Meaning |
| --- | --- | --- |
| `review_age_days` | `7` | A task done longer ago than this and still unreviewed is reported as aged. |

## `[hooks]`

| Key | Default | Meaning |
| --- | --- | --- |
| `stop_check` | `false` | At the end of each turn, run `rite.py check --quick` and warn if views are out of sync. |

## Example: legacy layout

A repository with Portuguese file names, flat `docs/tasks/<cycle>/` folders and `CORR-*` fixes:

```toml
[project]
docs_language = "pt-BR"

[paths]
cycles_root  = "docs/tasks"
archive_dir  = "docs/tasks/concluidos"
profiles_dir = "docs/prompts"
link_style   = "relative"

[naming]
fix_id        = "CORR-{prefix}-{n:03}"
progress_file = "progresso.md"
fixes_file    = "correcoes-progresso.md"
profile_file  = "perfil-{cycle}.md"

[sections]
execution_log = "Log de Execução"
phase_checks  = "Verificações por fase"
phase_label   = "Fase"
evidence      = "Evidência"
verification  = "Verificação"
files         = ["Arquivos a criar ou modificar", "Arquivos"]
gates         = "Gates deste ciclo"
```
