---
description: Break a plan into Rite tasks — phases, verifiable done criteria, dependencies, closing tasks and profile checks
argument-hint: "<plan> [cycle] [--dry-run] [--yes]"
parts: [cli, state, asking, workspace, reporting]
---

# /rite:plan-to-tasks

Arguments: `$ARGUMENTS`

## Steps

1. **Resolve** the plan file and the cycle (`rite resolve-cycle [cycle] --json`). No cycle yet → stop
   and suggest `/rite:new-cycle <name> --plan <plan>`. A cycle with tasks → new ones are appended;
   never renumber or rewrite existing ones.
2. **Read the plan whole** — the one command that does — then `rite anchors <plan> --cycle <cycle>
   --json`. Every `source_of_truth` you propose must be one of the values it printed: an anchor that
   does not exist makes every later review measure against nothing. Work with no section to anchor to
   → say so and propose adding the section to the plan instead.
3. **Propose the breakdown**:
   - **Phases** in the plan's order.
   - **Tasks** per phase, each reviewable in one sitting: imperative title, `type` from
     `[vocab].task_types`, `phase`, `source_of_truth`, `depends_on` (inside this cycle), predicted
     `files`, the `repo` in a workspace, and **done criteria that are verifiable** — a command and its
     expected output, a number from a versioned tool, or a file that must exist. "Works", "is clean"
     and "is documented" are not criteria.
   - In a workspace, each task touches one repository; work crossing two becomes two tasks, linked by
     `depends_on` when order matters.
   - **One closing task per phase** (`type: closing`) depending on every task of that phase, whose
     criteria re-run the phase's gates and checks.
   - **Graph**: a mermaid `graph TD` of the dependencies.
   - **Phase checks**: 2–5 checks per phase, derived from the plan, that the reviewer will run.
4. **Show** the breakdown as a table (ID-to-be, title, type, phase, repo, anchor, depends_on) with the
   graph and the checks. `--dry-run` → stop here. Otherwise confirm and apply the corrections first.
5. **Write**, in dependency order: each task with `rite new-task --cycle <cycle> --title … --type …
   --phase … --depends-on … --source-of-truth … [--repo <repo>] --json`, then its body (Goal, Scope,
   Done criteria, Notes) and its `files:` planning field — never the state fields; the graph into the
   progress file's "Dependency graph" section; the checks into the profile's phase-checks section, one
   sub-heading per phase.
6. **Validate**: `rite sync --cycle <cycle>`, then `rite check --cycle <cycle>` must be clean.
7. **Commit** the task files, the views and the profile, staged explicitly:
   `docs(rite): plan <cycle> from <plan file name>`.

## Report

Plan file, sections used, sections without tasks and why · the task table · checks per phase ·
`rite check` result · commit SHA · next: `/rite:execute <cycle>`.

<!-- rite:parts -->
