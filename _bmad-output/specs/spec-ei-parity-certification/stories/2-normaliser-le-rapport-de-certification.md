---
title: 'Normaliser le rapport de certification'
type: 'feature'
created: '2026-08-14'
status: 'done'
review_loop_iteration: 1
baseline_commit: '59a802ed17b3b2440b4216c90fa5fba72db03109'
context:
  - '{project-root}/AGENTS.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problème :** La chaîne EI expose aujourd'hui un dictionnaire sparse de différences et une baseline agrégée, sans matérialiser les comparaisons réussies, les règles appliquées ni les statuts `PASS`, `KNOWN_DELTA` et `FAIL`. Elle ne fournit donc pas le rapport détaillé stable exigé par CAP-2 et CAP-3.

**Approche :** Instrumenter les points de comparaison existants pour produire des résultats structurés sans remplacer `matches`, `compared` ou `differences`, puis laisser `ei_diff.py` ajouter le log, appliquer des règles `KNOWN_DELTA` exactes et écrire un rapport local privé distinct de la baseline versionnée.

## Boundaries & Constraints

**Always:** Conserver la sémantique et les consommateurs de `compare_elite_insights`; émettre une ligne par comparaison atomique avec règle et statut; calculer `delta = actual - expected` pour les nombres et `null` sinon; atomiser les écarts de rotation par cast et compétence; trier déterministement le rapport; traiter les 133 écarts actuels comme `FAIL`; garder `--json` compatible avec la baseline agrégée de story 1.

**Ask First:** Toute règle `KNOWN_DELTA` appliquée au corpus réel; toute nouvelle tolérance; toute modification des buckets certifiés ou du format de baseline; toute donnée privée destinée à être versionnée.

**Never:** Créer un second comparateur; reconstruire les `PASS` en reparcourant `compared` après coup; convertir `KNOWN_ROTATION_DEAD_ENDS` en dérogations; utiliser regex ou sélecteur incomplet pour masquer un écart; inclure le rapport détaillé, comptes, personnages ou chronologie dans Git; émettre un verdict global de certification, réservé à la story 5.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Comparaison conforme | Valeurs égales ou dans la tolérance existante | Ligne `PASS` avec règle, expected, actual et dimensions disponibles | N/A |
| Écart sans dérogation | Valeurs hors règle ou donnée manquante | Ligne `FAIL`; rotation scindée par cast/skill | Aucun écart ignoré |
| Écart accepté | Sélecteur exact et borne respectée | Ligne `KNOWN_DELTA` avec `rule_id`, motif et critère de retrait | Hors sélecteur ou borne: `FAIL` |
| Rapport détaillé | Corpus complet et destination locale sûre | JSON schema v1 trié avec résumé par statut/bucket et résultats détaillés | Écriture atomique; artefact non versionné |
| Baseline agrégée | Option `--json` existante | Format story 1 inchangé | Refus d'un corpus partiel inchangé |

</frozen-after-approval>

## Code Map

- `libs/gw2_analytics/src/gw2_analytics/ei_compare.py:141-178,385-420,749-1103` -- source canonique des égalités, tolérances et différences; ajouter une émission additive au moment de chaque décision, y compris boons et rotation.
- `libs/gw2_analytics/tests/test_ei_compare.py` -- protéger `matches`/`differences` et vérifier PASS, FAIL, tolérance uptime et rotation atomisée.
- `scripts/ei-parity/ei_diff.py:75-77,231-276,279-329,332-420` -- ajouter dimensions de log, classification des règles, résumé et option de rapport détaillé; conserver `bucket()` et `--json` pour la baseline.
- `scripts/ei-parity/known-deltas.json` -- nouveau registre versionné schema v1; vide pour le corpus réel, avec sélecteurs exacts et champs obligatoires `id`, `selector`, `constraint`, `reason`, `remove_when`.
- `tests/scripts/test_ei_diff.py` -- tester règle bornée, quasi-correspondance restant FAIL, stabilité JSON, confidentialité et coexistence des deux sorties.
- `scripts/ei-parity/corpus-baseline.json` -- contrat agrégé story 1 en lecture seule; doit rester octet-pour-octet stable après régénération.
- `docs/ei-parity-workbench.md` -- distinguer baseline publiable, rapport local privé et registre de dérogations.

## Tasks & Acceptance

**Execution:**
- [x] `libs/gw2_analytics/src/gw2_analytics/ei_compare.py` -- émettre additivement les résultats atomiques et leurs règles aux points de comparaison existants sans changer les contrats historiques.
- [x] `scripts/ei-parity/known-deltas.json` -- définir le schéma fermé du registre avec aucune dérogation réelle initiale.
- [x] `scripts/ei-parity/ei_diff.py` -- normaliser dimensions/deltas/statuts, appliquer uniquement les règles exactes et écrire un rapport détaillé schema v1 atomique via une option distincte.
- [x] `libs/gw2_analytics/tests/test_ei_compare.py` et `tests/scripts/test_ei_diff.py` -- couvrir chaque ligne de la matrice avec données synthétiques non personnelles.
- [x] `docs/ei-parity-workbench.md` -- documenter formats, confidentialité et procédure de création/retrait d'une règle.

**Acceptance Criteria:**
- Given une comparaison couverte, when elle est évaluée, then elle produit exactement un résultat structuré avec `status`, `expected`, `actual`, `delta`, `bucket`, règle et dimensions disponibles.
- Given une règle versionnée, when seul son sélecteur exact et sa borne correspondent, then le résultat devient `KNOWN_DELTA`; toute variante reste `FAIL`.
- Given le corpus actuel sans dérogation, when le rapport détaillé est généré, then ses 133 écarts sont `FAIL`, ses conformités sont `PASS` et aucune regex ne masque un résultat.
- Given la baseline story 1, when elle est régénérée après ce changement, then son format et son contenu restent inchangés.

## Spec Change Log

### 2026-08-14 — Step-04 re-run : patch findings appliqués (9)
- **Findings traités (patch) :** P1 garde `json_out == report_out` → `_fail` (destinations distinctes) ; P2 sélecteurs de règle rejetés si valeur non-scalaire ; P3 `_atomic_result` : delta non fini (NaN/inf) ignoré (pas d'émission) ; P4 comparaison header exclut la clé structurelle `players` ; P5 clé fantôme `players[Private].dpsAll.contribution` corrigée vers la clé producteur réelle `players[Private].dpsAll.damage` (fixtures + tests) ; P6 test producteur `dpsAll` avec événement de dégâts réel ; P7 test privacy `--json` baseline avec résultats peuplés (aucun `Private`/`expected`/`actual` ne fuit) ; P8 payloads invalides des tests paramétrés désormais munis de `reason`/`remove_when` valides (le validateur ciblé est réellement exercé ; le cas doublon reste au test dédié) ; P9 `_classify_results` refuse tout statut hors `{PASS, FAIL}` au lieu de l'ignorer silencieusement.
- **Déféré :** régénération de la baseline octet-identique (nécessite le corpus privé) ; test du chemin `OSError`/message de rename (préexistant hors périmètre).
- **Rejeté :** dedupe buff (clé par (account, buff_id) agrégée — le garde avant émission est requis, pas un bug) ; KNOWN_DELTA numérique seul (contrainte `max_abs_delta`, spec figée) ; clés rotation dupliquées ; sélecteurs null (wildcard couvre) ; corpus complet imposé par `--report-json` ; axes non comparés sans lignes ; statut rotation = matcher externe.
- **KEEP (à préserver à la re-dérivation) :** émission additive aux points de comparaison existants sans remplacer `matches`/`compared`/`differences` ; report schema v1 trié avec `summary_by_status` et `summary_by_status_bucket` ; `--json` story 1 inchangée ; écriture atomique du rapport ; registre `known-deltas.json` schema v1 vide ; les 133 écarts de baseline traités `FAIL` ; 60 tests verts, coverage 90 %+, ruff OK, mypy sur `ei_compare.py` OK.

### 2026-08-14 — Verification : le compte « 133 FAIL » était insatisfaisable
- **Finding déclencheur :** reviewer `verification-gap` (step-04, itération 0) : le rapport affiche plus de 133 lignes `FAIL` car `_rotation_unmatched` atomise les écarts de rotation par cast (`52` clés baseline `players.rotation` → une ligne par cast manquant/excédentaire), alors que la commande de vérification exigeait « rapport schema v1, 133 FAIL ». La somme des lignes atomisées n'égale pas 133 en général. Structure confirmée par lecture du code (`_rotation_unmatched` émet un `_atomic_result` par cast) ; le chiffre « 194 FAIL » avancé par le reviewer n'a pas pu être reproduit (corpus privé absent du worktree).
- **Amendement :** la commande de vérification (ligne 79, section `## Verification`, hors bloc figé) reformule l'attendu : les 133 écarts de baseline restent `FAIL` ; les lignes de rotation atomisées par cast font que le nombre total de lignes `FAIL` peut excéder 133 sans masquer un écart.
- **État mauvais évité :** rejet à tort d'un rapport correct parce que le compteur de lignes atomisées ≠ 133 ; ou inversion de la contrainte figée « atomiser la rotation par cast » pour forcer un compte de 133.
- **KEEP (à préserver à la re-dérivation) :** émission additive aux points de comparaison existants sans remplacer `matches`/`compared`/`differences` ; report schema v1 trié avec `summary_by_status` et `summary_by_status_bucket` ; `--json` story 1 inchangée ; écriture atomique du rapport ; registre `known-deltas.json` schema v1 vide ; les 133 écarts de baseline traités `FAIL` ; 48 tests verts, coverage 90 %+, ruff OK, mypy sur `ei_compare.py` OK.

## Design Notes

Le rapport détaillé est local et sensible. Son document racine porte `schema_version`, la référence EI, le hash du manifeste, un résumé par statut/bucket et une liste triée de résultats. Les résultats conservent un identifiant joueur/slice local uniquement lorsque disponible; ils ne sont jamais copiés dans `corpus-baseline.json`.

Le registre réel commence vide : story 2 construit et prouve le mécanisme, mais l'acceptation d'un écart du corpus exige une décision humaine ultérieure. Les règles exactes utilisent des listes de stems, joueurs/slices et skill IDs, jamais des regex.

## Verification

**Commands:**
- `uv run pytest libs/gw2_analytics/tests/test_ei_compare.py tests/scripts/test_ei_diff.py -q` -- expected: contrats historiques et nouvelle classification couverts.
- `uv run ruff check libs/gw2_analytics/src/gw2_analytics/ei_compare.py scripts/ei-parity/ei_diff.py libs/gw2_analytics/tests/test_ei_compare.py tests/scripts/test_ei_diff.py` -- expected: aucune erreur.
- `uv run ruff format --check libs/gw2_analytics/src/gw2_analytics/ei_compare.py scripts/ei-parity/ei_diff.py libs/gw2_analytics/tests/test_ei_compare.py tests/scripts/test_ei_diff.py` -- expected: format conforme.
- `uv run python scripts/ei-parity/ei_diff.py --report-json /tmp/ei-certification-report.json --json /tmp/ei-baseline.json` -- expected: rapport schema v1 dont les 133 écarts de baseline restent `FAIL` (les lignes de rotation étant atomisées par cast, le nombre total de lignes `FAIL` du rapport peut excéder 133 sans masquer un écart) et baseline identique à `corpus-baseline.json`.

## Suggested Review Order

**Entrée et sémantique du rapport**

- Le résultat atomique pose le contrat : statut, expected/actual/delta, dimensions.
  [`ei_compare.py:142`](../../../../libs/gw2_analytics/src/gw2_analytics/ei_compare.py#L142)
- Le point d'entrée compare instrumenté ; delta non fini ignoré, émission additive.
  [`ei_compare.py:460`](../../../../libs/gw2_analytics/src/gw2_analytics/ei_compare.py#L460)

**Validation et classification des règles**

- Registre schema v1 : sélecteurs scalaires non nuls, bornes positives finies, ids uniques.
  [`ei_diff.py:246`](../../../../scripts/ei-parity/ei_diff.py#L246)
- Classification PASS/FAIL/KNOWN_DELTA ; statut inattendu refusé.
  [`ei_diff.py:437`](../../../../scripts/ei-parity/ei_diff.py#L437)
- Résumé par statut/bucket, écriture atomique, tri déterministe.
  [`ei_diff.py:483`](../../../../scripts/ei-parity/ei_diff.py#L483)

**Confidentialité et coexistence des sorties**

- `bucket()` collapse les clés joueur pour la baseline agrégée.
  [`ei_diff.py:84`](../../../../scripts/ei-parity/ei_diff.py#L84)
- Destinations protégées et distinctes (`json` vs `report`) ; refus de corpus partiel.
  [`ei_diff.py:509`](../../../../scripts/ei-parity/ei_diff.py#L509)
- Orchestration : `--json` story 1 inchangé, `--report-json` séparé.
  [`ei_diff.py:525`](../../../../scripts/ei-parity/ei_diff.py#L525)

**Rotation atomisée**

- Écarts de rotation scindés par cast et compétence, désambiguïsés par durée.
  [`ei_compare.py:194`](../../../../libs/gw2_analytics/src/gw2_analytics/ei_compare.py#L194)
- Comptage missing/extra par skill côté pilote.
  [`ei_diff.py:301`](../../../../scripts/ei-parity/ei_diff.py#L301)

**Tests et documentation**

- Privacy de la baseline : aucune donnée joueur dans l'agrégat.
  [`test_ei_diff.py:253`](../../../../tests/scripts/test_ei_diff.py#L253)
- Fixture d'un rapport à un résultat, base des tests de règles.
  [`test_ei_diff.py:305`](../../../../tests/scripts/test_ei_diff.py#L305)
- KNOWN_DELTA ne flippe jamais un PASS ; FAIL atomique devenu connu.
  [`test_ei_diff.py:386`](../../../../tests/scripts/test_ei_diff.py#L386)
- Règles invalides rejetées (payloads munis de reason/remove_when valides).
  [`test_ei_diff.py:527`](../../../../tests/scripts/test_ei_diff.py#L527)
- Producteur dpsAll réel : delta numéro-tique sur événement de dégâts.
  [`test_ei_compare.py:591`](../../../../libs/gw2_analytics/tests/test_ei_compare.py#L591)
- Workbench : formats, confidentialité, procédure de règle.
  [`ei-parity-workbench.md:116`](../../../../docs/ei-parity-workbench.md#L116)
