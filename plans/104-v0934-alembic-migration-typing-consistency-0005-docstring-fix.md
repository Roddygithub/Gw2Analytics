# Plan 104 (v0.9.34) — Alembic migration typing consistency + 0005 docstring typo fix

## Files touched
- `apps/api/alembic/versions/0003_fight_skills.py` (annotate `branch_labels = None` → `branch_labels: str | Sequence[str] | None = None`; same for `depends_on`, `revision`, `down_revision`)
- `apps/api/alembic/versions/0007_webhook_retry.py` (same annotation update)
- `apps/api/alembic/versions/0005_fight_player_summaries.py` (fix docstring `Revision ID: 0004_fight_player_summaries` → `Revision ID: 0005_fight_player_summaries`)
- `apps/api/tests/alembic/test_migration_annotations.py` (NEW — 4 hermetic tests pinning the canonical annotation shape via AST inspection)

## Findings (audit)

- Across the 8 migrations (`apps/api/alembic/versions/0001..0008`), the alembic revision-identifier declarations are inconsistent:
  - `0001_v0_5_baseline.py`: `revision: str = "..."` (partially typed) + `branch_labels: str | Sequence[str] | None = None` (fully typed) + `depends_on: str | Sequence[str] | None = None` (fully typed). Uses the dataclass-style annotation across the module.
  - `0002_agent_identity_columns.py`: same fully-typed pattern as 0001.
  - `0003_fight_skills.py`: `revision = "..."` (UN-TYPED) + `branch_labels = None` (UN-TYPED) + `depends_on = None` (UN-TYPED). The comment block says `# revision identifiers, used by Alembic.` but skips the annotations.
  - `0004_fight_events_blob_uri.py`: same fully-typed pattern as 0001/0002.
  - `0005_fight_player_summaries.py`: same fully-typed pattern as 0001/0002.
  - `0006_webhooks.py`: same fully-typed pattern.
  - `0007_webhook_retry.py`: `revision = "..."` (UN-TYPED) + `branch_labels = None` (UN-TYPED) + `depends_on = None` (UN-TYPED). Same pattern as 0003.
  - `0008_payload_bytes.py`: same fully-typed pattern.
- Future `alembic revision --autogenerate -m "..."` invocations inherit the typing from the most-recent source file. With the current 8-file scatter of untyped + fully-typed, autogenerate is non-deterministic — depends on which file the new revision is numbered after.
- A second finding: `0005_fight_player_summaries.py` docstring line 1 says `Revision ID: 0004_fight_player_summaries` but the actual `revision: str = "0005_fight_player_summaries"`. The docstring is off-by-one vs the constant. A future contributor reading the docstring would assume `alembic current` would show `0004_fight_player_summaries` (wrong).
- These drift hazards compound during a release: a refactor that touches the typed revision constants would be safe; one that touches the untyped constants would silently allow `down_revision` to be `None` (which is a valid alembic root revision marker — but if applied to 0003/0007 by mistake, the migration tree would fragment into multiple heads, breaking `alembic upgrade head`).

## Fix

1. `apps/api/alembic/versions/0003_fight_skills.py` — replace:

   ```python
   # revision identifiers, used by Alembic.
   revision = "0003_fight_skills"
   down_revision = "0002_agent_identity_columns"
   branch_labels = None
   depends_on = None
   ```

   with:

   ```python
   revision: str = "0003_fight_skills"
   down_revision: str | None = "0002_agent_identity_columns"
   branch_labels: str | Sequence[str] | None = None
   depends_on: str | Sequence[str] | None = None
   ```

2. `apps/api/alembic/versions/0007_webhook_retry.py` — same canonical-type pattern as the fix above:

   ```python
   revision: str = "0007_webhook_retry"
   down_revision: str | None = "0006_webhooks"
   branch_labels: str | Sequence[str] | None = None
   depends_on: str | Sequence[str] | None = None
   ```

3. `apps/api/alembic/versions/0005_fight_player_summaries.py` docstring — fix the off-by-one:

   ```python
   """v0.8.4: add the fight_player_summaries table to materialise the per-fight per-account roll-up.

   Revision ID: 0005_fight_player_summaries
   Revises: 0004_fight_events_blob_uri
   ...
   """
   ```

   (Was `Revision ID: 0004_fight_player_summaries`.)

4. NO new migration file is added. The annotation update is metadata-only — alembic hashes are based on `revision` string + `down_revision` string + the file contents, but the annotation update changes the file content's Mermaid bytes; alembic's hash algorithm includes the file content, so a `alembic upgrade head` after this PR WOULD register the script as "modified" but harmless — the AST-level changes preserve the runtime behaviour.

5. Wait — alembic uses the file's Python content hash as part of the revision identifier in some workflows. To avoid spurious "downgrade/upgrade" churn, we should verify the alembic hash policy. Per the alembic docs, the default `script_directory` uses `file_template` for naming, NOT a content hash. The migration is identified by `revision` (the string), so the annotation change does NOT bump the alembic key — the migration is still recognised as `0005_fight_player_summaries` (or 0003/0007, respectively). The upgrade/downgrade graph is unchanged.

## Tests (4, NEW file `apps/api/tests/alembic/test_migration_annotations.py`)

- `test_all_eight_migrations_have_typed_revision_constants` — AST-inspect each `apps/api/alembic/versions/*.py` file; assert each declares `revision` + `down_revision` + `branch_labels` + `depends_on` AS `ast.AnnAssign` nodes (with `ast.Name.id == "str"` for `revision` and `ast.BinOp` + `ast.Name.id == "None"` for the optional fields). Catches a future regression where a new migration is added without the annotations.
- `test_revision_does_not_match_down_revision_across_migration_tree` — for each migration, assert `revision != down_revision` (a self-referencing revision would silently form an alembic head-loop). Defensive: catches a future typo where `down_revision` is mistakenly set to the same string as `revision`.
- `test_0005_docstring_revision_id_matches_the_revision_constant` — parse the docstring of `0005_fight_player_summaries.py` and assert the literal `Revision ID: 0005_fight_player_summaries` matches the `revision: str = "0005_fight_player_summaries"` constant. Defensive: catches a future regression where the docstring drifts back.
- `test_alembic_migration_graph_has_single_head` — `alembic heads` subprocess invocation returns exactly one head; this is the canonical "migration graph is well-formed" check. Defensive: catches the failure mode mentioned in the finding (a misapplied `down_revision = None` would create multiple heads).

## Rejected alternatives

- **Add a default `revision_migrations/` template file and copy from it on every autogenerate** — adds a contributor workflow step; the canonical in-file annotation is more discoverable. REJECTED.
- **Move the annotations to a shared `_migration_template.py` and import from each** — alembic scripts MUST be standalone modules (no shared imports allowed in the `versions/` directory per alembic's design); each script is the unit of version control. The in-file pattern is mandatory. REJECTED.
- **Skip the docstring fix in 0005 (the constant is correct)** — leaves the off-by-one footgun in place. The docstring is what future contributors read first; the inconsistency between docstring and constant WILL cause confusion. REJECTED.
- **Replace `str | Sequence[str] | None` with `Optional[str | Sequence[str]]`** — `Optional[Union[str, Sequence[str]]]` is equivalent but the `Optional` import is legacy-style at this point (Python 3.12+ uses the `|` syntax). The current `str | None` is the canonical form. REJECTED.

## Dependency graph

- Independent: touches 3 migration files in disjoint regions (0003 + 0007 typing + 0005 docstring) + 1 NEW test file.
- No alembic graph change — the migration identifiers (`revision` constants) and `down_revision` chain are preserved. The annotation update is metadata-only; the runtime schema is unchanged.
- Parallel-safe with plans 105 / 106.
- Future-proofs the 0009+ migrations: new files will inherit the typed pattern via the AST-pinning test (test #1 fails if a future migration skips the annotations).
