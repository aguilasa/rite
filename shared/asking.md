# Asking the user

Ask only what the repository cannot answer, in one round, with AskUserQuestion (at most 4 questions,
the recommended option first). Why: every question is a context switch for the user; guesses the
commands then obey are worse.

**`--yes` in the arguments** (or a session where questions cannot be asked): do not ask. Take the
recommended option of each question, and list every such choice in the report under "Asked" as
`assumed: <question> → <choice>`, so the user can reverse it. Two limits hold even with `--yes`:

- never choose an option that deletes, moves or overwrites existing files;
- never apply retro proposals or open issues — write them down only.
