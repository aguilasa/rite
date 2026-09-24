---
id: {{id}}
title: {{title}}
origin: {{origin}}
severity: {{severity}}
files: []            # predicted paths/globs; batches build their conflict matrix from them
resources: []        # serialized resources this item needs (rite.toml [resources] / profile)
status: pending
depends_on: {{depends_on}}
done_on: null
done_commit: null
---

# {{id}} — {{title_text}}

Origin: [{{origin}}]({{origin_link}})

## Problem

<!-- What is wrong, stated as an observable fact. -->

## {{evidence}}

<!-- The exact command and its output that shows the problem. Whoever fixes this reproduces it first. -->

```text
$
```

## Root cause

## Fix

<!-- Where the change goes. If the defect is in generated output, the fix goes in the generator. -->

## {{files}}

-

## {{verification}}

<!-- Command(s) that turn red before the fix and green after it. -->

## {{execution_log}}
