---
description: Review every Rite task awaiting review in a cycle — independent reviewers in parallel waves, bookkeeping in series
argument-hint: "[cycle] [task-IDs] [--plan]"
parts: [cli, state, evidence, workspace, reporting]
---

# /rite:review-all — the whole review queue, independent

Arguments: `$ARGUMENTS`

Review only: never change code, docs or the tasks' work. Each task gets the treatment of
`/rite:review` — a fresh reviewer that **measures instead of reads** — and the run ends with every task
of the queue reviewed.

## Steps

1. `rite begin review --cycle <cycle> --no-claim --json` resolves the cycle and its config. The batch:
   the task IDs given, or the queue **now** (`rite batch-plan all --kind review --cycle <cycle>
   --json`); tasks done mid-run wait for the next run: a batch that grows never ends. Exit `1` with
   "no selectable review" → the queue is empty: report and stop.
2. **Read the plan.** Reviewers edit nothing, so files and dependencies never separate them; a wave
   holds tasks that share no serialized resource, at most `[limits].review_parallel` of them
   (`parallel_cap`). One wave of one task each means the run is sequential: say why (cap `1`, or
   the resource each pair shares). With `--plan`, show items, conflicts and waves, and stop: nothing
   is written.
3. **Each wave**: `rite begin review --cycle <cycle> --id <ID> --json` per task — it opens the
   review's clock (`review_started_at`) — then one fresh `rite:rite-reviewer` per task, **in parallel, in one message** — never this
   context. Give each the facts `/rite:review` gives: the payload of `rite context <ID> --json`, the
   repository it works in (`item.repo_dir` when given, else the root), the CLI invocation, the task's
   `done_commit`, and the instruction "Review this task per your procedure and return findings in your
   format." Do not tell any what you think of the work, nor what another reviewer found. Commit
   nothing while reviewers run: they measure HEAD.
4. **Screen the findings** of each report. Keep one only if it carries a runnable evidence command and
   its output, and at least one of its commands runs on the working tree (a pinned revision cannot
   turn green). Do not re-review, soften or add findings of your own; list what you dropped, with the
   reason.
5. **Merge duplicates across reviews** — this wave's and the earlier ones': two kept findings with the
   same evidence command and the same files are one root cause, so one fix, its origin the lowest
   task ID; every review that found it lists that fix. Findings that only look alike stay apart.
6. **Serially, in task order**, close the wave before the next starts:
   - one fix per kept finding: `rite new-fix --cycle <cycle> --origin <ID> --title "<title>" --severity
     <critical|high|medium|low> --json`, then fill the body sections (Problem, Evidence, Root cause,
     Fix, Files, Verification) — never its frontmatter or the JSON state. A merged fix lists every
     task's evidence. In Evidence the CLI is `sh "$RITE_HOME/bin/rite"`, never a resolved plugin
     path. A finding about a phase with no entry in the profile's phase checks is itself a `medium` fix;
   - `rite mark-reviewed <ID> [--fixes <FIX-ID>,…] --json` — one commit per task, also with no finding,
     because a review without a record leaves the task to be selected again. In a local cycle it writes
     the files and commits nothing.
   A run cut short keeps every closed wave; the next run takes only what is left in the queue.
7. After the last wave: `rite check --quick --cycle <cycle> --json`, then `rite status --cycle <cycle>
   --json`: no task of the batch may remain in `review_queue`. One that does is named with the reason
   (reviewer failed, `mark-reviewed` refused) — never left unsaid.

## Report

Waves with their task IDs, and why the run was parallel or sequential (cap, shared resources) · per
task: `done_commit`, the four universal verdicts in one line, phase checks, fixes opened, the commit
SHA or "local cycle" · merged fixes and the tasks behind each · dropped findings with reasons · tasks
left in the queue, if any · what to run next (usually `/rite:fix-all`).

<!-- rite:parts -->
