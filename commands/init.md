---
description: Adopt Rite in this repository — detect its layout and conventions, ask what cannot be inferred, write rite.toml
argument-hint: "[--yes]"
---

# /rite:init

Arguments: `$ARGUMENTS`

Read from `${CLAUDE_PLUGIN_ROOT}/shared/`: `cli.md`, `commit-policy.md`, `asking.md`.

**Never move, rename or rewrite existing files.** Why: adopting a workflow must not cost the project
its history or its links. `init` writes `rite.toml` and a short block in `CLAUDE.md`, nothing else.

## Steps

1. **Already adopted?** If `rite.toml` exists at the repository root, run `rite check --all` and
   `rite status --all`, report both, and stop.
2. **Detect** (read-only), and note the evidence for each conclusion:
   - **Workspace**: the current folder is not inside a git repository (`git rev-parse` fails) but
     sub-folders are. Then Rite runs in workspace mode (see `${CLAUDE_PLUGIN_ROOT}/shared/workspace.md`):
     `rite.toml` goes here, every cycle is local, every item names its `repo`. Read languages, commit
     style and gates from each repository, and tell the user which ones were found.
   - **Docs and plans**: folders holding plans, specs or design documents.
   - **Existing backlog**: folders with task-like files; their ID pattern (e.g. `ABC-TASK-01`,
     `XYZ-042`), progress files and their names, fix/correction files and their ID pattern, whether
     each folder is one cycle (flat) or holds cycle sub-folders, an archive folder.
   - **Link style** used in those docs: `/root-absolute` or `relative`.
   - **Languages**: of docs (sample a few), of code identifiers, of the last 50 commit subjects
     (`git log -50 --format=%s`).
   - **Commit style**: conventional if most recent subjects match `type(scope): ...`.
   - **Protected paths**: vendored or third-party code, golden/reference data, files marked as
     generated (search for "generated", "do not edit" headers) and the generator that makes them.
   - **Gates**: the project's own test/lint/build commands as documented in its README, `CLAUDE.md`
     or CI configuration. Use only commands you found written down; never invent one.
3. **Ask** the user, in one round (AskUserQuestion, at most 4 questions), only what detection left
   open. Typical: which layout to use (keep the existing one, or the default `docs/rite/…`); which
   paths are read-only; which gates every item must pass; docs language when mixed.
4. **Write `rite.toml`** at the root. Start from `${CLAUDE_PLUGIN_ROOT}/templates/rite.toml` but keep
   only keys that differ from the defaults, plus `[project].name`; add a first comment line pointing to
   the plugin's `docs/CONFIG.md`. If an existing backlog uses other names (progress file, fix IDs,
   section headings), map them in `[paths]`, `[naming]` and `[sections]` — do not rename files.
5. **Validate**: `rite status --all --json` must not fail. If existing cycles were mapped, run
   `rite check --all` and report its findings; do not fix legacy items in this command — list them.
   Offer `rite sync --all` if only the generated tables are missing.
6. **CLAUDE.md**: append (create the file if absent) a block of at most 8 lines between
   `<!-- rite:begin -->` and `<!-- rite:end -->`: this repository uses Rite; config in `rite.toml`;
   item state changes only through the CLI; the commands to use (`/rite:status`, `/rite:execute`,
   `/rite:review`, `/rite:fix`).
7. **Commit** exactly `rite.toml` and `CLAUDE.md` (plus the synced tables, if the user accepted the
   sync): `chore(rite): adopt rite`.

## Report (fixed format)

1. **Detected** — each conclusion with its evidence (file or command).
2. **Asked** — questions and answers.
3. **rite.toml** — the keys written.
4. **Validation** — `status` / `check` results; legacy findings left for later.
5. **Commit** — SHA + subject.
6. **Next** — `/rite:new-cycle <name>` (or `/rite:status` when cycles already exist).
