# Plan 173 — Boon uptime % + Presence % dans le Combat Readout

**Inspiré par :** WvW_Analytics (projet legacy sur la machine locale)

## Résumé

Le backend GW2Analytics **stocke déjà** les pourcentages d'uptime des 14 boons
trackés dans `OrmFightPlayerSummary` (depuis la migration 0018). Mais le
Combat Readout (`GET /fights/{id}/readout`) expose uniquement des **raw counts**
(`stability_out: 42`), pas les pourcentages. WvW_Analytics montre des
pourcentages (Stab 85%, Quick 92%, etc.) — beaucoup plus parlant.

Objectif : **brancher les uptimes** dans le readout, **ajouter `presencePct`**
dans la table Défense, et **mettre à jour l'UI** pour coller au design
WvW_Analytics (barres horizontales avec %).

---

## Phase A — Backend : uptimes dans le readout

### A1. Étendre `PlayerReadoutBoonsOut` (schemas/fight.py)

Ajouter 14 champs `*_uptime: float | None = None` dans
`PlayerReadoutBoonsOut` :

```
might_uptime        # [0, 100] pourcentage
fury_uptime
quickness_uptime
alacrity_uptime
protection_uptime
regeneration_uptime
vigor_uptime
aegis_uptime
stability_uptime
swiftness_uptime
resistance_uptime
resolution_uptime
superspeed_uptime
stealth_uptime
```

**Optionnel** : ajouter aussi les 13 champs `outgoing_*` si l'UI doit
montrer la génération de boons (WvW_Analytics ne les montre pas).

### A2. Étendre `PlayerReadoutDefenseOut` (schemas/fight.py)

Ajouter `presence_pct: float | None = None` dans
`PlayerReadoutDefenseOut`.

Le `presencePct` représente le % de temps où le joueur était présent
dans le combat (basé sur les événements où son `source_agent_id` ou
`target_agent_id` apparaît). À calculer à partir du stream d'événements.

### A3. Hydrater les uptimes depuis `OrmFightPlayerSummary`

Les uptimes sont DÉJÀ calculés pendant le parse dans
`_persist_player_summaries` via `BuffStateTracker` et stockés dans
`OrmFightPlayerSummary`. Pas besoin de les recalculer.

**Architecture :**
- A3.1 : Dans `get_fight_readout` (le route handler), après avoir chargé
  l'identity map, faire un `SELECT` sur `OrmFightPlayerSummary` filtré par
  `fight_id`.
  ```python
  summary_rows = db.execute(
      select(OrmFightPlayerSummary).where(
          OrmFightPlayerSummary.fight_id == fight_id
      )
  ).scalars().all()
  # → dict[account_name, OrmFightPlayerSummary]
  summaries_by_account = {r.account_name: r for r in summary_rows}
  ```
- A3.2 : Ajouter un paramètre `boon_uptimes: dict[str, PlayerBuffUptimeOut]`
  (ou un type plus simple) à `aggregate_combat_readout` → `_build_player_readout`.
- A3.3 : Dans `_build_player_readout`, mapper `account_name` → uptimes et
  les passer à `boons=PlayerReadoutBoonsOut(...)`.

**Justification (vs recalcul depuis les events) :**
- Performance : pas de recomputation O(N) pour chaque chargement de page
- Cohérence : mêmes données que le profile player (`/players/{name}`)
- Simplicité : pas de modification de l'event split dans `aggregate_combat_readout`
- Le `SELECT` sur 1-50 rows est négligeable

**Backward compat :** Les fights parsés avant la migration 0018 ont NULL
pour tous les champs d'uptime. Le frontend doit afficher "—" pour NULL.

### A4. Calcul de `presence_pct`

Définition : pourcentage du temps (en ms) où le joueur a été source ou
cible d'au moins un événement, par rapport à la durée totale du combat.

Algorithme simple :
1. Collecter tous les timestamps d'événements où `source_agent_id == player`
   ou `target_agent_id == player`.
2. Calculer la couverture temporelle : `max_time_ms - min_time_ms` ou
   mieux, utiliser les `PositionEvent` (le joueur envoie des position
   updates même sans événement de combat).
3. Si pas de `PositionEvent` : utiliser `first_event_time_ms` et
   `last_event_time_ms` sur les événements où le joueur apparaît.
4. `presence_pct = coverage_ms / fight_duration_ms * 100`.

Plus simple : compter le nombre de `EventWindow` buckets où le joueur
est actif. Mais une approximation suffit : si le joueur a au moins un
événement dans le premier 1% du combat ET dans le dernier 1%, presence ≈ 100%.

On peut aussi regarder si le joueur a des `PositionEvent` — s'il en a,
il était présent.

**Alternative pragmatique** : utiliser `len(position_samples)` / `max_possible_samples`
comme proxy de présence. Simple et déjà disponible via `/positions`.

---

## Phase B — Route : hydrater les uptimes + presence dans le handler

### B1. Modifier `get_fight_readout` (routes/fights/__init__.py)

- Après le chargement de l'identity map (`agent_id_to_identity`), charger
  les `OrmFightPlayerSummary` rows pour le fight.
- Construire un `dict[account_name, PlayerBuffUptimeOut]` (ou un mapping
  simple des 14 champs d'uptime).
- Passer ce mapping à `aggregate_combat_readout` qui le transmet à
  `_build_player_readout`.
- **Ne pas utiliser `BuffStateTracker` ici** — les uptimes sont déjà
  dans les summaries.

### B2. Calcul du presence_pct

⚠️ **Attention :** un simple calcul `(last_event - first_event) / duration`
est trompeur (un joueur avec 2 events à t=1s et t=299s obtiendrait 100%
pour un combat de 300s).

**Approche retenue :** utiliser les `EventWindow` buckets (5s).
- Découper la durée du combat en buckets de 5s (déjà disponibles dans
  le readout).
- Pour chaque agent, compter le nombre de buckets où il a au moins un
  événement (damage, heal, boon, etc.).
- `presence_pct = (active_buckets / total_buckets) * 100`

**Plus simple (V1) :** approche basée sur les `PositionEvent`.
- Si le joueur a des samples de position, sa présence est liée au
  nombre de samples qu'il a émis / au nombre attendu (~1 sample/500ms).
- `presence_pct ≈ (len(samples) * 500 / duration_ms) * 100`

**Backward compat :** Les fights sans position events ont presence_pct = NULL.

**Décision :** Reporter presence_pct en **Phase E** (hors scope de cette
itération). Priorité : uptimes d'abord.

---

## Phase C — Frontend : remplacer raw counts par pourcentages

### C1. Mettre à jour les colonnes Boons dans `ReadoutTabClient.tsx`

Remplacer les raw counts (`stability_out`, `alacrity_out`, etc.) par
des **pourcentages d'uptime** :

| Avant | Après |
|-------|-------|
| boons_out_rate | boons_out_rate (conservé) |
| boons_in_rate | boons_in_rate (conservé) |
| stability_out: 42 | stability_uptime: 85% |
| alacrity_out: 15 | alacrity_uptime: 92% |
| resistance_out: 8 | resistance_uptime: 12% |
| aegis_out: 3 | aegis_uptime: 45% |
| superspeed_out: 5 | superspeed_uptime: 8% |
| stealth_out: 1 | stealth_uptime: 3% |

**Nouvelles colonnes à ajouter** (comme dans WvW_Analytics) :
- might_uptime (%)
- fury_uptime (%)
- quickness_uptime (%)
- protection_uptime (%)
- regeneration_uptime (%)
- vigor_uptime (%)
- swiftness_uptime (%)
- resolution_uptime (%)

Soit 14 colonnes de pourcentages (vs 6 raw counts avant). Trop large ?
On peut les grouper en deux barres horizontales comme les DPS :
- **Boons offensifs** : Might %, Fury %, Quickness %, Alacrity %
- **Boons défensifs** : Protection %, Regen %, Vigor %, Aegis %,
  Stability %, Resolution %, Resistance %
- **Mobilité** : Swiftness %, Superspeed %
- **Furtivité** : Stealth %

### C2. Barres horizontales pour les uptimes

Inspiré des barres DPS power/condi, créer un `UptimeBarCellRenderer`
qui affiche chaque boon sous forme de barre de progression :

```
[Might ████████████████░░░] 85%
[Fury  ██████████████████░] 95%
[Quick ██████████████░░░░░] 72%
...
```

Ou une version compacte : grouper les 14 boons en **4 barres** :

1. **Offensive Boons** : (Might 85% + Fury 95% + Quick 72% + Alac 68%) / 4
2. **Defensive Boons** : (Prot 45% + Regen 30% + Vigor 60% + Aegis 40% + Stab 25% + Resol 50% + Resist 12%) / 7
3. **Mobility** : (Swift 80% + SS 15%) / 2
4. **Stealth** : Stealth 3%

Chaque barre montre la moyenne du groupe avec une tooltip listant
chaque boon individuellement. C'est plus compact et plus lisible.

### C3. Ajouter `presence_pct` dans la table Défense

Nouvelle colonne après "Dist COM" :
```
Presence % | 98%
```

Format : pourcentage avec une barre de progression stylée.

### C4. Ajuster les `FightSummaryCards`

Vérifier que les summary cards (Top DPS, Top Heal, etc.) utilisent
toujours les bons champs (inchangé).

---

## Phase D — Tests

### D1. Test backend : `test_readout_boon_uptimes`

- Créer un fight avec des `BoonApplyEvent` pour might, fury, quickness
- Vérifier que `GET /fights/{id}/readout` retourne `might_uptime ≈ 100%`
  pour un joueur qui a reçu might toute la durée
- Vérifier que les champs sont `None` pour un fight sans boon events

### D2. Test backend : `test_readout_presence_pct`

- Créer un fight avec des événements répartis sur toute la durée
- Vérifier que `presence_pct ≈ 100%` pour un joueur actif tout le fight
- Vérifier que `presence_pct ≈ 0%` pour un joueur avec un seul event

### D3. Test frontend : colonnes boons

- Vérifier que les colonnes `might_uptime` render correctement
- Vérifier le format `85%`

---

## Résumé des fichiers à modifier

| Fichier | Changement |
|---------|-----------|
| `apps/api/src/gw2analytics_api/schemas/fight.py` | Ajouter 14 champs `*_uptime` dans `PlayerReadoutBoonsOut` |
| `apps/api/src/gw2analytics_api/routes/fights/aggregators.py` | Modifier `_build_player_readout` et `aggregate_combat_readout` pour accepter un mapping account_name → uptimes |
| `apps/api/src/gw2analytics_api/routes/fights/__init__.py` | Dans `get_fight_readout`, charger `OrmFightPlayerSummary`, mapper account_name → uptimes, passer à aggregate_combat_readout |
| `web/src/components/ReadoutTabClient.tsx` | Ajouter 14 colonnes d'uptime à côté des 8 colonnes existantes + barres de progression |
| `apps/api/tests/` | Nouveaux tests pour uptimes dans le readout |

**Hors scope (Phase E) :** presence_pct, outgoing boons, refactor des barres.

---

## Notes techniques

1. **Buff IDs en conflit** entre `buff_state.py` et `player_boons.py` :

   ```python
   # buff_state.py (TRACKED_BUFFS)
   "superspeed": 5974  # skill_id
   "stealth": 13017    # skill_id

   # player_boons.py (KNOWN_BOON_IDS)
   _SUPERSPEED_BUFF_ID = 597   # différent !
   _STEALTH_BUFF_ID = 1305     # différent !
   ```

   Les IDs dans `buff_state.py` sont ceux de WvW_Analytics (corrects
   pour les skill_id GW2). Les IDs dans `player_boons.py` semblent
   erronés. **À auditer avant l'implémentation.**

2. **Performance** : la lecture des uptimes depuis `OrmFightPlayerSummary`
   est un `SELECT` indexé sur ~1-50 rows → coût négligeable.

3. **Les colonnes existantes sont conservées** : `boons_out_rate`,
   `boons_in_rate`, les 6 raw counts (`stability_out`, etc.), et
   `other_boons_out` restent dans le schéma. On AJOUTE les uptimes
   sans rien supprimer. Le frontend pourra décider quelles colonnes
   afficher par défaut.

4. **Rétrocompatibilité** : les fights parsés avant la migration 0018
   ont `NULL` pour tous les champs d'uptime. Le frontend doit afficher
   "—" ou "N/A" quand la valeur est `None`.

5. **ID des buffs dans le stream d'événements** : le `BoonApplyEvent`
   porte `skill_id` qui correspond aux ID d'API GW2. `BuffStateTracker`
   les utilise directement via `TRACKED_BUFFS`. Le `PlayerBoonsAggregator`
   utilise des constantes différentes (`KNOWN_BOON_IDS`) qui sont peut-être
   des `buff_id` de statechange et non des `skill_id`. À auditer.

6. **Outgoing boons** : délibérément exclus de cette itération (WvW_Analytics
   ne les affiche pas non plus). Disponible via `OrmFightPlayerSummary.outgoing_*`
   si besoin futur.
