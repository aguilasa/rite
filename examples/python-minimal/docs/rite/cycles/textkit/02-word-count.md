---
id: TXT-TASK-02
title: "word count CLI"
type: feature
phase: 1
depends_on: [TXT-TASK-01]
source_of_truth: "/docs/plans/PLAN-textkit.md#2.2"
status: pending
done_on: null
done_commit: null
reviewed_on: null
review_commit: null
---

# TXT-TASK-02 — word count CLI

## Goal

Implement the function described in the source of truth.

## Scope

- In: the function, its unit tests.
- Out: anything else.

## Done criteria

- [ ] `python -m textkit.count data/golden/words.txt` prints `42`
- [ ] `python -m unittest discover -s tests` is green and includes a word-count test

## Notes

## Execution Log
