---
description: Break a plan into Rite tasks — phases, verifiable done criteria, dependencies, closing tasks and profile checks
argument-hint: "<plan> [cycle] [--dry-run] [--yes]"
---

# /rite:plan-to-tasks

Arguments: `$ARGUMENTS`

Before step 1, read from `${CLAUDE_PLUGIN_ROOT}/shared/`: `cli.md`, `cycle-resolution.md`,
`bookkeeping.md`, `commit-policy.md`, `asking.md`, `workspace.md`.

## Steps

1. **Resolve** the plan file and the cycle (Step 0). No cycle yet → stop and suggest
   `/rite:new-cycle <name> --plan <plan>`. A cycle that already has tasks → new tasks are appended;
   never renumber or rewrite existing ones.
2. **Read the plan whole** (the one command that does), then `rite anchors <plan> --cycle <cycle> --json`.
   Every `source_of_truth` you propose must be one of the `source_of_truth` values it printed.
   Why: an anchor that does not exist makes every later review measure against nothing. If a piece
   of work has no section to anchor to, say so and propose adding the section to the plan instead.
3. **Propose the breakdown**:
   - **Phases** in the plan's order.
   - **Tasks** per phase, each one reviewable in one sitting: title (imperative), `type` from
     `[vocab].task_types`, `phase`, `source_of_truth`, `depends_on` (inside this cycle only),
     predicted `files`, in a workspace the `repo` it lands in, and **done criteria that are verifiable** — a command and its expected output,
     a number produced by a versioned tool, or a file that must exist. "Works", "is clean", "is
     documented" are not criteria.
   - **Workspace** (`resolve-cycle` says `workspace: true`): a plan spanning several repositories
     becomes tasks that each touch one of `repos`; split work that crosses two, and link the halves with
     `depends_on` when order matters.
   - **One closing task per phase** (`type: closing`), depending on every task of the phase; its
     criteria re-run the phase's gates and checks.
   - **Graph**: a mermaid `graph TD` of the dependencies.
   - **Phase-specific checks**: for each phase, 2–5 checks the reviewer will run, derived from the plan.
4. **Show** the breakdown as a table (ID-to-be, title, type, phase, repo in a workspace, anchor, depends_on) plus the graph
   and the checks. With `--dry-run`, stop here. Otherwise ask for confirmation (AskUserQuestion) and
   apply the user's corrections before writing.
5. **Write**, in dependency order:
   - each task with `rite new-task --cycle <cycle> --title ... --type ... --phase ... --depends-on ...
     --source-of-truth ... [--repo <repo>] --json`, then fill its body (Goal, Scope, Done criteria, Notes) and its
     `files:` planning field — never the state fields;
   - the graph into the progress file's "Dependency graph" section (outside the generated region);
   - the checks into the profile's "Phase-specific checks" section, one sub-heading per phase
     (`### Phase <n> — <name>`).
6. **Validate**: `rite sync --cycle <cycle>` then `rite check --cycle <cycle>` must be clean; fix what
   it reports before committing.
7. **Commit** the task files, the progress and fixes files and the profile, staged explicitly:
   `docs(rite): plan <cycle> from <plan file name>`.

## Report (fixed format)

1. **Plan** — file, sections used, sections without tasks (and why).
2. **Tasks** — table: ID, title, type, phase, depends_on.
3. **Checks** — per phase.
4. **Validation** — `rite check` result.
5. **Commit** — SHA + subject.
6. **Next** — `/rite:execute <cycle>`.
