---
id: SLG-TASK-01
title: "slugify"
type: feature
phase: 1
depends_on: []
source_of_truth: "/docs/plans/PLAN-slugkit.md#2.1"
files: []
resources: []
status: pending
done_on: null
done_commit: null
reviewed_on: null
review_commit: null
---

# SLG-TASK-01 — slugify

## Goal

Implement the function described in the source of truth.

## Scope

- In: the function, its tests, and the regenerated entry point.
- Out: anything else.

## Done criteria

- [ ] `node -e "import('./src/index.mjs').then(m => console.log(m.slugify('Hello, World!')))"` prints `hello-world`
- [ ] `npm test` is green and includes a slugify test
- [ ] `node tools/gen-exports.mjs --check` passes

## Notes

## Execution Log
