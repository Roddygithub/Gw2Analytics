# Supermemory — Export Gw2Analytics

Export des résumés de session sauvegardés dans l'espace supermemory `gw2analytics`
(9 documents), du plus récent au plus ancien. Généré le 2026-08-11.

Chaque entrée conserve son ID de document supermemory pour retrouver l'original.

---

## 2026-08-08 — Fix du filtre de tranche rotation (negatives casts)

Document ID: `UitXS67X582dGsEopMH6Va`

### Objectif
Parité rotation EI : éliminer les diff rotation entre le parser in-house et le JSON EI des logs WvW zevtc.

### État du travail
**FAIT — Fix du filtre de tranche (slice) pour les rotations (ei_compare.py:761-770).**
- Problème : les casts de skills dont le **début** d'activation est avant le début du log (castTime relatif négatif, ex. dodge 23275 à -440ms, activation fin seule dans le log) étaient exclus par le filtre `slice_lo <= cast.time_ms + origin <= slice_hi`.
- Règle EI découverte (vérifiée sur tout le corpus, 57k casts) : un cast appartient à la tranche [firstAware, lastAware] contenant son **ancre** = début d'activation si le début est dans le log (cast.time_ms ≥ 0), sinon la **fin** de l'activation (cast.time_ms + duration_ms). Les castTimes négatifs d'EI (104 cas) sont tous dans des comptes à tranche unique → le parser émet déjà ces casts (branch `elif event.duration_ms > 1` rotation.py:552), c'était uniquement le filtre ei_compare qui les rejetait.
- Résultat : rotation missing 461 → **389** (-72), extra 178 → **179** (+1). Dodge 23275 : 7 missing → **0**, extra 0 → 0. Plusieurs négatifs réglés : 29772, 29855, 50947, 31496, 29965, 10555, 73091, 9140, 30229, 14358, 9253, 62565, 63163, 29772, 9265 (partiel).
- Le +1 extra restant : 2 cas de duration 9265 (2240 vs 2200, Guiritoui/insertcoin) et le cas edge Non Squad Player 43 / 29772@-1090 (instance ID 2448 partagé entre Nikola et un Scrapper ennemi → matching agent ambigu, hors filtre).

**REJETÉ — Dodge 23275 via DodgeEvent** : le parser émet un DodgeEvent par attaque évadée (résultat 4), EI n'ajoute 23275 en rotation qu'à partir des activations skill (début d'activation hors log). Branche DodgeEvent→23275 testée : 4428 extras. Ne PAS refaire.

### Next Move
- Duration 9265 2240 vs 2200 (2 logs) : pourquoi le parser produit 2200 (probablement cast_duration réel vs durée canonique EI).
- L'instance ID 2448 partagée (Nikola.8512 + Non Squad Player 43) : décider si le matching d'agent par instance doit tenir compte de l'account.
- Prochaine grosse piste : -27 (Blink/Phase Retreat, guid C34E250B01FF534292EE6AB36D768337, 10 missing / 9 extra) et -41, -7, -6, -11, -14 (négatifs synthétiques).

### Fichiers clés
- `libs/gw2_analytics/src/gw2_analytics/ei_compare.py` : `_rotation_unmatched` (nouveau, matcher par skill+time±2/dur), filtre tranche rotation (ancre début sinon fin), chronomancer ajouté à l'ensemble Mesmer (guid effect 10310/-27).
- `libs/gw2_analytics/src/gw2_analytics/rotation.py` : inchangé fonctionnellement ce coup-ci (patch local Engineer kit toujours en place).
- `libs/gw2_analytics/tests/test_rotation.py` : +35 lignes (patch local).

### Notes de décision
- Les outils bash/read/rtk de cette session ont renvoyé des sorties corrompues (répétitions, numéros de ligne) ; `git checkout -- rotation.py` a été lancé par erreur mais le fichier n'était PAS corrompu — vérifier par md5/size avant toute restauration en cas de doute.
- Les diffs EI sont générés via `uv run python scripts/ei-parity/ei_diff.py --json /tmp/gw2a-ei-diff-v8.json`. Le JSON /tmp/gw2a-ei-diff.json (version "7 missing 23275") était valide ; v8 est le dernier état correct.

---

## 2026-08-05 — ROOT CAUSE origine rotation résolu (start_time_ms / CBTS_START exposé)

Document ID: `oBgtFsaFVKivQA2AuqvSzU`

### Objectif
Réduire les diffs de parité rotation (players.rotation) vs GW2EI sur le corpus WvW (35 logs).

### État du travail (fait / en cours / bloqué)
- FAIT — DIAGNOSTIC conclu: notre origin = min(e.time_ms) était parfois 1ms PLUS TARDIVE que l'origine d'EI. Les 3 pires logs (20260526=45, 20260708=29, 20260118=17) avaient exactement ce décalage +1ms; les logs alignés souffraient d'autre chose.
- VÉRIFIÉ: l'origine d'EI = le statechange 9 (CBTS_START / log start marker), qui est à min(event)-1 sur ces logs, et = min(event) sur les autres. Confirmé par alignement des weapon-swaps (-2): shift +1 seulement sur les 3 fautifs.
- FAIT — FIX ROOT CAUSE implémenté:
  1. parser.py `_extract_evtc2025_metadata`: exposer `out["start_time_ms"] = ev[0]` du statechange 9 (jusque-là lu mais jeté; seul duration_ms=end-start était calculé).
  2. parser.py `_iter_fights`: passer `start_time_ms=metadata.get("start_time_ms")` au EvtcHeader.
  3. libs/gw2_core/models.py EvtcHeader: ajouter `start_time_ms: int | None = Field(default=None, ge=0)`.
  4. ei_compare.py ligne ~244: `origin = header.start_time_ms if header.start_time_ms is not None else min(event.time_ms)`. (build_skill_rotation utilisait déjà ce start_time_ms via son arg 3 positionnel `origin`, fallback min — cohérent.)
- BILAN: rotation diffs 416 → 378 ; total diffs 1108 → 1012 sur les 35 logs. Améliorations ciblées uniquement (aucune régression): 20260526 45→23, 20260708 29→17, 20260118 17→13; tous les autres logs inchangés.
- TESTS: 524 passed, 15 skipped. Ruff + mypy OK.
- NE PAS OUBLIER (session précédente, non commité): les 11 entrées de mapping ajoutées dans rotation.py (_BUFF_GAIN_CASTS + 51664:14410,32931:31187,62931:62758,9422,29502:30435,76507:5635 ; _DAMAGE_CASTS + 76783:75,24305:50,13907:50 ; _INSTANT_CASTS_BY_EFFECT + E10D2D...13684, D6C8F4...10302). Voir git diff rotation.py. WORKING TREE SALE — RIEN N'EST COMMITTÉ.

### Next Move
1. Attaquer la prochaine source de diffs rotation: 20260610-212627 (27), 20260625-215943 (25), 20260526-202841 (23), 20260718-154555 (21), 20260712-203400 (20). NB: 20260625 a l'origine CORRECTE (delta=0) mais échoue quand même — cause différente (casts manqués/pivot, pas l'origine).
2. Retrouver/redécouvrir le "pivot fix" (casts manqués/étourdis) dans l'ancienne branche rules-engine-flatten-casts (commit mentionnant "weapon").
3. Quand le diff est satisfaisant: committer proprement les changements (verifier DCO Signed-off-by, linear history, PR requis — pas de push direct sur main).

### Fichiers clés
- libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py: _extract_evtc2025_metadata (≈1982), _iter_fights (≈1704), EVENT_SIZE=64, _EVENT_STRUCT_2025, offsets.
- libs/gw2_core/src/gw2_core/models.py: class EvtcHeader (≈163) — extra="forbid", champs gw2_build/map_id/arc_revision/duration_ms + CHAMP start_time_ms AJOUTÉ.
- libs/gw2_analytics/src/gw2_analytics/ei_compare.py: compare_elite_insights (≈218), _slice_bounds (196), origin (~244), rotation comparison (567-596).
- libs/gw2_analytics/src/gw2_analytics/rotation.py: build_skill_rotation (signature ~303, origin fallback ~321).
- Fichiers de mesure: .tooling/ei_diff.py ET scripts/ei-parity/ei_diff.py. Outputs: /tmp/opencode/ei_now.json (baseline, 416 rot/1108 total), /tmp/opencode/ei_sc9.json (378 rot/1012 total).
- validation métier: statechange 9 = CBTS_START (log start), statechange 10 = END; dwell sur le fait que metadata renvoie {} sur certains logs donc start_time_ms peut être None → fallback min() intact.

---

## 2026-08-05 — Diagnose offset d'origine rotation vs EI

Document ID: `ZoKhAoqJB9SP9gN9czb5YE`

### Objectif
Atteindre la parité rotation (players.rotation) entre notre build_skill_rotation et GW2EI sur le corpus WvW (35 logs, corpus.txt, EI outputs dans .tooling/ei-out/*_detailed_wvw_kill.json). Métrique canonique = nombre de buckets où liste attendue OU réelle non-vide (comparaison par égalité exacte de listes). Baseline main = 424 diffs rotation → 416 après ajout de 11 entrées de mapping (dont 14410, 31187, 62758, 30435...).

### État du travail (fait / en cours / bloqué)
- FAIT: Capture baseline à /tmp/opencode/ei_baseline_main.json. 34/35 logs passent; 3 logs échouent: 20260118-020548 (17), 20260708-215736 (29), 20260625-215943 (26).
- FAIT (cette session): Diagnostic d'alignement par weapon-swaps (skill_id==-2) entre nos temps rotation et les castTime EI, par log, via meilleur shift global. RÉSULTAT CLÉ:
  - La plupart des logs: best_shift=0 (origines alignées). Ex: 20260118 → shift=1 (254/255 swaps match), 20260708 → shift=1 (76/76 match), 20260526 → shift=1 (149 match). Les 3 logs qui échouent au baseline incluent exactement ces logs à shift=+1ms.
  - Quelques logs ont des swaps manquants (notre count > EI count): 20260409 (our=10, ei=6), 20260519 (16/13), 20260316 (16/12), 20260506 (163/160), 20260718 (143/132) — suspecte casts manqués/état au début (clamped at origin, or skills consumables non-filtrés).
- EN COURS: Vérifier que la théorie "origine EI = min(e.time_ms) - 1ms sur ces logs" est confirmée; la correction = décaler l'origine de +1ms (ou corriger le point d'ancrage) pour les logs shift=+1.
- BLOQUÉ/NON-COMPRIS: Pourquoi EI n'émet pas tous les swaps que nous émettons (manquants -2). Et le "pivot fix" (cast stack, casts manqués/étourdis) n'a PAS été retrouvé — chercher dans l'ancienne branche rules-engine-flatten-casts (commit mentionnant "weapon").

### Next Move
1. Confirmer la théorie d'origine: pour 20260118-020548, décaler notre timeline de +1ms (ou trouver l'origine exacte EI = premier event d'état, pas min(e.time_ms)) et re-run la diff parité → attendu: rotation buckets de ces logs passent au vert.
2. Si confirmé: implémenter la compensation d'origine uniforme dans cast.py (où origin est appliqué) OU modifier l'origine utilisée dans build_skill_rotation pour ancrer sur l'event start/statechange 9 (start_time_ms) plutôt que min(e.time_ms).
3. Puis retourner au pivot fix pour les casts manqués (chercher dans rules-engine-flatten-casts).

### Fichiers clés
- zevtc files/*.zevtc (logs bruts), .tooling/ei-out/*_detailed_wvw_kill.json (ground truth EI)
- scripts/ei-parity/corpus.txt (liste stems)
- libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py: parse() (~1600-1720), _extract_evtc2025_metadata (1975-2013, lit start_time_ms via statechange 9 mais renvoie {} sur ces logs), parse_events(), _EVENT_STRUCT_2025/2024, _parse_skill_cbtevent (~906-1000, source des events buffDamage)
- libs/gw2_analytics/src/gw2_analytics/rotation.py: build_skill_rotation (reçoit origin)
- libs/gw2_analytics/src/gw2_analytics/cast.py: où origin est appliqué à la timeline
- Ancienne branche rules-engine-flatten-casts (commit mentionnant "weapon") : détient probablement le pivot fix

### Notes de décision
- Méthode de mesure des offsets: pour chaque log, comparer sorted(our_swaps) et sorted(ei_swaps), chercher le shift global qui maximise l'intersection des temps. shift=0 dominant; shift=+1 sur les 3 logs fautifs.
- On a déjà les events buff buffGain (51664:14410, 32931:31187...) émis correctement en COUNT; le problème des 5 entries neutres (31187, 30435, 62758, 76783, 24305) = les logs où elles apparaissent ont le décalage +1ms → tout décalé, jamais match. Corriger l'origine devrait les convertir en wins.

---

## 2026-08-05 — Réduction des discrepancies rotation (oracle probe_candidates)

Document ID: `8aksEwEww4xyQzJajES6C9`

### Objectif
Réduire `players.rotation` (424 diffs) du comparateur EI sur le corpus 35 logs en complétant les tables d'instants de `rotation.py` à partir du code source EI.

### État du travail
**FAIT (trouvaille majeure de la session)**
- Découvert que `ei_compare.compare_elite_insights` compare `players[X].rotation` par **égalité EXACTE de listes** (`expected_casts != actual_casts` à ei_compare.py:596). Une seule ms de différence fait compter tout le bucket comme diff. La métrique canonique = nb de buckets `rotation` avec expected OU actual non vide (NON la somme des casts — mes analyses précédentes « sum of casts » étaient trompeuses).
- Le vrai levier = faire correspondre des listes complètes par-log. Oracle scripté `scripts/ei-parity/probe_candidates.py` : parse chaque log une fois, patch chaque entrée candidate à chaud, mesure le delta canonique exact.
- **Résultat : 424 → 416** (strictement -8, mesuré via ei_diff.py --json ei_v2.json). Aucune régression.
- Entrées qui GAGNENT (delta négatif) : `_BUFF_GAIN_CASTS` 9422:9422 (-1), 76507:5635 Arcane Echo (-1) ; `_DAMAGE_CASTS` 13907:50 (-1) ; `_INSTANT_CASTS_BY_EFFECT` D6C8F406E4DEE04AB16A215BE068E910:10302 Feedback (-2), E10D2D0DF7803146A69BBB5BD47944FC:13684 Lesser Symbol of Protection large variant (-2) ; + 51664:14410 Signet of Fury déjà validé (-1). Total = 424-8.
- Entrées NEUTRES (delta +0, inertes sur corpus, mais correctes selon le source EI) : `_BUFF_GAIN_CASTS` 32931:31187 Dash, 62931:62758 Flame Wheel, 29502:30435 Berserk ; `_DAMAGE_CASTS` 76783:75, 24305:50. Conservées car conformes aux finders EI.
- Timing : pour 31187 sur log 20260118 (Daredevil), nos 56 applies de 32931 = les 56 casts EI, mais décalés de **+1ms uniforme** (origine log différente) → bucket reste diff malgré le compte exact.

### Next Move
- (optionnel) Investiguer le décalage de temps +1ms : `origin = min(e.time_ms)` dans rotation.py vs origine EI ; `_slice_bounds`/`origin` dans ei_compare.py:196-208. Si corrigeable, 31187/30435/62758 deviendraient des wins réels.
- Puis attaquer `players.buffUptimes.uptime` (363) et les autres buckets restants.

### Fichiers clés
- `libs/gw2_analytics/src/gw2_analytics/rotation.py` : tables modifiées (51664:14410, 32931:31187, 62931:62758, 9422:9422, 29502:30435, 76507:5635, 76783:75, 24305:50, 13907:50, D6C8F406...:10302, E10D2D0D...:13684).
- `scripts/ei-parity/probe_candidates.py` : oracle des candidats (nouveau, non commité ?).
- `/tmp/opencode/ei_v2.json` + `ei_v2_stdout.txt` : résultat 416.
- `/tmp/opencode/ei_baseline_main.json` : baseline 424.
- `/tmp/opencode/extract_finders.py` + `ei_finders_full.txt` : 443 finders EI.
- `libs/gw2_analytics/src/gw2_analytics/ei_compare.py:596` : comparaison exacte.

### Notes de décision / Diffs
- Le commit est en cours : rotation.py modifié avec les 11 entrées (git diff 1 fichier). Vérifier `git status`/`git diff` avant commit éventuel (aucun commit fait automatiquement).
- La métrique « nb de casts expected/actual » est INADÉQUATE : la vraie métrique est le compte de buckets canoniques.

---

## 2026-08-05 — Setup corpus + état de parité (rotation/buffUptimes/consumables)

Document ID: `z7GxtJpGjN6M5UTHR41N3V`

### Objectif
Réduire les écarts de parité restants vs Elite Insights sur le corpus 35 logs. Main local @ e1d69fe = origin/main = le plus avancé (contient #115 rotation gaps, #116 engineer kit, #117 Regen buffUptime, #120 slice compare 4503→1116). Rien à récupérer des branches remote (fix/regen-*, parser-buff-uptime-parity = simples chores CI non mergés).

### État du travail
- [x] 35 logs du corpus extraits de `/home/roddy/Projects/Logs combats/Hem Oclar.zip` (10 Go) vers `zevtc files/`
- [x] 35 EI outputs `_detailed_wvw_kill.json` régénérés dans `.tooling/ei-out/` via CLI EI local (`GuildWars2EliteInsights-CLI.dll`) avec `.tooling/ei-local.conf` — NOTER : `scripts/ei-parity/ei.conf` pointe vers un chemin Mac (/Users/arthurdacquet/...), il FAUT utiliser ei-local.conf
- [x] Baseline réel post-#120 figé : **1116 différences / 35 logs**
- En cours : rotation (424), buffUptimes.uptime (363), consumables (58), connectedHits (45), downContribution/againstDownedCount (~130)

### Next Move
1. Attaquer players.rotation (424) via SkillList.json / table InstantCastFinder d'EI (compilée dans .tooling/GW2EICLI/GW2EIEvtcParser.dll/.pdb) pour compléter _INSTANT_CASTS_BY_BUFF dans libs/gw2_analytics/src/gw2_analytics/rotation.py
2. Puis players.buffUptimes.uptime (363)
3. Relancer `uv run python scripts/ei-parity/ei_diff.py --json out.json` après chaque fix
4. Réf. json baseline : /tmp/opencode/ei_baseline_main.json

### Fichiers clés
- /home/roddy/Projects/Gw2Analytics (branche main @ e1d69fe)
- scripts/ei-parity/ei_diff.py, corpus.txt, probe_rotation.py ; docs/ei-parity-workbench.md
- libs/gw2_analytics/src/gw2_analytics/rotation.py (tables instants), ei_compare.py (_slice_bounds)
- .tooling/GW2EICLI/Content/SkillList.json (10MB) + GW2EIEvtcParser.dll/.pdb
- .tooling/ei-local.conf (bon OutLocation) vs scripts/ei-parity/ei.conf (chemin Mac cassé)
- /mnt/ssd-2to = SSD 2 To monté localement (WvW logs) ; Proxmox pve01 192.168.1.10 (token 401, SSH refusé)

### Notes de décision
- 4 approches dégradantes NON retentées (consignées #122) : fenêtrage uptimes boons (225→913), soustraction 2 lectures tracker, décalage consommables +1ms (39→95), restreindre cible à 1 agent (682→3205)
- dotnet runtime local : /home/roddy/.dotnet (8.0.29) ; dotnet --version buggé mais lancement CLI OK

---

## 2026-08-04 — Clôture parité EI Regeneration buffUptimes (#117)

Document ID: `SYha2ntGmmRg1oiFFCfKDY`

### Objectif
Clore la parité EI Regeneration `buffUptimes[718]` via `BuffSimulatorDuration` + `HealingLogic` (capacity 5) dans `buff_state.py`, merger PR #117.

### État du travail
- FAIT : PR **#117 merged** (squash commit `b1fb47b`, "fix(analytics): close EI Regeneration buffUptimes parity"), branche `fix/regen-buffuptime-parity` supprimée, 3 workflows CI verts sur `pull_request` (CI 30904308297, Docker build 30904308351, Security 30904308295) + DCO.
- FAIT : bouton dur : les checks `workflow_dispatch` ne comptent PAS pour les required checks d'une PR → le `statusCheckRollup` reste vide et `mergeStateStatus=BLOCKED` malgré 9 checks verts. Seul un run déclenché par `pull_request` (push sur branche / reopen) compte. Appris : pousser un commit vide (`git commit --allow-empty -m "chore(ci): trigger..."`) pour forcer le synchronize.
- FAIT : DCO check exige un trailer `Signed-off-by` sur TOUS les commits de la PR (pas seulement le head) → rebase `--signoff origin/main` sur les 11 commits.
- FAIT : bump `cryptography>=50,<51` dans `pyproject.toml:76` (CVE-2026-69247/8/9 sur 48.0.1).
- EN COURS : le dernier diff de parité (joueur `Ovalkvadratcylinder.9365`, log 20260125-001308) reste : 52.751 EI attendu vs 52.791 (1 seul diff sur 13 totaux, 12 = `players.rotation`).

### Next Move
1. Finir le dernier diff regen : tracer le joueur 9365 (`_probe_raw` sur 718) vs EI, regénérer `ei.py` depuis /tmp/ei-src si besoin pour isoler le cas.
2. Soumettre le correctif restant sur `main` (branche `fix/` + PR avec commit vide si CI ne se déclenche pas).

### Fichiers clés
- `libs/gw2_analytics/src/gw2_analytics/buff_state.py` (branche regen ~ligne 314, PLR5501 corrigé) — porté + mergé.
- `libs/gw2_core/src/gw2_core/models.py:494/531` : `BoonApplyEvent` + `added_active: bool`.
- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py:1168` : `added_active=bool(is_shields)`.
- `/tmp/v3_tmp.py` : port de référence exact. `/tmp/ei-src` : sources EI (`HealingLogic.cs`, `QueueLogic.cs`, `BuffApplyEvent.cs`).
- `scripts/ei-parity/ei_diff.py`, `.tooling/ei-out/<stem>_detailed_wvw_kill.json`, `SESSION.md`.

### Notes de décision / IDs
- CI branche : ne se déclenche pas automatiquement sur push de branche (sauf PR sync) ; forcer via commit vide. Check runs `pull_request` seulement.
- Règles repo : 9 required checks + DCO (Signed-off-by tous commits) + linear history + non-fast-forward. Push direct `main` refusé → toujours passer par PR.
- PR : https://github.com/Roddygithub/Gw2Analytics/pull/117 (merged b1fb47b).

---

## 2026-08-03 — continuation: port EI sim + découverte divergence

Document ID: `iyEYDdopixUtcJNxjTiDWu`

### Objectif
Parité totale EI v3.26.0.0 : 0 diff sur corpus 12 logs WvW. État 156 diffs (116 rotation / 39 buffUptimes / 1 downCount).

### Fait dans cette continuation
- **Construit `eisim.py`** : port fidèle Python de EI HealingLogic + BuffSimulatorDuration + BuffStackItem : `/tmp/eisim.py` (StackItem, HealingLogic, Sim class).
- **Résultat critique** : `eisim` donne EXACTEMENT le même résultat que notre tracker actuel pour Babba (20260429-232621) :
  - eisim Babba regen uptime: **55.251%**
  - Our tracker Babba regen uptime: **55.251%**
  - EI expected reference: **71.922%**
- **Notre modèle est cohérent mais diverge de 16.7% vs EI** → le flux d'événements ou la sémantique des événements que nous feedons diffère de ce que EI feed à son sim.
- **CommonBuffs.cs** : Regeneration skill 718 a DEUX définitions : `BuffStackType.Queue` (pre-Feb2018, l.19) et `BuffStackType.Regeneration` (post-Feb2018, l.21). Modern WvW → **HealingLogic**. Confirmé.
- EI `StateChange.BuffInitial` (18) = `BuffApplyEvent.Initial = true`. Notre parser émet `BuffApplyEvent` pour is_statechange==18 avec `added_active=bool(is_shields)` — potentiellement l'initial snapshot n'est pas correctement lié au sim (initial = stack pré-existant avant le début du log).
- `BuffRemoveAllEvent` : IsBuffSimulatorCompliant hérité de AbstractBuffRemoveEvent — faut vérifier si il hérite du filtre `BuffRemoveSingleEvent` ou a sa propre compliance. Les remove_all avec src=0 pourraient être filtrés par EI (éliminant des clears qui enlèvent de l'uptime).
- **EI `compare_healing`** : tri du root seedSrc pour `_healing` (l'agent record), qu'on lit correctement.
- **Agents** : 172 agents, Babba id 15113 inst_id 4534 (single)

### Next Move (priorité)
1. Lire l'EI reference JSON complet pour Babba (`.tooling/ei-out/20260429-232621_detailed_wvw_kill.json`) → comparer buffUptimes per source, activeTimes, initial buffs.
2. Vérifier si EI traite le BuffApplyEvent **Initial** (is_state_change == 18) comme précurseur avec un délai de déduction de durée déjà consommée. Notre tracker le traite comme n'importe quel apply — divergence possible.
3. Vérifier `BuffRemoveAllEvent.IsBuffSimulatorCompliant` dans EI (hérité de `AbstractBuffRemoveEvent` ? Filtre IFF ?). Si EI ignore uncredited remove_all... et notre tracker les exécute → on clear plus souvent que EI → on sous-estime (exactement Babba => 55 vs 72%).

### Fichiers clés
- /tmp/eisim/ (nouveau)
- .tooling/ei-out/20260429-232621_detailed_wvw_kill.json (référence EI)
- Tous les autres comme ci-dessus (résumé précédent, memory précédent)
- EI : BuffApplyEvent.cs l.19, l.39, AbstractBuffApplyEvent l.13, BuffRemoveAllEvent.cs, CombatItem.cs
- GW2 libs/gw2_analytics/src/... (compare, parser)

### Notes décision
- Important : `Remove.Single` ne s'applique pas à no (0 events relevant dans Babba log). Donc le fix remove_single n'a pas d'effet.
- Important : les two `eisim` et tracker produisent le MÊME résultat pour Babba (55.251%), ce qui prouve que notre modéliseur logique est fidèle — le problème est DANS LES ÉVÉNEMENTS OU LA LECTURE D'ÉVÉNEMENTS initiaux.
- `État `_noSort` global** : vérifié comme identique à EI (static Logic, per parse, modifié lors de BuffStackActive).
- `Healing` valeur: ordre dans `eisim` utilisé sort par `seedSrc.healing` identifié comme `compare_healing` EI — tous les scores sont 0 pour Babba? Vérifié — Babba healing = 0, mais SOURCES healing diffère de 0 selon... le `eisim` Sort reste op à zéro scores → `stacks.Last()` = hash-based insertion (stable). Ça peut causer écarts.

### Probes restantes
- `/tmp/test_babba_sim.py` top adapté `parse_events` — correct. Run UV (taille ~105109ms).
- Prendre `.tooling/ei-out/20260429-232621_detailed_wvw_kill.json` pour déboguer les `activeTimes`, `buffUptimes` de EI sur Babba.
- Vérifier `BuffRemoveAllEvent` héritage spec EI (filtre IFF).

---

## 2026-08-03 — Résumé de session (suite diagnostic regen)

Document ID: `JJzj6mpJ4HtEPPbzNfD9jF`

### Objectif
Parité totale EI v3.26.0.0 : 0 diff sur le corpus 12 logs WvW. État actuel 156 diffs (116 rotation / 39 buffUptimes / 1 downCount). Cible courante : regen uptime (39 diffs, changés par aucun fix jusqu'ici).

### État du travail
- FAIT : Constantes EI résolues (/tmp/ParserHelper.cs, tag v3.26.0.0) : ServerDelayConstant=10, BuffSimulatorDelayConstant=15, BuffSimulatorStackActiveDelayConstant=50. Notre tolérance < 15 ms déjà conforme.
- FAIT : `AddRegen` (BuffDictionary.cs:97-119) est du code MORT dans v3.26.0.0 — AUCUN appelant dans tout l'arbre. Donc `OverridenRegenInstance`/`OverridenRegenDuration` ne se déclenchent jamais → l'éviction EI en cas de file pleine est TOUJOURS `stacks.Last()` (HealingLogic.FindLowestValue, le code override ne sert jamais). Théorie "override pairing" invalide — ne peut pas expliquer Babba/Peixa.
- FAIT : EI NoID Remove.Single = match par DURÉE SEULEMENT, premier dans l'ordre de liste, ignore stack_id (`abs(removedDuration - TotalDuration) < 15`).
- FAIT : EI filtre les remove_single overstack/natural-end pour sims NoID : `BuffRemoveSingleEvent.IsBuffSimulatorCompliant` (BuffRemoveSingleEvent.cs:26-38) = false si IFF==Unknown && CreditedBy unknown && dstAgent==0 (`OverstackOrNaturalEnd`). Notre parser miroite ça à parser.py:1105 (`is_evtc_2025 and is_buffremove != 1 and _iff == 2 and dst_agent == 0`). IFF: Friend=0, Foe=1, Unknown=2 (ArcDPSEnums.cs:618).
- FAIT : **DÉCOUVERTE CLÉ** — le log Babba (20260429-232621) a ZÉRO événement regen `remove_single` ; seulement `remove_manual` (16) et `remove_all` (52). Notre tracker ne gère que `kind == "remove_single"` ; `remove_manual` tombe dans le vide = ignoré = **CONFORME à EI** (BuffRemoveManualEvent.IsBuffSimulatorCompliant retourne false, EI ignore aussi CBTB_MANUAL=3). Donc le fix remove_single ne pouvait RIEN changer (les events n'existent pas) — cela explique pourquoi act6 = act5 à l'identique (39 diffs, zéro CHANGED).
- FAIT : StackingLogic.cs : IsFull = stacks.Count == capacity (pas >=). QueueLogic.Add = append + Sort (no-op). HealingLogic : extends QueueLogic. BuffSimulator.Add : si full → FindLowestValue (false → OverstackSimulationResult) ; si addedActive → Activate (move front).
- FAIT : BuffSimulator.Remove (BuffSimulator.cs:86-110) : Remove.All → waste tous + clear ; Single → durée-only match.

### Next Move
La divergence des 39 uptimes ne vient PAS de remove_single ni de remove_manual (les deux conformes). Reste à tester : (1) la sémantique de `TotalDuration` décrémenté (EI décrémente les stacks actifs via Update(timePassed), notre `expirations` stocke des temps absolus — vérifier si la comparaison d'éviction/removal est comparable), (2) le chemin `addedActive`/Activate (move-to-front) et le noSort, (3) extension handling. Prochain pas concret : instrumenter Babba/Peixa — dump la séquence regen apply/remove_all + notre expirations vs simulation EI attendue, trouver où notre COUNT/expiry diverge d'EI. Ensuite re-run corpus, viser Peixa/Babba vers 0 sans régresser okami/Meril/Bergmann.

### Fichiers clés
- libs/gw2_analytics/src/gw2_analytics/buff_state.py — BuffStateTracker, _REGEN_NO_SORT, handlers BoonApply ~318-370, remove_single ~371-405, _process_buff_apply ~405-460.
- libs/gw2_analytics/src/gw2_analytics/ei_compare.py — BuffStackActiveEvent forwardé, clés JSON `players[<name>.<id>].buffUptimes.uptime`.
- libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py — filtre IFF l.1105, _CBTBUFREMOVE_KINDS l.343-347 (remove_all/remove_single/remove_manual).
- EI /tmp/ei-v3/GW2EIEvtcParser/ : BuffDictionary.cs (AddRegen mort), BuffSimulatorNoID/ (HealingLogic.cs, QueueLogic.cs, BuffSimulator.cs, StackingLogic.cs), BuffRemoves/BuffRemoveManualEvent.cs (compliant=false), BuffRemoves/BuffRemoveSingleEvent.cs:26-38.
- Dumps : /tmp/after_active4_full.json (159), after_active5_full.json (156), after_active6_full.json (156), baseline.json.
- Probe : /tmp/probe_regen.py.

### Notes décision / Diff
- act5 = append→replace-last (fix éviction) : a amélioré okami/Bergmann/Meril, régressé Peixa (-9.8) Babba (-16.7). act6 = +remove_single durée-first : identique à act5. Le levier n'est PAS là.
- Run : stems=$(ls "zevtc files" | grep '\.zevtc$' | sed 's/\.zevtc$//') && uv run python scripts/ei-parity/ei_diff.py --json /tmp/<out>.json $stems
- Tests : libs/gw2_analytics/tests/test_buff_state.py (66, pass).

---

## 2026-08-02 — cause racine buffUptimes établie

Document ID: `xLAesErg2jkYYQzccLPFb6`

### Objectif
Parité totale EI v3.26.0.0 : 0 diff sur le corpus 10 logs WvW. Baseline actuelle 158 diffs (115 rotation + 42 buffUptimes + 1 defenses.downCount).

### Découverte clé (cause racine 42 buffUptimes)
- Pour les buffs de DURÉE (Queue/Regeneration), l'uptime EI = PRÉSENCE (union du temps où ≥1 stack est actif), pas la somme des durées.
  - Preuve : ViV.9421 protection 717, log 20260702-185809. EI `uptime: 88.454` = 98146ms / 110956ms (phase), `states` = [[0,0],[1,1],[98146,0]] = présence continue de t=1 à 98146.
  - Σ `generated` par source EI = 58.109+9.339+5.404+1.521+3.924+4.867+5.29 = 88.454 (dans ce cas = présence car pas de chevauchement).
  - GetUptime (BuffDistribution.cs) = Σ Value par source ; Value = durée où le stack FRONT (BuffStack[0]) est actif, item BuffSimulationItemDuration, active stacks = 1.
- Notre tracker actuel (`buff_state.py`, path `max_stacks==1`) = FIFO-chaîne capacité 99 : `expirations` chaînées séquentiellement, cumulative = somme → ~99.999% systématiquement quand les applies se chevauchent. C'est FAUX.
- L'union brute des intervalles (t, t+dur) sur ViV donne 62.587% (69444ms) — NI somme (114435ms→103%) NI présence EI (88.45%). Donc `duration_ms` de nos BoonApplyEvent ne reproduit pas la présence EI : les `BuffStackActiveEvent` (33 pour ViV) et la logique de file (front qui change) prolongent la présence au-delà des (t,t+dur) simples.
- Vérifié : aucun (t+dur) de ViV ne tombe à 98146 → la présence EI dépend du mécanisme d'activation des stacks (BuffSimulatorDuration.Update + QueueLogic.Activate qui met le stack en position 0, délai ParserHelper.BuffSimulatorStackActiveDelayConstant = 50ms).

### Sémantique EI no-ID (WvW, UseBuffInstanceSimulator = false confirmé CombatData.cs:611)
- Simulateur par buff : BuffSimulatorDuration pour durée, BuffSimulatorIntensity pour intensité.
- QueueLogic (capacité 5 pour Protection/Régénération/Resolution/Resistance/Quickness/Fury/Vigor/Swiftness per CommonBuffs.cs) : `Add` append, si full remplace le stack non-front avec la plus courte TotalDuration → Waste ; `Activate` = move stackItem en position 0.
- `Value` (uptime) = temps où BuffStack non vide, crédité au Src du front.
- `Wasted` = temps des stacks remplacés (ViV protection : Schmusekætzchen 6.291, Ess Kape 3.893, Roger I Rabbit 1.947, Colmyllo 1.721, Semtäx 0.541, Krataxx 0.288).
- `Overstacked` == `generated` pour ViV (peut-être double-count dans l'export).

### État du travail
- Fait : PR #114 (a1dd3d0), #115 (2304cf7, rotation 163→120), #116 (76bfa34, 158 total, 115 rotation) mergés. Git GPG signé.
- En cours : cause racine buffUptimes établie (voir ci-dessus). 42 diffs concentrés : 28×Regeneration (718), 4×Protection (717), 2×Resolution (873), 2×Resistance (26980), Fury/Might/Swiftness/Quickness/SuperSpeed/Stability ×1. Log 20260702-185809 = gros deltas positifs.
- Bloquer : diffusion des 4 sous-agents de recherche aborted ; 1 defenses.downCount (Ever.6173, log 20251022, expected 2/actual 1, EI DefenseAllStatistics.cs DownCount = count BuffApplyEvent Downed).

### Next Move
1. Comprendre comment BuffStackActiveEvent + la file EI prolongent la présence au-delà des (t,t+dur) — instrumenter le flux EI (ou reproduire BuffSimulatorDuration en Python) sur ViV protection pour obtenir 98146ms.
2. Refonte `buff_state.py` : remplacer FIFO-chaîne cap 99 par simulation file EI (cap 5, front actif, activate via BuffStackActiveEvent, remplacement du plus court restant → waste).
3. Rédiger dossier Supermemory complet : defenses (compter BuffApplyEvent Downed), buffUptimes (refonte file), rotation (classer 115 écarts par skill + InstantCastFinder EI).
4. Déclencher GPT-5.5 avec validation : tests + Ruff + corpus avant/après.

### Fichiers clés
- libs/gw2_analytics/src/gw2_analytics/buff_state.py (à refondre)
- libs/gw2_analytics/src/gw2_analytics/ei_compare.py (l.355 aliases, l.462 min(100), l.489 seuil 0.005)
- /tmp/opencode/GW2-Elite-Insights-Parser/GW2EIEvtcParser/EIData/Buffs/BuffSimulators/BuffSimulatorNoID/BuffSimulatorDuration.cs, BuffSimulator.cs, EffectStackingLogic/QueueLogic.cs
- /tmp/opencode/GW2-Elite-Insights-Parser/GW2EIEvtcParser/EIData/Buffs/BuffDistribution.cs (GetUptime)
- /tmp/opencode/GW2-Elite-Insights-Parser/GW2EIEvtcParser/EIData/Buffs/BuffSimulators/BuffSimulationItems/BuffSimulationItemDuration.cs
- Probes: /tmp/opencode/probe_union.py (union brute 62.587%), probe_viv*.py
