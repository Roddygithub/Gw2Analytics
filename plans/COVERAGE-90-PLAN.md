# Plan couverture 82% → 90%

**Date** : 2026-07-22  
**Baseline** : 82% (5180 statements, ~913 missing)  
**Cible** : 90% (~520 missing → ~393 additional covered lines)

---

## Progrès réalisé (v0.13.5)

| Fichier | Avant | Après | Delta |
|---|---|---|---|
| `players.py` | 30% | **69%** | +39% |
| `backfill.py` | 22% | **67%** | +45% |
| `uploads.py` | 32% | **85%** | +53% |
| `main.py` | 49% | **91%** | +42% |
| `config.py` | 75% | **90%** | +15% |
| `aggregators.py` | 18% | **88%** | +70% |
| `webhooks.py` | 34% | **95%** | +61% |

---

## Gaps restants (par priorité)

### 🔴 Priorité 1 : guilds.py (0% → 50%)

**Fichier** : `apps/api/src/gw2analytics_api/routes/guilds.py` (34 lignes)  
**Effort estimé** : 1h  
**Tests** : `test_guilds.py` (~15 lignes)

Route GET `/api/v1/guilds/{guild_id}` — retourne les infos d'une guilde. 
- `test_guild_200`: upload un fight avec un membre de guilde, GET guild → 200
- `test_guild_404`: GET guild inconnue → 404

### 🟡 Priorité 2 : guild_service.py (0% → 60%)

**Fichier** : `apps/api/src/gw2analytics_api/services/guild_service.py` (~30 lignes)  
**Effort estimé** : 1h  
**Tests** : `test_guild_service.py` (~20 lignes)

Service de guildes appelé par guilds.py.
- `test_get_guild_data_known`: test avec données mockées
- `test_get_guild_data_unknown`: guild inconnue
- `test_get_guild_data_empty`: guild sans membres

### 🟡 Priorité 3 : __main__.py (0% → 80%)

**Fichier** : `apps/api/src/gw2analytics_api/__main__.py` (7 lignes)  
**Effort estimé** : 30min  
**Tests** : `test_main_cli.py` (~10 lignes)

Entrypoint CLI pour `python -m gw2analytics_api`.
- `test_main_runs_uvicorn`: mock uvicorn.run et vérifie l'appel

### 🟢 Priorité 4 : players.py (69% → 85%)

**Fichier** : `apps/api/src/gw2analytics_api/routes/players.py` (180 lignes, ~126 → ~54 uncovered)  
**Effort estimé** : 2h  
**Tests** : déjà 18 nouveaux tests dans `test_players_routes.py`

Reste : slow-path blob walk, `_contributions_from_blob_walk`, `_load_slow_path_contributions` — ces branches sont difficiles à tester en unitaire car elles nécessitent un blob MinIO valide.

### 🟢 Priorité 5 : uploads.py (85% → 95%)

**Fichier** : `apps/api/src/gw2analytics_api/routes/uploads.py` (80 lignes)  
**Effort estimé** : 1h

Ajouter :
- `test_upload_empty_file` : fichier vide → 201 ou 422 ?
- `test_upload_no_filename` : multipart sans filename
- `test_upload_content_length_413`: Content-Length > max → 413

### 🟢 Priorité 6 : backfill.py (67% → 85%)

**Fichier** : `apps/api/src/gw2analytics_api/backfill.py` (95 lignes, ~74 → ~31 uncovered)  
**Effort estimé** : 1h

Les nouvelles branches (role detection backfill) dans `backfill_role_detection` ne sont pas testées.
- `test_backfill_role_detection_updates_rows` : test unitaire avec rows mockés

---

## Résumé des efforts

| Priorité | Fichier | Lignes | Effort |
|---|---|---|---|
| 🔴 P1 | `guilds.py` | 34 | 1h |
| 🟡 P2 | `guild_service.py` | 30 | 1h |
| 🟡 P3 | `__main__.py` | 7 | 30min |
| 🟢 P4 | `players.py` | 126→54 | 2h |
| 🟢 P5 | `uploads.py` | 54→12 | 1h |
| 🟢 P6 | `backfill.py` | 95→31 | 1h |
| **Total** | | **~250 lignes** | **~6h** |

**Stratégie** : P1+P2 (guilds) donnent le meilleur rapport effort/impact (~64 lignes à 0%). P3 (main) est trivial. Avec ces 3, on gagne ~70 lignes → couverture ~84%. P4+P5+P6 ajoutent ~80 lignes → ~86%. Pour atteindre 90%, il faudrait couvrir ~600 lignes supplémentaires — l'effort le plus productif est P1+P2+P3 (gain rapide).
