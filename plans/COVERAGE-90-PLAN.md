# Plan couverture 82% → 90%

**Date** : 2026-07-22  
**Baseline** : 82% (5180 statements, ~913 missing)  
**Cible** : 90% (~520 missing → ~393 additional covered lines)  
**Actuel** : **84%** ✅ (+2% depuis le début des améliorations)

---

## Progrès réalisé

### v0.13.5 — Audit fixes (P0-P3)

| Fichier | Avant | Après | Delta |
|---|---|---|---|
| `players.py` | 30% | **69%** | +39% |
| `backfill.py` | 22% | **67%** | +45% |
| `uploads.py` | 32% | **85%** | +53% |
| `main.py` | 49% | **91%** | +42% |
| `config.py` | 75% | **90%** | +15% |
| `aggregators.py` | 18% | **88%** | +70% |
| `webhooks.py` | 34% | **95%** | +61% |

18 tests ajoutés dans `test_players_routes.py` (parse_profession_filter, combine_day_midnight, timelines, labels).

### v0.13.6 — P1 guilds (0% → 70%)

| Fichier | Avant | Après | Delta |
|---|---|---|---|
| `guilds.py` | 0% | **~70%** | +70% |
| `guild_service.py` | 0% | **~40%** | +40% |

5 tests de route dans `test_guilds.py` (list 200, list empty, detail 200, detail 404, multi-member).
Fix : routeur guilds jamais monté dans `main.py` — corrigé.

### v0.13.7 — P3 __main__ + P5 uploads edge cases

| Fichier | Avant | Après | Delta |
|---|---|---|---|
| `__main__.py` | 0% | **100%** | +100% |
| `uploads.py` | 85% | **~93%** | +8% |

- `test_main_cli.py`: mock uvicorn.run, vérifie host/port
- `test_upload_edge_cases.py`: 413 oversized, 413 Content-Length, empty file
- Conftest: Guild+GuildMember ajoutés au cleanup (8 tables)

### v0.13.8 — P6 backfill_role_detection (67% → 85%)

| Fichier | Avant | Après | Delta |
|---|---|---|---|
| `backfill.py` | 67% | **~85%** | +18% |

4 tests dans `test_backfill_role_detection.py` (update null rows, idempotency, dry_run, empty DB).
Seed complet Upload → OrmFight → OrmFightPlayerSummary (FK chain).

### v0.13.9 — Modernisation SQL (0 legacy db.query())

- Audit complet : **ZÉRO** `db.query()` legacy restant dans `apps/api/src/`
- `guild_service.py`: `select().join().where()` remplace le dernier `query().join().filter()`

---

## Résumé des efforts réalisés

| Priorité | Fichier | Avant | Après | Effort réel |
|---|---|---|---|---|
| 🔴 P1 | `guilds.py` | 0% | ~70% | 30min |
| 🟡 P2 | `guild_service.py` | 0% | ~40% | 15min |
| 🟡 P3 | `__main__.py` | 0% | 100% | 10min |
| 🟢 P4 | `players.py` | 30% | 69% | 1h |
| 🟢 P5 | `uploads.py` | 85% | ~93% | 20min |
| 🟢 P6 | `backfill.py` | 67% | ~85% | 30min |
| ♻️ | Legacy queries | 2 files | 0 | 10min |
| **Total** | | **82%** | **84%** | **~3h** |

## Gaps restants

Les fichiers les plus bas restants sont :
- `__main__.py` : 0% → 100% ✅ **DONE**
- `guilds.py` : 0% → ~70% ✅ **DONE**
- `guild_service.py` : 0% → ~40% (la fonction `sync_guilds` stub est difficile à tester sans mock API)
- `players.py` : 30% → 69% (slow-path blob walk difficile à tester sans blob MinIO valide)
- `backfill.py` : 67% → ~85% ✅ **DONE**

Pour atteindre 90%, il faudrait couvrir les chemins lent du blob walk dans `players.py` (~60 lignes) et `backfill.py` (~20 lignes) à l'aide de données de test EVTC réelles.
