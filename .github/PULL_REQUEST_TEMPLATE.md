## Summary

-

## Verification

- [ ] Backend checks: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy libs apps/api/src --no-incremental`, `uv run pytest --tb=line -q`
- [ ] Web checks when `web/` changes: `pnpm typecheck`, `pnpm lint`, `pnpm test:unit`
- [ ] Parser/parity checks when parser or analytics behavior changes
- [ ] Not applicable / documented below

## Risk

- [ ] No migration or data-shape change
- [ ] Migration included and tested
- [ ] Security-sensitive change reviewed

## Notes

Every commit needs a `Signed-off-by:` trailer (`git commit -s`).
