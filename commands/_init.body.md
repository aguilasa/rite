---
description: Adopt Rite in this repository — detect its layout and conventions, ask what cannot be inferred, write rite.toml
argument-hint: "[--yes]"
parts: [cli, asking, commit, reporting]
---

# /rite:init

Arguments: `$ARGUMENTS`

**Never move, rename or rewrite existing files**: adopting a workflow must not cost the project its
history or its links. This command writes `rite.toml` and a short block in `CLAUDE.md`, nothing else.

## Steps

1. **Already adopted?** `rite.toml` at the root → run `rite check --all` and `rite status --all`,
   report both, stop.
2. **Detect** (read-only), noting the evidence for each conclusion:
   - **Workspace**: this folder is not inside a git repository but sub-folders are. Then `rite.toml`
     goes here, every cycle is local and every item names its `repo` (see the Workspace section of the
     work commands). Read languages, commit style and gates from each repository and say which were found.
   - **Docs and plans**; **existing backlog**: task-like files, their ID pattern, progress and fix file
     names, whether a folder is one cycle or holds cycle sub-folders, an archive folder.
   - **Link style** in those docs (root-absolute or relative).
   - **Languages** of docs, of identifiers, and of the last 50 commit subjects (`git log -50
     --format=%s`); **commit style** is conventional if most of those match `type(scope): …`.
   - **Protected paths**: vendored code, golden data, files marked generated, and their generator.
   - **Gates**: the project's own test/lint/build commands **as documented** in README, `CLAUDE.md` or
     CI config. Never invent one.
3. **Ask** only what detection left open: which layout to use, which paths are read-only, which gates
   every item must pass, docs language when mixed.
4. **Write `rite.toml`** from `${CLAUDE_PLUGIN_ROOT}/templates/rite.toml`, keeping only the keys that
   differ from the defaults plus `[project].name`, with a first comment line pointing at the plugin's
   `docs/CONFIG.md`. Map an existing backlog's names in `[paths]`, `[naming]` and `[sections]` instead
   of renaming files.
5. **Validate**: `rite status --all --json` must not fail; with mapped cycles, run `rite check --all`
   and report its findings — do not repair legacy items here. Offer `rite sync --all` when only the
   generated tables are missing.
6. **CLAUDE.md**: append (or create) at most 8 lines between `<!-- rite:begin -->` and
   `<!-- rite:end -->`: this repository uses Rite, config in `rite.toml`, item state changes only
   through the CLI, and the commands to use.
7. **Commit** exactly `rite.toml` and `CLAUDE.md` (plus synced tables, if accepted):
   `chore(rite): adopt rite`.

## Report

Detected conclusions with their evidence · questions and answers (or `assumed:`) · the keys written ·
`status` / `check` results and legacy findings left for later · commit SHA · next:
`/rite:new-cycle <name>`, or `/rite:status` when cycles already exist.

<!-- rite:parts -->
