# Plan 172 — Merge du modèle de données WvW_Analytics → Gw2Analytics

**Date :** 2026-07-20
**Objectif :** Enrichir le modèle `fight_player_summaries` de Gw2Analytics avec les 80+ colonnes supplémentaires du modèle `player_stats` de WvW_Analytics.

---

## 1. État des lieux

### Gw2Analytics — `OrmFightPlayerSummary` (modèle actuel)

| Groupe | Colonnes |
|--------|----------|
| **Identité** | `fight_id`, `account_name`, `name`, `profession`, `elite_spec` |
| **3 magnitudes** | `total_damage`, `total_healing`, `total_buff_removal` |
| **Rôle** | `detected_role`, `detected_tags` |
| **Split** | `power_damage`, `condi_damage` |

**Total : ~12 colonnes**

### WvW_Analytics — `PlayerStats` (modèle cible)

| Groupe | Colonnes | Stats |
|--------|----------|-------|
| **Identité** | `fight_id`, `is_ally`, `character_name`, `account_name`, `profession`, `elite_spec`, `spec_name`, `effective_spec`, `subgroup` | 9 |
| **Dégâts** | `total_damage`, `dps`, `power_damage`, `condition_damage`, `downs`, `kills`, `cc_total`, `down_contribution`, `applied_cc_duration_ms` | 9 |
| **Support** | `healing_out`, `barrier_out`, `cleanses`, `cleanses_other`, `cleanses_self`, `cleanses_time_other`, `cleanses_time_self`, `resurrects`, `resurrect_time`, `stun_breaks`, `stun_break_time` | 11 |
| **Strips** | `strips_out`, `strips_in`, `strips_time` | 3 |
| **Défense** | `damage_taken`, `deaths`, `dead_count`, `downs_count`, `downed_damage_taken`, `blocked_count`, `evaded_count`, `missed_count`, `interrupted_count`, `dodged_count`, `barrier_absorbed`, `invulned_count` | 12 |
| **Boons uptime (14)** | `might_uptime`, `fury_uptime`, `quickness_uptime`, `alacrity_uptime`, `protection_uptime`, `stability_uptime`, `regeneration_uptime`, `vigor_uptime`, `aegis_uptime`, `resistance_uptime`, `resolution_uptime`, `superspeed_uptime`, `swiftness_uptime`, `stealth_uptime` | 14 |
| **Boons outgoing** | `stab_out_ms`, `aegis_out_ms`, `protection_out_ms`, `quickness_out_ms`, `alacrity_out_ms`, `superspeed_out_ms`, `resistance_out_ms`, `resolution_out_ms`, `swiftness_out_ms`, `might_out_stacks`, `fury_out_ms`, `regeneration_out_ms`, `vigor_out_ms` | 13 |
| **Auras** | `fire_aura_out_ms`, `frost_aura_out_ms`, `shocking_aura_out_ms`, `magnetic_aura_out_ms`, `chaos_aura_out_ms`, `light_aura_out_ms`, `dark_aura_out_ms` | 7 |
| **Temps** | `dead_duration_ms`, `dc_duration_ms`, `active_ms`, `presence_pct` | 4 |
| **Position** | `stack_dist`, `dist_to_com`, `time_wasted`, `time_saved` | 4 |
| **Divers** | `weapon_swaps`, `anim_percent`, `anim_no_auto_percent`, `against_downed_count`, `against_downed_damage`, `received_cc_count`, `received_cc_duration_ms`, `stun_removed_duration_ms`, `participation_status` | 9 |
| **Per-skill JSON** | `skill_casts`, `outgoing_healing_by_skill`, `outgoing_barrier_by_skill`, `position_samples` | 4 |
| **Total** | | **~99 colonnes** |

---

## 2. Stratégie de merge

### Approche recommandée : merge en 3 phases

#### Phase A — Colonnes déjà parsables (faible effort)

Ces données sont déjà disponibles dans le pipeline d'events de Gw2Analytics — il suffit d'ajouter les colonnes ORM + persistance.

| Colonne | Source dans Gw2Analytics |
|---------|--------------------------|
| `damage_taken` | Calculable depuis les `DamageEvent` (target_agent_id = player) |
| `cleanses` | `BuffRemovalEvent` avec untracked buffs |
| `strips_out` | `BuffRemovalEvent` avec tracked buffs |
| `strips_in` | `BuffRemovalEvent` target-side |
| `deaths` | `DeathEvent` déjà dans le pipeline |
| `downs` | `DownEvent` déjà dans le pipeline |
| `stun_breaks` | `StunBreakEvent` déjà dans le pipeline |
| `barrier_out` | `BarrierEvent` déjà dans le pipeline |

**Effort estimé :** 4-6h (ajout ORM + persistance + tests)

#### Phase B — Colonnes nécessitant l'extension du parser

Ces données nécessitent d'étendre le parser EVTC pour émettre de nouveaux types d'events.

| Colonne | Nécessite |
|---------|-----------|
| `blocked_count`, `evaded_count`, `missed_count`, `interrupted_count`, `dodged_count` | Extension parser → `BlockEvent`, `DodgeEvent`, `InterruptEvent` |
| `healing_by_skill`, `barrier_by_skill` | Extension parser → `ExtHealingStats` sidecar |
| `position_samples` | Extension parser → `STATE_CHANGE_POSITION` |
| `boon_uptimes` (14) | Extension parser → buff tracking |
| `boon_outgoing` (13) | Extension parser → buff application attribution |

**Effort estimé :** 12-16h (extension parser + persistance + tests)

#### Phase C — Colonnes nécessitant l'analyse WvW_Analytics

Ces colonnes viennent de l'analyse WvW_Analytics mais n'ont pas de source directe dans les events arcdps.

| Colonne | Source |
|---------|--------|
| `stack_dist`, `dist_to_com` | Position data + commander tracking |
| `time_wasted`, `time_saved` | Calculé depuis position data |
| `presence_pct` | Calculé depuis active_ms / duration_ms |
| `cc_total` | Defiance bar damage (état 19) |
| `resurrects` | Skill ids 848/1066/12538 |
| `participation_status` | Heuristic from event activity |

**Effort estimé :** 8-12h (analyse + implémentation + tests)

---

## 3. Plan d'exécution détaillé

### Phase A (Semaine 3-4, Jours 1-2)

1. **Ajouter les colonnes ORM** dans `apps/api/src/gw2analytics_api/models.py`
   - Nouvelle table `fight_player_stats` ou enrichissement de `fight_player_summaries`
   - Migration Alembic `0015_enrich_player_stats`

2. **Étendre la persistance** dans `apps/api/src/gw2analytics_api/services/event_blob.py`
   - Récupérer les champs additionnels depuis les events streams
   - Calculer les totaux par joueur

3. **Mettre à jour les schemas API** dans `schemas/player.py`
   - Ajouter les nouveaux champs aux Pydantic models

4. **Tests** — vérifier l'intégrité des données parsées

### Phase B (Semaine 3-4, Jours 3-4+)

1. **Extension du parser EVTC** dans `libs/gw2_evtc_parser/`
   - Émettre `DodgeEvent`, `BlockEvent`, `InterruptEvent` depuis les events `is_statechange`
   - Implémenter le buff tracking pour les boon uptimes

2. **Sidecar JSON loader** pour `arcdps_healing_stats`
   - Inspiré de l'implémentation WvW_Analytics

3. **Position heatmaps** — échantillonnage depuis `STATE_CHANGE_POSITION`

## 4. Recommandations

1. **Commencer par Phase A** — les colonnes déjà disponibles dans les events streams sont les plus rapides à merger et donnent un ROI immédiat (défense, cleanses, strips, downs/kills)
2. **Utiliser BigInteger** pour toutes les colonnes de magnitude (prévention du débordement WvW)
3. **Utiliser Float pour les uptimes** (ratios 0.0-1.0 déjà format standard dans l'industrie GW2)
4. **Garder les colonnes additionnelles dans une table séparée** (`fight_player_stats` étendue) pour ne pas casser le contrat existant de `fight_player_summaries`
5. **Nullable par défaut** pour les nouvelles colonnes — compat ascendante avec les fights parsés avant la migration
