---
id: TXT-TASK-01
title: "slugify"
type: feature
phase: 1
depends_on: []
source_of_truth: "/docs/plans/PLAN-textkit.md#2.1"
status: pending
done_on: null
done_commit: null
reviewed_on: null
review_commit: null
---

# TXT-TASK-01 — slugify

## Goal

Implement the function described in the source of truth.

## Scope

- In: the function, its unit tests.
- Out: anything else.

## Done criteria

- [ ] `python -c "from textkit import slugify; print(slugify('Hello, World!'))"` prints `hello-world`
- [ ] `python -m unittest discover -s tests` is green and includes a slugify test

## Notes

## Execution Log
