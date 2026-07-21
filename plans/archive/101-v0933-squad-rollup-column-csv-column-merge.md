# Plan 101 (v0.9.33) — `RollupColumn<TRow>` unified interface (merge `SquadRollupColumn` + `CsvColumn`)

## Files touched
- `web/src/lib/csv.ts` (append `RollupColumn<TRow>` + deprecate `CsvColumn<TRow>` as alias; OR — preferred — rename in-place and update all consumers)
- `web/src/components/SquadRollupsGrid.tsx` (swap `SquadRollupColumn` → `RollupColumn` import)
- `web/src/components/PlayersGrid.tsx` (swap `CsvColumn` → `RollupColumn`)
- `web/src/components/SkillUsageTable.tsx` (swap `CsvColumn` → `RollupColumn`)
- `web/src/components/CsvDownloadButton.tsx` (swap `CsvColumn` → `RollupColumn`)
- `web/tests/lib/csv.test.ts` (extend the column-spec tests to cover `width` + verify backward compat of the deprecated alias)

## Findings (audit)

- `web/src/lib/csv.ts::CsvColumn<TRow>` has 3 fields: `field` (keyof TRow) + `headerName` + optional `decimals`.
- `web/src/components/SquadRollupsGrid.tsx::SquadRollupColumn<TRow>` has 4 fields: `field` + `headerName` + optional `decimals` + optional `width`.
- The two interfaces cover the SAME conceptual surface ("a column spec on a roll-up row"): one is the CSV rendering param, the other is the AG Grid rendering param. The grid consumes the SAME column-shape for AG Grid column definitions.
- Today they are exported from different modules: `CsvColumn` from `lib/csv.ts`; `SquadRollupColumn` from `components/SquadRollupsGrid.tsx`. A future column-spec helper (e.g. `csvFromGridColumn(rollup)` or `gridFromCsvColumn(rollup)`) would need to import from BOTH modules, leaking the cross-module coupling.
- `decimals` semantics are the SAME across both: `Number.toFixed(decimals)` for on-screen rendering in the AG Grid (via `valueFormatter`) AND for the CSV cell string. The current `SquadRollupsGrid.tsx` `valueFormatter` (lines 90-95) and the `csv.ts::toCsv` decimals branch BOTH implement `Number.toFixed(decimals)` independently. The duplication is small but real.
- Each component consumers (PlayersGrid, SkillUsageTable, SquadRollupsGrid) compute their column specs in isolation; when a future column-spec migration comes (e.g. adding `render: "bar"` for in-cell bars), every consumer has to update. The unified interface centralises the schema.

## Fix

1. `web/src/lib/csv.ts` — append the unified `RollupColumn<TRow>`:

   ```typescript
   /**
    * Unified column spec for a roll-up table row.
    *
    * Drives both the AG Grid rendering (via :class:`SquadRollupsGrid`'s
    * ``columns`` prop) AND the CSV export (via :class:`CsvDownloadButton` /
    * :func:`toCsv`). Adding a new column-shape field (e.g. ``render`` for
    * in-cell bars) is now a single-file change.
    *
    * The Export order is column-declaration order for both on-screen and
    * downloaded file. ``decimals`` is shared semantics: when set, the
    * value is rendered via ``Number.toFixed(decimals)`` in BOTH the AG Grid
    * ``valueFormatter`` AND the CSV cell string. When unset, raw values
    * are stringified.
    */
   export interface RollupColumn<TRow> {
     /** Pydantic field name on the row model (e.g. ``"total_damage"``). */
     field: keyof TRow & string;
     /** Column header text shown in the grid + the first CSV row. */
     headerName: string;
     /**
      * Optional fixed-decimal formatter for numeric columns. When
      * set, ``Number`` values are rendered as
      * ``value.toFixed(decimals)`` in BOTH the on-screen grid cell
      * AND the downloaded CSV cell. When unset, the raw value is
      * stringified.
      */
     decimals?: number;
     /**
      * Optional explicit column width in pixels for the AG Grid
      * rendering. When unset, AG Grid auto-sizes the column to its
      * content (default behaviour for ``ColDef.width = undefined``).
      * Does not affect the CSV export (the CSV has no width concept).
      */
     width?: number;
   }

   /**
    * Backward-compat alias for :class:`RollupColumn`. New code should
    * import :class:`RollupColumn` directly. The alias is retained
    * because 3 existing components (PlayersGrid, SkillUsageTable,
    * CsvDownloadButton) reference ``CsvColumn`` symbolically
    * and the migration to ``RollupColumn`` will land in plan 101.
    */
   export type CsvColumn<TRow> = RollupColumn<TRow>;
   ```

2. `web/src/components/SquadRollupsGrid.tsx` — drop the local `SquadRollupColumn` interface entirely. Import `RollupColumn` from `lib/csv.ts`:

   ```typescript
   import type { RollupColumn } from "@/lib/csv";
   ```

   And update the props type:

   ````typescript
   export interface SquadRollupsGridProps<TRow> {
     rows: TRow[];
     columns: RollupColumn<TRow>[];
     filename?: string;
   }
   ````

3. `web/src/components/PlayersGrid.tsx` — update the type alias on `CSV_COLUMNS`:

   ```typescript
   const CSV_COLUMNS: RollupColumn<PlayerListRow>[] = [
     // ... unchanged ...
   ];
   ```

4. `web/src/components/SkillUsageTable.tsx` — same `RollupColumn` swap on its `CSV_COLUMNS`.

5. `web/src/components/CsvDownloadButton.tsx` — update the props + import:

   ```typescript
   import type { RollupColumn } from "@/lib/csv";

   // ...

   export interface CsvDownloadButtonProps<TRow> {
     rows: readonly TRow[];
     columns: readonly RollupColumn<TRow>[];
     filename: string;
     label?: string;
   }
   ```

6. NO `lib/csv.ts::toCsv` signature change — it already accepts `readonly CsvColumn<TRow>[]` which is structurally identical to `readonly RollupColumn<TRow>[]` (the alias preserves type identity).

7. NO change to the AG Grid `ColDef<TRow>` mapping in `SquadRollupsGrid.tsx` — the consumer of `RollupColumn` already translates to `ColDef<TRow>` internally.

## Tests (5, EXTEND `web/tests/lib/csv.test.ts`)

- `test_rollup_column_with_width_serialises_to_csv_without_width` — a `RollupColumn{field: "x", headerName: "X", width: 120}` is accepted by `toCsv` and the resulting CSV row 1 contains "x" (the width is ignored during CSV serialization).
- `test_csv_column_alias_is_structurally_identical_to_rollup_column` — `RollupColumn<TRow>` and `CsvColumn<TRow>` are mutually assignable; the alias compiles.
- `test_squad_rollups_grid_accepts_rollup_column_array` — import the `SquadRollupsGrid` fixture column spec from a sample; the TS compiler sees a `RollupColumn` array works as the `columns` prop. (Compile-time check enforced as an explicit `import type` + `as RollupColumn[]` test in the test file.)
- `test_csv_column_alias_deprecation_warning_does_not_break_runtime` — import the old `CsvColumn` symbol from one of the consumer components; assert no runtime side effect (the alias is a pure type-level re-export).
- `test_rollup_column_decimals_shared_semantics_grid_and_csv` — a single `RollupColumn{field: "x", headerName: "X", decimals: 2}` renders `value.toFixed(2)` in BOTH grid + CSV paths. Captures the shared semantics at the test layer; future regressions that diverge the two renderers fail loudly.

## Rejected alternatives

- **Keep the two interfaces distinct, add a `csvOf(gridColumn)` adapter** — adds a runtime adapter without removing the duplication. The two surfaces ARE the same concept; the interface split is purely cosmetic. REJECTED.
- **Use a `RollupColumn<TRow> | GridColumn<TRow>` union** — introduces a discriminated union at the call site; every consumer now has to narrow. The unified interface is simpler. REJECTED.
- **Hoist `RollupColumn` to a new `web/src/lib/columns.ts` module** — adds a new file for a 4-field interface; the console pulse is to keep this adjacent to its primary consumer (`lib/csv.ts`). REJECTED.
- **Drop the `CsvColumn` alias immediately (no backward-compat)** — breaks every existing import path that uses the old name. The alias preserves the import path while the source-of-truth becomes `RollupColumn`. REJECTED.

## Dependency graph

- Independent: touches `lib/csv.ts` + 4 components. No production behaviour change (the alias keeps the runtime call paths byte-identical).
- Parallel-safe with plans 102 / 103 (different file regions).
- Reduces the column-spec surfaces from 2 to 1; future column-shape enhancements (e.g. `render: "bar"` for in-cell bars) are single-file changes.
