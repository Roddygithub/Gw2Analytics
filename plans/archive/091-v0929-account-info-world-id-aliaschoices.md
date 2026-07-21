# Plan 091 (v0.9.29) — `AccountInfo.world_id` `AliasChoices` forward-compat

## Files touched
- `libs/gw2_core/src/gw2_core/models.py` (1-line import addition + 1-line `Field` argument replacement on `AccountInfo::world_id`)

## Findings (audit)

- `models.py::AccountInfo::world_id = Field(..., alias="world", ge=1)` accepts ONLY the legacy wire key `"world"`.
- The v2 REST API documentation is stable today (`GET /v2/account` returns `{"world": <id>}`), so the library works in production.
- BUT: the sibling models (`WorldInfo` / `Population`) all use `extra="ignore"` to be forward-compat with unknown keys. The reasoning at the time (per the docstring on `AccountInfo`): "the v2 API can grow new fields without breaking the library; unknown keys are silently dropped at validation time". That same argument applies IN REVERSE for field RENAMES: a future API rename would 422 ALL clients without warning, because `extra="ignore"` only ignores extras — it can't paper over a missing REQUIRED field.
- The library's design intent is clearly client-stable (the docstring says so). The `alias="world"` single-key wiring is a leak in that intent: it bakes in ArenaNet's exact choice of wire key, which is the one thing the library SHOULD be insulated from.
- Real-world impact: low today, high the moment ArenaNet ships the rename. The 2023-2024 v2 API modernisation wave ArenaNet ran on other endpoints (e.g. `worlds` schema consolidation) sets the precedent; `accounts.world` → `accounts.world_id` is a guaranteed-future schema change.

## Fix

1. `models.py` — extend the `pydantic` import at the top of the file:

   ```python
   from pydantic import AliasChoices, BaseModel, ConfigDict, Field
   ```

2. `models.py::AccountInfo::world_id` — replace:

   ```python
   world_id: int = Field(..., alias="world", ge=1)
   ```

   with:

   ```python
   world_id: int = Field(
       ...,
       validation_alias=AliasChoices("world", "world_id"),
       serialization_alias="world",
       ge=1,
       description=(
           "World the account is currently on. The wire key is "
           "``\"world\"`` today (ArenaNet v2 REST API), but the "
           "library accepts BOTH ``\"world\"`` and ``\"world_id\"`` "
           "via Pydantic ``AliasChoices`` so a future ArenaNet "
           "rename is non-breaking for clients pinning to this "
           "library. The Python attribute (``world_id``) is the "
           "analyst-facing name, matched to ``WorldInfo.id``."
       ),
   )
   ```

   Notes:
   - `validation_alias=AliasChoices(...)` accepts either wire key on input.
   - `serialization_alias="world"` preserves the on-the-wire output format (so `model_dump(by_alias=True)` round-trips against today's API).
   - The Pydantic `Field` `alias=` (read+write alias) is replaced by the more explicit `validation_alias=...` + `serialization_alias=...` pair — single-purpose aliases are easier to audit than the combined one.

## Tests (4 hermetic, NEW file or append to `libs/gw2_core/tests/test_gw2_core_models.py`)

- `test_account_info_accepts_legacy_world_wire_key` — `AccountInfo.model_validate({"id": "ABC", "name": "X.1234", "world": 1234})` succeeds; `info.world_id == 1234`.
- `test_account_info_accepts_modern_world_id_wire_key` — `AccountInfo.model_validate({"id": "ABC", "name": "X.1234", "world_id": 1234})` succeeds; `info.world_id == 1234`.
- `test_account_info_missing_both_alias_keys_raises_validation_error` — `AccountInfo.model_validate({"id": "ABC", "name": "X.1234"})` raises `pydantic.ValidationError` (NOT silently IGNORED — `AliasChoices` does NOT relax the required-ness, it only ADDS candidate keys for the existing requirement).
- `test_account_info_round_trip_preserves_legacy_wire_key` — `info = AccountInfo.model_validate({"id": "ABC", "name": "X.1234", "world": 1234}); info.model_dump(by_alias=True) == {"id": "ABC", "name": "X.1234", "world": 1234}` (round-trip preserves today's wire format even though the deserializer accepted the modern key as well).

## Rejected alternatives

- **Drop the alias entirely and rename the field back to plain `world_id` (no wire alias)** → breaking change for all callers sending `{"world": ...}`. Today the library offers a compatibility shim; removing it is a regression. REJECTED.
- **Use `model_config[populate_by_name] = True` instead of `AliasChoices`** → `populate_by_name` lets you use the Python-name (`world_id`) as INPUT, but it does NOT support accepting MULTIPLE wire keys. The dual-key requirement is exactly what `AliasChoices` is for. REJECTED.
- **`Union[int, str]` as a weaker forward-compat fallback** (accept any key whose value parses as int) → not a real fix, just a workaround; loses the field-name anchor for analysts who query the model by attribute. REJECTED.
- **Leave as-is — "the API hasn't broken yet"** → fine today, but tech debt. The moment ArenaNet ships the rename, every `gw2_api_client::parse_account` callsite fails simultaneously — exactly the kind of production fire that `extra="ignore"` on the sibling models was supposed to prevent here. REJECTED.
- **Use `Field(alias=AliasChoices(...))` (the old combined alias parameter)** → `validation_alias` + `serialization_alias` are more explicit and don't depend on Pydantic's read/write heuristics; also, latest Pydantic v2 emits a `DeprecationWarning` when a dict is passed to the combined `alias=` slot with two keys. REJECTED.
- **Add `extra="allow"` to `AccountInfo::model_config` as a wider safety net** → masks downstream bugs (an API response with a typo'd key would silently produce a model with the typo propagated downstream); also requires dropping `frozen=True`. The targeted `AliasChoices` fix is the minimal change. REJECTED.

## Dependency graph

- Independent from plan 089 (different import + different top-of-file region).
- Independent from plan 090 (different field on a different model).
- No downstream effects: `libs/gw2_api_client/src/gw2_api_client/client.py` passes the wire dict directly to `AccountInfo.model_validate(...)`, so the consumer doesn't change. The new accepted wire key is purely additive for callers that today send `"world"` (unchanged behaviour).
