---
description: Execute exactly one task of a Rite cycle, commit it, and record it
argument-hint: "[cycle] [task-ID]"
parts: [cli, state, reading, evidence, guards, sweep, commit, workspace, reporting]
---

# /rite:execute — one task

Arguments: `$ARGUMENTS`

One task per invocation, then stop: small runs stay reviewable and resumable. Batches are
`/rite:execute-batch`.

## Steps

1. `rite begin task [--cycle <cycle>] [--id <ID>] --json`. A token shaped like an item ID is the item,
   the other plain token is the cycle. Nothing selectable → report `reason` and `blocked_by`, stop.
   Several live cycles → ask which, never guess. A named task that is `blocked` → re-run the check
   behind the cause in its Execution Log; gone → `rite mark <ID> pending --reason "…" --commit` and
   continue, still there → report and stop.
2. `rite context <ID> --json` — the reading for this task; open another file only if it names one.
3. **Keep to the scope**, the task's Scope and Done criteria. Later work is not pulled ahead unless the
   user asked in this conversation (then add a line to the profile's "Pull-ahead precedents"); what
   you notice for another item goes in that item's Notes; a done criterion that is not verifiable is
   made verifiable in the task file first.
4. **Do the work**, then **verify every done criterion by running it**. Tick `- [x]` only after seeing
   the output; paste the command and the decisive line under Notes. With `files:` declared and
   `repo_kb` above `[limits].delegate_above_kb`, hand the implementation to one `rite:rite-worker`
   (payload of `rite context`, allowed files, gates) and verify its report: a clean context is cheaper.
5. `rite gates --id <ID> --json`. Red → fix and rerun; if you cannot, go to *Blocked*.
6. **Sweep**, then the **work commit**: code, docs, sweep edits and the task file's prose together.
7. `rite finish <ID> --json` — close, check, next.

**Blocked** (missing dependency, gate you cannot fix, guarded path, contradiction with the source of
truth): commit useful partial work, `rite mark <ID> blocked --reason "<cause, command, output>"
--commit`, report. Never close a task whose criteria are not met.

## Report

Task · each done criterion `[x]`/`[ ]` with its command and decisive output · gates · sweep · work
and bookkeeping SHAs · the `next` from `finish`; the task awaits `/rite:review`.

<!-- rite:parts -->
