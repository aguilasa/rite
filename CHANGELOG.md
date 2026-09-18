# Changelog

All notable changes to this project are documented here. Versions follow [SemVer](https://semver.org/).

## [Unreleased] — 0.1.0

### Added

- `rite.py` CLI (Python 3.11+, stdlib only): `resolve-cycle`, `next`, `new-task`, `new-fix`, `commit-new`,
  `close`, `mark`, `mark-reviewed`, `mark-stale`, `sync`, `check`, `status`, `batch-plan`, `new-cycle`,
  `archive`, `relink`, `anchors`, `stats`, `guard`, `migrate --from we2002`.
- Commands: `/rite:init`, `/rite:new-cycle`, `/rite:plan-to-tasks`, `/rite:status`, `/rite:execute`,
  `/rite:execute-batch`, `/rite:review`, `/rite:fix`, `/rite:fix-all`, `/rite:close-cycle`, `/rite:retro`.
- Agents: `rite-reviewer`, `rite-worker`, `rite-reproducer`.
- Hooks: `PreToolUse` guard for read-only and generated paths; optional `Stop` check.
- `rite.toml` repo config with validation; templates for items, views, profiles, plans and retros.
- Tests: unit and CLI suites over three fixture layouts; an end-to-end loop with headless Claude Code.
