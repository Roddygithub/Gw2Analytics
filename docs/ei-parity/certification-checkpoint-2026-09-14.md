# Checkpoint de certification Parser/EI — 2026-09-14

Ce document conserve les résultats métier vérifiés de la certification EI ;
il remplace les checkpoints d'orchestration supprimés.

## Baseline

- Référence : Elite Insights 3.26.0.0 sur 35 journaux privés manifestés.
- Résultat : 235 lignes de différence et 242 `FAIL` atomiques.
- Rotation : 16 lignes, 23 `FAIL` atomiques (5 casts manquants, 18 en trop).
- Les journaux, exports et chemins locaux restent privés et hors Git.

## Mécanismes certifiés

- `42470` Lesser Signet of Stone : gain du buff `883` dans `5 000 ± 9 ms`.
- `12815` Lightning Leap Combo : finder breakbar (`result == 10`) avec ICD de
  50 ms.
- `22499` Shattered Aegis : `result=8` reste un `CombatOutcomeEvent(killed)`;
  il ne doit jamais être promu en `DamageEvent`.
- `77178` Tale of the Valiant Marshal : GUID
  `EBC45B862D299143B4D63CB6CAEC26ED`.
- Mine detonation `-37` : paire d'effets de même source et règle
  `dynamicEnd` EI ; résidu nul.
- La table de GUID d'effet ne retient que `ContentLocal.Effect`; les GUID
  sont last-write-wins entre métadonnées Effect. Cette règle corrige notamment
  le résidu `29560` sans cas particulier par journal ou finder.
- `24755` Thousand Cuts : garde de spécialisation source Virtuoso.
- `76611` Tale of the Honorable Rogue : conserver le GUID EI `DBECB…`, pas le
  GUID local obsolète `69ACA…`.

## Invariants et travaux différés

- L'hypothèse EVTC2025+ qui remplaçait `_srest[5]` par `_srest[8]` dans le
  pré-scan GUID est falsifiée et ne doit pas être réintroduite.
- La fenêtre sémantique de `29560` (10 ms locale contre 50 ms EI) est prouvée
  mais ne change pas ce corpus : la traiter séparément.
- La profondeur de file Régénération `15 → 5` est sans effet sur les 35
  journaux ; aucune modification de capacité n'est justifiée par ce corpus.
- Les résidus restants concernent surtout les uptimes de boons (190 `FAIL`
  atomiques), puis rotation, groupe, down contribution et CC. Les résultats de
  tranche dont les comptes et `firstAware` coïncident sont maintenant distincts
  dans le diff ; ce défaut d'observabilité n'affectait pas le calcul du parser.

## Validation de référence

```bash
uv run --no-cache pytest libs/gw2_evtc_parser/tests/test_parser_emit_buff.py \
  libs/gw2_analytics/tests/test_rotation.py \
  libs/gw2_analytics/tests/test_down_contribution.py \
  libs/gw2_analytics/tests/test_ei_compare.py -q
uv run --no-cache python scripts/ei-parity/ei_diff.py --json /tmp/ei-certification-boundary.json
```
