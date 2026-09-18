# What to read, in this order

Read only what the current item needs. Why: context spent on unrelated rules is context taken from
the code under change.

1. **Repo config** — `rite.toml` (paths, naming, languages, commit policy, guards, gates, resources).
   `CLAUDE.md` is already in context.
2. **Cycle profile** — the `profile` file from Step 0, whole. It is size-limited on purpose. If it is
   missing, say so in the report and continue with the repo config only.
3. **Pitfalls** — never read whole. Search it for the item's paths, type, phase and key terms
   (`grep -n -i`) and read only the matching entries. Each hit is a rule proven by a past failure; obey it.
4. **The item** — its file, whole. Other items are opened only when a `depends_on` needs checking.
5. **Source of truth** — open `source_of_truth` and read the anchored section and its sub-sections,
   not the whole document. The item is measured against it; when item and source disagree, the source
   wins and the disagreement goes in the report.

Language: prose in `[project].docs_language`, code in `code_language`, commits in `commit_language`.
Keep the headings the templates and `[sections]` define.
