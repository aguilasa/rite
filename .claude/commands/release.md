---
description: Release rite — run the Release workflow on main, wait for it and report the published release
argument-hint: "[patch | minor | major | X.Y.Z]"
allowed-tools: Bash(git status:*), Bash(git fetch:*), Bash(git rev-list:*), Bash(git log:*), Bash(git pull:*), Bash(python3 tools/release.py current:*), Bash(python3 tools/release.py notes:*), Bash(gh workflow run release.yml:*), Bash(gh run list:*), Bash(gh run watch:*), Bash(gh run view:*), Bash(gh release view:*), Read, AskUserQuestion
---

# /release — publish a rite release through the Release workflow

Arguments: `$ARGUMENTS`

The release itself runs in `.github/workflows/release.yml` (see "Releasing" in `README.md`): tests,
version bump in every file, `[Unreleased]` dated in `CHANGELOG.md`, commit `chore(release): X.Y.Z`,
tag `vX.Y.Z`, GitHub release. This command only checks that a release makes sense, triggers the
workflow and follows it. Never bump, edit, commit, tag or create the release locally.

## Steps

1. **What would be released.** Run `git fetch origin main --tags` and
   `python3 tools/release.py current`, then `python3 tools/release.py notes Unreleased`. If the
   notes fail (no `[Unreleased]` section, or it is empty), say there is nothing to release and stop.
2. **Is it on origin.** The workflow releases `origin/main`, not the working tree.
   - `git rev-list --count origin/main..main` above 0: list those commits (`git log --oneline
     origin/main..main`) and stop. They must be pushed first, or they stay out of the release.
   - `git status --short` not empty: warn that uncommitted changes will not be in the release, and
     go on.
3. **The bump.** If `$ARGUMENTS` is `patch`, `minor`, `major` or `X.Y.Z`, use it. If it is empty,
   infer it from the `[Unreleased]` notes: a `### Added` or `### Changed` heading means `minor`; only
   `### Fixed` means `patch`; anything that says it breaks existing behaviour or configuration means
   ask. Then ask the user with `AskUserQuestion`, the inferred bump first and marked recommended,
   showing current → new version and the notes' headings with their entry titles. Anything else in
   `$ARGUMENTS`: say what is accepted and stop.
4. **Trigger.** `gh workflow run release.yml --ref main -f bump=<bump>`. Then find the run it created:
   `gh run list --workflow release.yml --event workflow_dispatch --limit 1 --json
   databaseId,url,status,createdAt` (retry after a few seconds if the newest run predates the
   trigger). Give the user the run URL.
5. **Follow.** `gh run watch <id> --exit-status` (with a timeout of at least 10 minutes).
   - On failure: `gh run view <id> --log-failed`, quote the shortest decisive lines and say which
     step failed. If it failed before "Bump, commit, tag and push", nothing was changed on GitHub.
     If it failed after, check with `gh release view v<version>` and `git log origin/main -1` what was
     already done, and say what is missing.
6. **Report.** `git pull --ff-only origin main` to bring the release commit in, then
   `gh release view v<version> --json url,name,publishedAt`. Reply with the version, the release URL
   and one line per section of its notes. Nothing more.
