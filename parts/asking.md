## Asking the user

Ask only what the repository cannot answer, in one round, with AskUserQuestion (at most 4 questions,
recommended option first). Every question is a context switch; guesses the commands then obey are worse.

With `--yes` in the arguments (or when questions cannot be asked): do not ask. Take the recommended
option of each and list them in the report as `assumed: <question> → <choice>`. Even then, never choose
an option that deletes, moves or overwrites existing files, and never apply retro proposals — write
them down only.
