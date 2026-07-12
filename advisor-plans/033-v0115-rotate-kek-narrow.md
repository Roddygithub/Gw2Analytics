# Plan 033 — v0.10.15: narrow `except Exception` in `rotate_kek.py`

**Status:** open
**Priority:** P3
**Impact:** LOW-MED (dev DX)
**Confidence:** 1.0

## Finding

`apps/api/scripts/rotate_kek.py:104` `except Exception as exc:`
catches ALL non-`SystemExit` exceptions inside the per-row
decrypt-and-re-encrypt loop. The loop's only operations are:

1. `old_fernet.decrypt(sub.ciphertext).decode("utf-8")`
2. `new_fernet.encrypt(plaintext.encode("utf-8"))`

The legitimate exceptions are:
- `cryptography.fernet.InvalidToken` (KEK mismatch / corrupt ciphertext)
- `UnicodeDecodeError` (corrupt ciphertext rows)
- `sqlalchemy.exc.SQLAlchemyError` (DB transient error)

`Exception` also catches `AttributeError`, `MemoryError`,
`KeyboardInterrupt` (well, `BaseException`-only), `TypeError`,
etc. — none of which are KEK-rotation concerns. Masking these is
a future-debugging landmine: if a script operator sees
"decrypt_failed" with a typed `MemoryError` reason, they would
chase KEK rotation when the actual culprit is upstream.

## Fix

Narrow to the 3 expected exception types:

```diff
-            except Exception as exc:
+            except (
+                cryptography.fernet.InvalidToken,
+                UnicodeDecodeError,
+                sqlalchemy.exc.SQLAlchemyError,
+            ) as exc:
                 session.rollback()
                 failed_count += 1
                 audit_line = {
                     "subscription_id": sub.id,
                     "status": "decrypt_failed",
                     "error": str(exc),
                 }
                 print(json.dumps(audit_line))
```

The error_class discriminator is now visible in the operator's
stderr aggregation; the `error` field already includes `str(exc)`
so the rollback path's logging is informative enough.

## Tests

| Test | File | Type |
|------|------|------|
| `test_rotate_kek_invalid_token_caught` (existing — should still pass) | `apps/api/tests/test_rotate_kek.py` | hermetic |
| `test_rotate_kek_attribute_error_propagates` (NEW) | `apps/api/tests/test_rotate_kek.py` | hermetic |
| `test_rotate_kek_unicode_decode_error_caught` (NEW) | `apps/api/tests/test_rotate_kek.py` | hermetic |

The new `attribute_error_propagates` test seeds a misconfiguration
where the KEK is malformed (so Fernet's `__init__` raises
`ValueError`, NOT `InvalidToken`) — the test asserts the script
exits non-zero and surfaces the `ValueError` (NOT silently
counts as "failed"). This is the regression-pin for the
narrowing.

## Out of scope

- `event_blob.py` `except Exception` in apps/api/src/.../services/event_blob.py
  — INTENTIONALLY broad (per the comment on `event_blob.py:66`).
- `webhook_dispatch.py:174` `except Exception` in retry loop — INTENTIONAL
  worker-loop broad-catch.

## Done criteria

- `uv run ruff check apps/api/scripts` GREEN
- `uv run ruff format --check apps/api/scripts` GREEN
- New tests PASS
- Existing `test_rotate_kek_invalid_token_caught` PASS

## Maintenance note

The doc-comment at `event_blob.py:66` notes the inverse design
pattern: "intentionally broad" catches in worker loops are OK.
The rotate_kek.py script is NOT a worker — it is a batch operator
script. Different contract.

## Escape hatches

- For dev "what's actually happening" debugging, run the script
  with `PYTHONUNBUFFERED=1` — the `print(json.dumps(audit_line))`
  lines already classify per-row status, so a re-run reveals
  which row failed and the exception sub-type stays logged.

## Dependency graph

Standalone — no inter-plan deps.

## Cross-references

- Finding sourced from `plans/AUDIT-2026-07-12-5d0d4d4.md` §"Open
  findings" O2.
- Pairs naturally with plan 032 (main.py except narrow) in the
  same release commit for review convenience.
