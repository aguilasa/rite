# Profile — slugkit

## Confirmed decisions

- Node standard library only; no dependencies, no bundler.

## Sources of truth

- [PLAN-slugkit](/docs/plans/PLAN-slugkit.md)

## Generated artifacts

- `src/index.mjs` <- `tools/gen-exports.mjs` (check: `node tools/gen-exports.mjs --check`)

## Gates

- `npm test`
- `node tools/gen-exports.mjs --check`

## Hot files

- `src/index.mjs` (generated; only the generator writes it)

## Serialized resources

None.

## Pull-ahead precedents

None.

## Phase-specific checks

### Phase 1 — functions

- Every exported function has a test under `test/` that exercises the example given in the plan.
- `node tools/gen-exports.mjs --check` passes, so the entry point matches the modules on disk.
- The examples in the plan section hold when run from a shell.
