# Profile — textkit

## Confirmed decisions

- Standard library only.

## Sources of truth

- [PLAN-textkit](/docs/plans/PLAN-textkit.md)

## Generated artifacts

None.

## Gates

- `python -m unittest discover -s tests`

## Hot files

- `textkit/__init__.py`

## Serialized resources

None.

## Pull-ahead precedents

None.

## Phase-specific checks

### Phase 1 — functions

- Every public function has a unit test in `tests/` that exercises the example given in the plan.
- The examples in the plan section hold when run from a shell.
