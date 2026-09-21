---
id: SLG-TASK-02
title: "word count CLI"
type: feature
phase: 1
depends_on: [SLG-TASK-01]
source_of_truth: "/docs/plans/PLAN-slugkit.md#2.2"
files: []
resources: []
status: pending
done_on: null
done_commit: null
reviewed_on: null
review_commit: null
---

# SLG-TASK-02 — word count CLI

## Goal

Implement the function described in the source of truth.

## Scope

- In: the function, its tests, and the regenerated entry point.
- Out: anything else.

## Done criteria

- [ ] `node bin/wc.mjs fixtures/golden/words.txt` prints `42`
- [ ] `npm test` is green and includes a word-count test
- [ ] `node tools/gen-exports.mjs --check` passes

## Notes

## Execution Log
