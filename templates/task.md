---
id: {{id}}
title: {{title}}
type: {{type}}
phase: {{phase}}
depends_on: {{depends_on}}
source_of_truth: {{source_of_truth}}
files: []            # predicted paths/globs; batches build their conflict matrix from them
resources: []        # serialized resources this item needs (rite.toml [resources] / profile)
status: pending
done_on: null
done_commit: null
reviewed_on: null
review_commit: null
---

# {{id}} — {{title_text}}

## Goal

<!-- One paragraph: what exists after this task that did not exist before. -->

## Scope

- In:
- Out:

## Done criteria

<!-- Verifiable only: a command and its expected output, a number produced by a versioned tool, a file that must exist. -->

- [ ]

## Notes

## {{execution_log}}
