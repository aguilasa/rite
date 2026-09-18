# `rite.toml` reference

`rite.toml` lives at the repository root. It is the **repo config** layer: everything that belongs to
the repository (folders, naming, languages, commit policy, protected paths, generators, repo-wide gates
and resources). The plugin never assumes a path; if something is not here, it uses the default below.

Every key is optional. Unknown sections or keys are an error, so typos do not silently fall back to
defaults. A commented copy with all defaults is in [`templates/rite.toml`](../templates/rite.toml).

Where things are decided:

| Layer | Where | Changes when |
| --- | --- | --- |
| Rite | the plugin (`commands/`, `shared/`) | plugin version |
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

Task numbers are per cycle. Fix numbers are per prefix across all cycles, archived ones included.
IDs are always allocated by `rite.py new-task` / `new-fix`, which create the file atomically.

A cycle's `prefix` (and optionally `cycle`, `plan`, `profile`, `pitfalls`) comes from the
frontmatter of its `progress_file`.

## `[sections]`

Heading names the CLI reads or writes, so projects can keep their own language.

| Key | Default |
| --- | --- |
| `execution_log` | `"Execution Log"` |
| `phase_checks` | `"Phase-specific checks"` (section of the profile) |

## `[commit]`

| Key | Default | Meaning |
| --- | --- | --- |
| `style` | `"conventional"` | `conventional` (`feat: …`, bookkeeping `chore(rite): …`) or `free` (bookkeeping `rite: …`). |
| `co_author_footer` | `true` | Commands add the agent's co-author footer to work commits. |
| `bookkeeping` | `"separate-commit"` | Only mode in v1: the work commit first, then `rite.py close` records it in its own commit. |
| `push` | `"on-request"` | `never` or `on-request`. Commands never push on their own. |
| `never_stage` | `[]` | Globs never added to a commit. |

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
- fix `status`: `pending`, `in-progress`, `done`, `stale`
- fix `severity`: `critical`, `high`, `medium`, `low`
- task `reviewed_on`: `null` (not reviewable yet), `pending` (awaiting review), `YYYY-MM-DD`

## `[profile]`

| Key | Default | Meaning |
| --- | --- | --- |
| `max_kb` | `12` | Size limit of a cycle profile; `check` fails above it. `0` disables. The pitfalls file has no limit — it is searched, not read whole. |

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
```
