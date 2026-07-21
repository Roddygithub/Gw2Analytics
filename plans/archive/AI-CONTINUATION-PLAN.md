# Plan de continuité Gw2Analytics

> **Status: COMPLETED (2026-07-21)** — Phases 1-4 delivered. Phase 5 (guild + multi-fight) remains as future work.
> See [CHANGELOG v0.12.5](../CHANGELOG.md) for the audit details.

Ce document est le plan de travail prioritaire pour Gw2Analytics. Il a été écrit pour que n'importe quelle IA (ou développeur humain) récupérant le projet puisse reprendre le travail sans avoir à tout redécouvrir.

---

## Contexte

Le projet Gw2Analytics est une plateforme d'analyse de combats WvW pour Guild Wars 2. Il se compose de :

- `libs/gw2_core` : modèles Pydantic
- `libs/gw2_evtc_parser` : parseur de fichiers `.zevtc`
- `libs/gw2_analytics` : logique analytique (agrégations, rôles, buffs)
- `apps/api` : backend FastAPI + SQLAlchemy + Alembic
- `web/` : frontend Next.js

L'ancien projet `WvW_Analytics` contient une logique métier utile mais n'est pas directement compatible avec le format EVTC2025+.

---

## 1. Recommandations techniques immédiates

### 1.1 Centraliser la logique de build string

**Fichiers concernés** : `apps/api/tests/_fixtures.py`, `apps/api/tests/routes/_evtc_builder.py`, ~12 fichiers de test API.

**Action** : créer un helper unique (dans `_evtc_builder.py`) :

```python
def build_2025_string(suffix: str) -> str:
    return f"2025{int(suffix[:4], 16) % 10000:04d}"
```

Importer et utiliser ce helper partout. Éviter la duplication actuelle.

### 1.2 Améliorer la robustesse du parser

- Documenter que `_build_version_from_build_str` exige 8 chiffres exacts.
- Ajouter des tests unitaires de frontière skill/event avec 0, 1 et 2 événements.
- Ajouter un test de round-trip : générer un EVTC, le parser, et vérifier les champs.

### 1.3 Simplifier le setup des tests

Fournir un `conftest.py` ou une commande `make` qui démarre Postgres + MinIO + Redis et applique les migrations Alembic avant les tests API.

### 1.4 Nettoyer le working tree

S'assurer que tous les fichiers pertinents sont dans git. Commiter les migrations et les nouveaux fichiers source.

### 1.5 Documenter le format EVTC2025+

Créer `docs/EVTC2025_FORMAT.md` avec la structure du header, des agents, des skills et des events.

---

## 2. Plan d'action fonctionnel prioritaire

### Phase 1 — Boon uptimes + outgoing boons (2-3 jours)

**Objectif** : calculer l'uptime et l'outgoing des 14 boons trackés.

**Fichiers clés** :
- `libs/gw2_analytics/src/gw2_analytics/buff_state.py`
- `apps/api/src/gw2analytics_api/services/player_summaries.py`
- `apps/api/src/gw2analytics_api/models.py`
- `apps/api/alembic/versions/` (nouvelle migration)

**Étapes** :
1. Vérifier que `BoonApplyEvent` est bien émis par le parser avec les bons `kind`, `stacks`, `duration_ms`.
2. Compléter `BuffStateTracker` si des cas sont manquants (REMOVE_SINGLE avec stacks > 1, etc.).
3. Ajouter 14 colonnes d'uptime et 13 colonnes d'outgoing dans `OrmFightPlayerSummary`.
4. Brancher le calcul dans `_persist_player_summaries`.
5. Exposer les colonnes dans les schémas et routes players/fights.
6. Écrire des tests unitaires et d'intégration.

### Phase 2 — Strips de boons + cleanses de conditions (1-2 jours)

**Objectif** : compter les strips de boons et les cleanses de conditions par joueur.

**Fichiers clés** :
- `libs/gw2_analytics/src/gw2_analytics/buff_state.py`
- `apps/api/src/gw2analytics_api/services/player_summaries.py`
- `apps/api/src/gw2analytics_api/models.py`

**Étapes** :
1. Gérer correctement les événements de type `remove_single` et `remove_all`.
2. Différencier les buffs trackés (boon strips) des non-trackés (condition cleanses).
3. Ajouter les colonnes correspondantes et brancher le calcul.

### Phase 3 — Finaliser la détection de rôles (1 jour)

**Objectif** : afficher le rôle détecté (DPS / HEAL / STRIP / BOON / MIXED) sur l'interface.

**Fichiers clés** :
- `libs/gw2_analytics/src/gw2_analytics/role_detection.py`
- `apps/api/src/gw2analytics_api/services/player_profiles.py`
- `web/` (pages players / fights)

**Étapes** :
1. S'assurer que `detect_role_lite` est appelé dans le pipeline de persistance.
2. Exposer `detected_role` et `detected_tags` dans les réponses API.
3. Afficher les tags dans le frontend.

### Phase 4 — Heatmaps de position (3-5 jours)

**Objectif** : afficher une heatmap de position par joueur / par combat.

**Fichiers clés** :
- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` (`PositionEvent`)
- `libs/gw2_analytics/src/gw2_analytics/position_analysis.py`
- `web/` (composant de carte)

### Phase 5 — Fonctionnalités de guilde + multi-fight comparison (2-3 semaines)

**Objectif** : comparaison de plusieurs combats et features de guilde.

**Attention** : phase à ne commencer que lorsque les phases 1-4 sont stables et testées.

---

## 3. Notes pour les futures IA

- Le parser binaire est fragile. Ne modifiez pas les structs (`_EVENT_STRUCT_*`) sans recalibrer sur des fichiers réels.
- Les modèles Pydantic de `gw2_core` sont le contrat entre toutes les couches.
- Toute nouvelle colonne en base doit être nullable pour la rétrocompatibilité.
- L'ancien projet `WvW_Analytics` est une référence utile pour la logique métier mais PAS pour le parsing binaire (format legacy).

---

## 4. Commandes essentielles

```bash
# Backend
cd /home/roddy/Projects/Gw2Analytics
uv run ruff check libs apps
uv run mypy libs/gw2_analytics/src apps/api/src --no-incremental
uv run pytest libs apps -q

# API tests avec DB
docker compose up -d postgres minio redis
uv run alembic -c apps/api/alembic.ini upgrade head
uv run pytest apps/api/tests -q
```

---

*Dernière mise à jour : 21 juillet 2026*
