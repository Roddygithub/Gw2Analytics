# Plan 032 — v0.10.15: narrow `except Exception:` in `main.py:113` arq pool init

**Status:** open
**Priority:** P2
**Impact:** MED (ops)
**Confidence:** 1.0

## Finding

`apps/api/src/gw2analytics_api/main.py:113` `except Exception:` in
the Arq pool init swallows ALL non-`SystemExit` exceptions with no
exception-type logging. A misconfigured deployment masks the
underlying `ConnectionError` / `OSError` / `TimeoutError` /
`ModuleNotFoundError` reason when only the WARNING-level
`logger.exception(...)` line fires.

The doc-comment explicitly justifies the broad catch:

> "The try/except is intentionally broad: arq raises a mix of
> ``ConnectionError`` (Redis unreachable), ``OSError`` (DNS), and
> ``TimeoutError`` (slow broker) on init failure."

But arq init failure with a specific exception type + a logger
exception line is **just as informative** as a broad `except
Exception` — `logger.exception(...)` already prints the traceback
with the exception type. The broad catch only fires on exception
classes the comment does NOT document (e.g. `AttributeError` from
a `redis_settings` typo, `KeyError` from `REDIS_HOST` typo),
swallowing real shipped-but-broken misconfigurations.

## Fix

Narrow the catch to the documented exception classes:

```diff
-    except Exception:
+    except (ConnectionError, OSError, TimeoutError) as exc:
         # The try/except is intentionally narrow: arq
         # raises a mix of ``ConnectionError`` (Redis
         # unreachable), ``OSError`` (DNS), and
         # ``TimeoutError`` (slow broker) on init
         # failure. Other exception classes (e.g.
         # ``AttributeError``) propagate so a typo'd
         # ``redis_settings`` field doesn't silently
         # disable the parser pipeline AND log a
         # misleading "arq pool init failed" warning.
         logger.exception(
             "arq pool init failed (type=%s); uploads will use the "
             "BackgroundTasks fallback (slower on parallel "
             "uploads, but functional)",
             type(exc).__name__,
         )
```

## Tests

| Test | File | Type |
|------|------|------|
| `test_arq_pool_init_redis_down_falls_back` (existing — narrow to `OSError`) | `apps/api/tests/test_main_lifespan.py` | hermetic |
| `test_arq_pool_init_attribute_error_propagates` (NEW) | `apps/api/tests/test_main_lifespan.py` | hermetic |

The existing `Redis down` test (already pins OSError / ConnectionError behavior) gains assertion specificity. The new test cases the `redis_settings.host = "bad"` typo case — narrows confirm the fix prevents the silent-down behavior.

## Out of scope

- `webhook_scheduler.py:153/342` `except Exception` — INTENTIONAL worker-loop broad-catch (1 bad iteration must not kill the worker). Out.
- `stuck_upload_sweeper.py:65`, `parser_worker.py:121/132` `except Exception` — same intent rationale. Out.
- `health_gate.py:148` `except Exception` — separate script; revisit in plan 046 if it lands as standalone.

## Done criteria

- `uv run ruff check apps/api/src` GREEN
- `uv run mypy apps/api/src` GREEN
- New `test_arq_pool_init_attribute_error_propagates` PASS (pin the narrowing)
- Existing `test_arq_pool_init_redis_down_falls_back` PASS (regression of the "fall back gracefully" contract)

## Maintenance note

The doc-comment is preserved as the rationale. Future readers: do
NOT widen the catch again — a typo'd `redis_settings.host` is
shippable as a real bug, not a transient init failure. If a new
exception class legitimately surfaces (e.g. a future arq version
adds a custom error), add it to the tuple, do NOT widen to bare
`except`.

## Escape hatches

- For dev-only "swallow everything" debugging, the operator can
  set `LOGLEVEL=DEBUG` and add `pdb.pm()` manually — no code
  change required to the exception narrowing.

## Dependency graph

Standalone — no inter-plan deps. Independent of all 6 v0.10.10
plans (026-031). Pairs naturally with plan 033 (rotate_kek.py
narrow) in the same release PR for review convenience.

## Cross-references

- Finding sourced from `plans/AUDIT-2026-07-12-5d0d4d4.md` §"Open
  findings" O1.
- `CONTRIBUTING.md` "No bare `except:` — catch specific exception
  types" is the project-wide rule this plan enforces for the
  cited surface.
