## PROJET Gw2Analytics — Résumé de session (2026-08-04)

### Objectif
Parité totale du parser avec Elite Insights (EI) v3.26.0.0 sur les logs WvW (0 diff).

### État du travail
- **En cours :** investigation du surcomptage regen sur "Non Squad Player 50" (`20260125-001308`, instanceID 3089, account "Non Squad Player 50", agent 38309).
- Constat probe : notre tracker compte regen actif jusqu'à rel≈50320 (55.845 %) alors que EI l'arrête à rel=40940 (44.757 %). Dernier événement regen à rel=21118.
- **Cause probable identifiée** : les événements `remove_manual` (7 présents sur cet agent) ne sont PAS pris en charge dans `BuffStateTracker.process()` — seuls `apply`, `remove_single`, `remove_all` sont gérés. Les `remove_manual` sont donc ignorés et les stacks ne sont pas retirés → surcomptage.
- EI states : `[[0,0],[2905,1],[40940,0]]`. Règle d'uptime EI : uptime calculé sur événements/états, pas sur présence cumulée simple.

### Next Move
1. Ajouter la gestion de `kind == "remove_manual"` (et vérifier `remove_all`) dans `buff_state.py` — traiter comme un remove de la stack correspondante (par durée/stack_id), façon EI.
2. Ré-échantillonner : `uv run python scripts/ei-parity/ei_diff.py 20260125-001308 --show "buffUptimes"` et comparer inst 3089.
3. Vérifier que les "Non Squad Player" 50/58 passent de 52.2/51.895 → 44.757/43.852.

### Fichiers clés
- `libs/gw2_analytics/src/gw2_analytics/buff_state.py` — ligne ~337 (`remove_single`), ~372 (`remove_all`), ~295 (`apply`) ; **manque `remove_manual`**.
- `libs/gw2_analytics/src/gw2_analytics/ei_compare.py`
- `scripts/ei-parity/ei_diff.py`, `.tooling/ei-out/<stem>_detailed_wvw_kill.json`
- Probes `/tmp/probe_ev.py`, `/tmp/probe_tr.py`

### Probes
- `/tmp/probe_ev.py <stem> <instanceID>` : dumps événements regen ciblant un agent.
- `/tmp/probe_tr.py <stem> <instanceID>` : trace le tracker stack par événement (before/after expirations).