# Opening issues with `gh`

How to open an issue on rite from the terminal with the [GitHub CLI](https://cli.github.com/), so it
carries the same labels and sections as one opened through the web forms in
[.github/ISSUE_TEMPLATE/](../.github/ISSUE_TEMPLATE/).

Requires `gh` authenticated (`gh auth status`). Every example runs from a clone of this repository;
elsewhere, add `-R aguilasa/rite`.

## Labels

Every issue gets **one type label** and, at triage, its **area** and **origin** labels.

| Kind | Label | When |
| --- | --- | --- |
| type | `bug` | rite does something wrong: a command, the CLI, a hook or an agent misbehaves |
| type | `design-gap` | rite works as designed, but the model has no answer for a real case |
| type | `enhancement` | something rite does not do yet and should |
| type | `documentation` | a doc is wrong, missing, stale or unclear |
| type | `question` | how rite is meant to be used, when the docs do not answer it |
| area | `area: cli` | `bin/`, `rite_lib/` |
| area | `area: commands` | `commands/`, `parts/` |
| area | `area: agents` | `agents/` |
| area | `area: hooks` | `hooks/` |
| area | `area: config` | the `rite.toml` schema, [CONFIG.md](CONFIG.md) |
| area | `area: templates` | `templates/`, `examples/` |
| origin | `found-in-use` | found running rite on another repository, not by reading its code |
| resolution | `duplicate`, `invalid`, `wontfix` | set when closing, never when opening |

From the CLI you set all of them yourself with `--label`. The web forms set only the type label;
area and origin are added at triage.

## Web form or terminal

The forms are YAML issue forms, which `gh` cannot fill in. Two ways to keep issues uniform:

- **Open the form from the terminal** — the browser does the rest:
  ```sh
  gh issue create --web       # template chooser
  xdg-open "$(gh repo view --json url -q .url)/issues/new?template=1-bug.yml"   # one form directly
  ```
  On macOS use `open`; on Windows, `start`.
- **Write the body yourself** with the form's headings (`### Field`), which is what a form produces.
  The sections of each form are listed below.

## Bug

Sections: Rite version, Area, Origin, Where it was observed, What happened, Measured, Expected, Ask.
Report what you measured, not what you suspect: the exact command and the shortest decisive output.

~~~sh
gh issue create \
  --title "reproduce runs only the first line of a backslash-continued Evidence command" \
  --label "bug,area: cli,found-in-use" \
  --body-file - <<'EOF'
### Rite version

0.16.0

### Area

cli — bin/, rite_lib/

### Origin

Found running rite on another repository

### Where it was observed

new-we2002-editor, cycle kits, CORR-KITS-089

### What happened

`rite reproduce` splits an Evidence block per line, so a command continued with a trailing `\`
runs only its first line.

### Measured

```text
$ rite reproduce CORR-KITS-089 --json
...
```

### Expected

The continued lines run as one command, as the shell would run them.

### Ask

Join lines ending in `\` before splitting the block.
EOF
~~~

## Design gap

Sections: Rite version, Area, Origin, Problem, Observed, Options. Quote the rule that cannot be
followed.

```sh
gh issue create \
  --title "No item type for amendments to read-only plan paths" \
  --label "design-gap,area: commands,area: cli,found-in-use" \
  --body-file - <<'EOF'
### Rite version

0.16.2

### Area

commands — commands/, parts/

### Origin

Found running rite on another repository

### Problem

With `docs/plans/**` in `[guards].read_only`, a plan amendment the cycle needs becomes a fix the
agent cannot resolve: only the user may commit `docs(plan): …`.

### Observed

Observed in cycle `base-scraper` (rite 0.16.2):
- FIX-BASE-011: plan §14.2 smoke wording that httpbin output cannot satisfy.

### Options

1. A `plan-amendment` item type that `close-cycle` refuses to skip.
2. ...
EOF
```

## Enhancement

Sections: Area, Origin, Motivation, Proposal, Alternatives. The motivation is a concrete case; an
idea with none uses the origin `Idea, not from a concrete case` and no `found-in-use` label.

```sh
gh issue create \
  --title "close does not compare the work commit with the item's declared files" \
  --label "enhancement,area: cli,found-in-use" \
  --body-file - <<'EOF'
### Area

cli — bin/, rite_lib/

### Origin

Found running rite on another repository

### Motivation

Two work commits touched paths outside their item's declared `files`; only the independent review
caught it.

### Proposal

`rite close` warns when the work commit changes a path outside the item's `files`.

### Alternatives

Today the reviewer compares them by hand.
EOF
```

## Documentation

Sections: Location, Kind (`Wrong`, `Missing`, `Stale` or `Unclear`), What it says now, What it should
say.

```sh
gh issue create \
  --title "CONFIG.md describes co_author_footer, which nothing reads" \
  --label "documentation,area: config" \
  --body-file - <<'EOF'
### Location

docs/CONFIG.md:131

### Kind

Wrong — contradicts what rite does

### What it says now

> Commands add the agent's co-author footer to work commits.

### What it should say

Either drop the setting, or state what reads it once something does.
EOF
```

## Question

Sections: Question, Context. Short enough for `--body`:

```sh
gh issue create \
  --title "Can one cycle span two workspaces?" \
  --label question \
  --body $'### Question\n\nCan one cycle span two workspaces?\n\n### Context\n\nRead CONCEPTS.md#workspaces.'
```

## Other useful flags

```sh
gh issue create ... --assignee @me          # assign yourself
gh issue create ... --parent 7              # open as a sub-issue of #7
gh issue create ... --blocked-by 12         # mark it blocked by #12
gh issue create ... --attach ./out.png      # upload a screenshot into the body
gh issue create --editor --label bug        # write title and body in $EDITOR
gh issue create --recover <file>            # recover the input of a failed run
```

After opening, adjust labels with `gh issue edit <N> --add-label "area: hooks"` or
`--remove-label`, and find issues with `gh issue list --label design-gap --state all`.
