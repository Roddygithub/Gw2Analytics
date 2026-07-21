# 🏗️ Prompt de Passation — Gw2Analytics

Tu es une IA qui reprend le développement de **Gw2Analytics**, une application web + API d'analyse de combats Guild Wars 2 (logs arcdps .zevtc). Voici tout ce que tu dois savoir pour être opérationnelle immédiatement.

---

## 📋 État actuel du projet (20 juillet 2026)

### ✅ Semaine 1-2 — Consolidation (TERMINÉE)

| Tâche | Statut |
|-------|--------|
| Bug durée relative du combat | ✅ Corrigé (seuil 24h→1h dans `blob_loader.py`) |
| Tests E2E Playwright (43/43) | ✅ Passent tous |
| Release v0.11.0 | ✅ CHANGELOG, versions, README à jour |

### ✅ Semaine 3-4 — Phase A : Merge modèle enrichi (TERMINÉE)

Colonnes ajoutées à `OrmFightPlayerSummary` via migration `0016_player_stats_enrich` :

| Colonne | Type | Source |
|---------|------|--------|
| `damage_taken` | BigInteger | `DamageEvent.target_agent_id` (target-side) |
| `downs` | Integer | `DownEvent` |
| `deaths` | Integer | `DeathEvent` |
| `stun_breaks` | Integer | `StunBreakEvent` |

Pile complète : ORM → Migration → `_persist_player_summaries` → `FightContribution` → service SQL → schémas → routes.

### ✅ Semaine 3-4 — Phase B : Events défense (TERMINÉE)

Colonnes ajoutées via migration `0017_player_defense_events` :

| Colonne | Type | Détection | Résultat arcdps |
|---------|------|-----------|-----------------|
| `blocked` | Integer | `result == 3` (CBTR_BLOCK) | La cible bloque l'attaque |
| `dodges` | Integer | `result == 4` (CBTR_EVADE) | La cible esquive (dodge) |
| `interrupts` | Integer | `result == 5` (CBTR_INTERRUPT) | La source interrompt la cible |

Pile complète : parser → ORM → migration → persistence → schemas → routes.

### ⏳ Semaine 3-4 — Reste de Phase B (À FAIRE)

- **Boon uptimes** (14 colonnes) — might, fury, quickness, alacrity, protection, regeneration, vigor, aegis, stability, swiftness, resistance, resolution, superspeed, stealth
- **Outgoing boons** (13 colonnes) — émission des boons vers les coéquipiers
- **Position heatmaps** — depuis `STATE_CHANGE_POSITION` (statechange byte 19)
- **Per-skill healing/barrier** — breakdown par skill_id

### ⏳ Semaine 5+ (À FAIRE)

- **Guild features**
- **Multi-fight comparison**
- **Player progression timeline**
- **Context detection** (zerg/roam/guild raid)

---

## 🏗️ Architecture du projet

```
Gw2Analytics/
├── apps/
│   └── api/                          # Backend FastAPI
│       ├── src/gw2analytics_api/
│       │   ├── models.py             # ORM SQLAlchemy (tables)
│       │   ├── routes/               # FastAPI endpoints
│       │   │   ├── fights/           # Fights routes
│       │   │   │   ├── blob_loader.py  # Cache LRU events
│       │   │   │   └── aggregators.py  # Per-player readout
│       │   │   └── players.py        # Player routes
│       │   ├── schemas/player.py     # Pydantic response models
│       │   └── services/
│       │       ├── player_summaries.py   # _persist_player_summaries
│       │       └── player_profiles.py    # SQL aggregation
│       └── alembic/versions/         # Migrations BDD
├── libs/
│   ├── gw2_core/src/gw2_core/        # Modèles Pydantic (Event, Agent, etc.)
│   │   └── models.py                 # Tous les Event types
│   ├── gw2_evtc_parser/              # Parser binaire EVTC
│   │   └── src/gw2_evtc_parser/
│   │       ├── parser.py             # parse_events() hot loop
│   │       ├── statechange_dispatch.py  # Dispatch table
│   │       └── overlay_log.py        # SCAFFOLD-zero (stub)
│   └── gw2_analytics/                # Logique analytique
│       └── src/gw2_analytics/
│           └── player_profile.py     # FightContribution, PlayerProfile
└── web/                              # Frontend Next.js
```

### Flux de données critique

```
.zevtc → parser.parse_events() → list[Event]  (DamageEvent, HealingEvent,
    BuffRemovalEvent, BlockEvent, DodgeEvent, InterruptEvent,
    DownEvent, DeathEvent, StunBreakEvent, BarrierEvent, etc.)
       ↓
_persist_player_summaries() → OrmFightPlayerSummary (SQL)
       ↓
get_account_contributions_from_sql() → FightContribution
       ↓
routes/players.py → Schemas Pydantic → JSON Response
```

### Comment sont détectés les événements

1. **Damage/Heal/BuffRemoval** — événements non-statechange (`is_statechange == 0`)
   - `is_nondamage == 0` = dégâts directs → `DamageEvent`
   - `is_nondamage > 0` + `value > 0` = heal → `HealingEvent`
   - `buff_dmg > 0` = strip → `BuffRemovalEvent`

2. **Defense events** (Phase B) — depuis le `result` byte du cbtevent
   - `result == 3` (CBTR_BLOCK) → `BlockEvent(source=dst_agent)`
   - `result == 4` (CBTR_EVADE) → `DodgeEvent(source=dst_agent)`
   - `result == 5` (CBTR_INTERRUPT) → `InterruptEvent(source=src_agent, target=dst_agent, skill=skill_id)`

3. **Statechange events** — depuis `is_statechange` byte, dispatch via table
   - byte 4 → `DeathEvent`, byte 5 → `DownEvent`, byte 38 → `BarrierEvent`, byte 56 → `StunBreakEvent`
   - byte 18 → `BuffApplyEvent` (intercepté avant le dispatch générique)

4. **Dodge/Block/Interrupt** — **PAS** des statechange events ! Ils viennent du `result` byte et sont émis dans la branche `is_nondamage == 0` (dégâts). La logique est dans `parser.py` ~ligne 460+.

---

## 🔧 Commandes essentielles

```bash
# Backend
cd /home/roddy/Projects/Gw2Analytics

# Lint + typecheck
uv run ruff check apps/api/src/ libs/
uv run mypy apps/api/src/ libs/ --no-incremental

# Tests
uv run pytest apps/api/tests/ -v --tb=short
uv run pytest libs/gw2_evtc_parser/tests/ -v --tb=short

# Migration BDD
cd apps/api && uv run alembic upgrade head

# E2E browser tests (Playwright)
cd /home/roddy/Projects/Gw2Analytics/web
# Tue d'abord les vieux serveurs tmux :
tmux kill-session -t web-dev 2>/dev/null
tmux kill-session -t api-dev 2>/dev/null
pnpm exec playwright test --project=chromium --reporter=list --workers=1 --timeout=60000
```

### Serveurs de développement

Le projet utilise **2 sessions tmux** :
- `web-dev` → Next.js sur port 3000
- `api-dev` → FastAPI sur port 8080

Scripts de démarrage :
```bash
cd /home/roddy/Projects/Gw2Analytics
# Démarre les serveurs de fond
bash scripts/dev-web-bg.sh
bash scripts/dev-api-bg.sh
```

---

## 📌 Prochaine étape prioritaire : Boon Uptimes

C'est LA fonctionnalité la plus impactante du reste de Phase B. Voici ce qu'il faut implémenter :

### Ce que fait WvW_Analytics (code de référence)

Dans `WvW_Analytics/libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` :

```python
TRACKED_BUFFS: dict[str, int] = {
    "might": 740,
    "fury": 725,
    "quickness": 1187,
    "alacrity": 30328,
    "protection": 717,
    "regeneration": 718,
    "vigor": 726,
    "aegis": 743,
    "stability": 1122,
    "swiftness": 719,
    "resistance": 26980,
    "resolution": 873,
    "superspeed": 5974,
    "stealth": 13017,
}
```

WvW_Analytics utilise `STATE_CHANGE_BUFF_APPLY` (69), `STATE_CHANGE_BUFF_INITIAL` (18), `STATE_CHANGE_BUFF_REMOVE_SINGLE` (71), `STATE_CHANGE_BUFF_REMOVE_ALL` (72) pour tracker les changements de buffs. Voir `_process_buff_change()` dans le même fichier.

### Dans Gw2Analytics

Les événements `BoonApplyEvent` sont déjà émis par le parser (Phase 9), avec `kind: "apply" | "remove_single" | "remove_all"`. Ce qu'il manque :

1. **BuffState tracker** — Un accumulateur qui suit les stacks de chaque buff par joueur, et calcule l'uptime (time * stacks / fight_duration)
2. **14 colonnes boon uptime** dans `OrmFightPlayerSummary` (1 par buff)
3. **13 colonnes outgoing boon generation** (émission vers les autres)

### Approche recommandée

1. Lire `_process_buff_change()` dans WvW_Analytics pour voir comment le `BuffState` tracker fonctionne
2. Implémenter un tracker similaire dans `player_summaries.py` ou dans un nouveau module `libs/gw2_analytics/buff_uptime.py`
3. Les `BoonApplyEvent` du parser Gw2Analytics ont déjà `kind`, `skill_id` (= buff ID), `stacks`, et `duration_ms`
4. Ajouter les colonnes + migration + pipeline complet

### Piège connu

Les buffs dans arcdps sont encodés par leur **skill_id** (ex: might=740). Il faut une table de lookup `buff_id → nom du buff` (déjà dans `TRACKED_BUFFS`). Certains événements `BoonApplyEvent` ont `kind="apply"` avec `stacks=1` — d'autres sont `"remove_all"` ou `"remove_single"`. Le tracker doit maintenir un état courant des stacks par buff.

---

## ⚠️ Contraintes importantes

1. **Ne JAMAIS modifier les structs binaires** (`_EVENT_STRUCT_EVENTS`, etc.) sans re-exécuter le "F1 calibration pilot" — les positions des bytes sont calibrées empiriquement
2. **Toujours appliquer la migration BDD** après avoir ajouté des colonnes : `cd apps/api && uv run alembic upgrade head`
3. **Layer separation** : le parser (`gw2_evtc_parser`) n'importe PAS de `gw2_analytics` (c'est une couche fondation, l'analyse est une couche supérieure)
4. **Tous les champs enrichis doivent être nullable** (backward compat avec les lignes pré-migration)
5. **Tester avec les vrais fichiers** : le dossier `WvW_Analytics/uploads/` contient des vrais logs .zevtc pour les tests réels

---

## 📂 Fichiers clés à connaître

| Fichier | Pourquoi |
|---------|----------|
| `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` | Le hot loop `parse_events()` — coeur du parser |
| `libs/gw2_evtc_parser/src/gw2_evtc_parser/statechange_dispatch.py` | Table de dispatch des statechange bytes |
| `libs/gw2_core/src/gw2_core/models.py` | Tous les modèles d'events + `_EVENT_MAP` |
| `apps/api/src/gw2analytics_api/services/player_summaries.py` | `_persist_player_summaries` — écriture des stats |
| `apps/api/src/gw2analytics_api/models.py` | ORM SQLAlchemy |
| `apps/api/src/gw2analytics_api/schemas/player.py` | Schemas Pydantic de réponse |
| `apps/api/src/gw2analytics_api/routes/players.py` | Routes API players |
| `apps/api/src/gw2analytics_api/services/player_profiles.py` | SQL aggregation |
| `libs/gw2_analytics/src/gw2_analytics/player_profile.py` | `FightContribution` model |
| `apps/api/alembic/versions/0017_player_defense_events.py` | Dernière migration (modèle pour les suivantes) |
| `/home/roddy/Projects/WvW_Analytics/libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` | Code de référence WvW_Analytics (parser complet) |

Bon courage ! 🚀
