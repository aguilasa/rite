## What to read

`rite context <ID> --json` returns in one call what this item needs: the item, the anchored section of
its `source_of_truth` with its subsections, the profile's decisions, gates and phase checks, and the
matching pitfalls entries. Read that instead of opening those files.

- **Never open a document larger than `[limits].read_kb` whole** — not the profile, the plan or a
  saved tool output. Slice it (`grep -n`, `sed -n '<from>,<to>p'`). When `context` cuts something it
  prints the command for the rest; run it only if you need it.
- What you read once in this invocation is not read again.
- Item and source of truth disagree → the source wins, and the report says so.
- Prose in `docs_language`, identifiers in `code_language`, commits in `commit_language`.
