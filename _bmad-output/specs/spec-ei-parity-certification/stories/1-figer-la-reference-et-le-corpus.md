---
title: 'Figer la référence et le corpus'
type: 'chore'
created: '2026-08-13'
status: 'done'
review_loop_iteration: 0
baseline_commit: '553b40c73a650dadae0b48028a564a8fa7c32c0d'
context:
  - '{project-root}/AGENTS.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problème :** Le corpus EI actuel contient 35 stems, mais son exécution ignore silencieusement des références absentes et ne prouve ni l'intégrité des fichiers locaux ni la version EI ayant produit les exports. La baseline n'est pas versionnée sous une forme agrégée et non personnelle.

**Approche :** Versionner un manifeste pour les 35 couples privés, le valider avant toute comparaison dans `ei_diff.py`, puis produire une baseline complète par bucket sans détails joueur. Attester EI v3.26.0.0 par une version déclarée et l'empreinte SHA-256 du binaire CLI local utilisé.

## Boundaries & Constraints

**Always:** Conserver `corpus.txt` comme liste ordonnée canonique; exiger exactement une entrée de manifeste par stem; vérifier avant parsing la présence et le SHA-256 du `.zevtc`, de l'export EI et du binaire CLI; fixer le type `detailed_wvw_kill`, EI `3.26.0.0` et un vocabulaire fermé de tags; n'écrire dans la baseline que les compteurs agrégés des buckets normalisés effectivement observés.

**Ask First:** Toute modification du corpus de 35 stems, de la version EI, du type d'export, du vocabulaire des tags ou des buckets inclus; toute impossibilité d'attester le binaire local par empreinte.

**Never:** Déplacer, renommer ou versionner un log, un export EI ou le binaire; inclure chemin absolu, compte, personnage, `recordedBy` ou différence brute dans un artefact versionné; créer un comparateur ou un générateur de corpus parallèle; accepter le fallback ambigu `_detailed_wvw*.json` pour une exécution certifiée.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Corpus valide | 35 entrées uniques, fichiers présents, empreintes conformes | Les 35 logs sont comparés et la baseline expose les buckets observés, triés par clé | N/A |
| Fichier absent ou altéré | Couple, CLI ou SHA-256 manquant/invalide | Aucun log n'est parsé et aucun rapport trompeur n'est produit | Échec explicite nommant seulement le stem et l'artefact |
| Manifeste incohérent | Stem absent, dupliqué, supplémentaire, mauvaise version/type/tag | Exécution refusée avant comparaison | Échec explicite sans donnée privée |
| Sortie baseline | Résultats des 35 logs | JSON stable: référence, empreinte du manifeste, nombre de logs et compte par bucket | Aucun détail attendu/réel ni identifiant joueur |

</frozen-after-approval>

## Code Map

- `scripts/ei-parity/corpus.txt` -- ordre canonique des 35 stems; ne pas dupliquer cette sélection dans le code.
- `scripts/ei-parity/corpus-manifest.json` -- nouvel inventaire versionné: métadonnées non personnelles, empreintes des artefacts privés et attestation EI.
- `scripts/ei-parity/corpus-baseline.json` -- baseline agrégée versionnée produite sur les 35 logs: 133 différences dans 13 buckets normalisés.
- `scripts/ei-parity/ei_diff.py` -- preflight strict UTF-8/JSON/timestamps/empreintes avant parsing, chargement des couples et écriture atomique de la baseline; aucun fallback de référence.
- `scripts/ei-parity/ei.conf:3-15,25-28` -- preuve de configuration du type d'export détaillé WvW et timeline brute; lecture seule.
- `libs/gw2_analytics/src/gw2_analytics/ei_compare.py:385-416,403-413,749-1098` -- surface réelle des comparaisons et buckets; lecture seule pour cette story.
- `tests/scripts/test_ei_diff.py` -- nouveau test isolé sur fichiers temporaires, sans EVTC/export réel.
- `docs/ei-parity-workbench.md:19-24,40-66,79-89` -- procédure locale à mettre à jour avec validation du manifeste et génération de baseline.
- `.gitignore:130-136` et `AGENTS.md:20-25` -- garde-fous de confidentialité; les artefacts privés restent hors Git.

## Tasks & Acceptance

**Execution:**
- [x] `scripts/ei-parity/corpus-manifest.json` -- inventorier les 35 stems, dates, SHA-256 EVTC/export, version et empreinte CLI, type d'export et tags de couverture sans donnée personnelle.
- [x] `scripts/ei-parity/corpus-baseline.json` -- versionner la baseline complète agrégée des 35 logs sans donnée personnelle ni différence brute.
- [x] `scripts/ei-parity/ei_diff.py` -- charger et valider strictement manifeste, corpus et artefacts avant parsing; ajouter une sortie baseline stable des buckets observés sans différences brutes.
- [x] `tests/scripts/test_ei_diff.py` -- protéger l'alignement corpus/manifeste, les erreurs avant parsing, le contrat fermé des métadonnées et l'absence de détails privés dans la baseline.
- [x] `docs/ei-parity-workbench.md` -- documenter l'attestation EI, la vérification préalable et la commande reproductible de baseline.

**Acceptance Criteria:**
- Given les artefacts locaux correspondant au manifeste, when le corpus complet est lancé, then les 35 stems sont vérifiés puis comparés sans omission silencieuse et le JSON agrégé est reproductible.
- Given un manifeste versionné, when il est inspecté, then chaque stem de `corpus.txt` apparaît exactement une fois avec les champs requis et aucune donnée personnelle ou chemin local.
- Given la baseline produite, when elle est inspectée, then chaque bucket normalisé observé apparaît une fois avec un compteur entier et aucune différence brute n'est présente.

## Spec Change Log

## Design Notes

Le JSON d'export EI ne contient pas de preuve fiable de la release génératrice. L'attestation minimale est donc double: `ei_version: "3.26.0.0"` comme contrat humain et SHA-256 du `GuildWars2EliteInsights-CLI.dll` local comme preuve de l'artefact exécuté. La baseline doit également inclure le SHA-256 des octets du manifeste afin de lier ses compteurs au corpus exact.

## Verification

**Commands:**
- `uv run pytest tests/scripts/test_ei_diff.py -q` -- expected: contrat du manifeste et cas d'échec couverts sans artefact privé.
- `uv run ruff check scripts/ei-parity/ei_diff.py tests/scripts/test_ei_diff.py` -- expected: aucune erreur.
- `uv run ruff format --check scripts/ei-parity/ei_diff.py tests/scripts/test_ei_diff.py` -- expected: format conforme.
- `uv run python scripts/ei-parity/ei_diff.py --json scripts/ei-parity/corpus-baseline.json` -- expected: 35 logs vérifiés et baseline versionnée régénérée atomiquement avec 133 différences dans 13 buckets.

## Suggested Review Order

**Validation et sécurité**

- Le preflight bloque tout corpus incohérent avant le premier parsing.
  [`ei_diff.py:130`](../../../../../scripts/ei-parity/ei_diff.py#L130)

- L'écriture atomique protège baseline et entrées contre l'écrasement.
  [`ei_diff.py:210`](../../../../../scripts/ei-parity/ei_diff.py#L210)

- L'entrée CLI impose corpus complet et destination sûre.
  [`ei_diff.py:332`](../../../../../scripts/ei-parity/ei_diff.py#L332)

**Référence figée**

- Le manifeste atteste précisément les 35 couples privés et EI 3.26.0.0.
  [`corpus-manifest.json:1`](../../../../../scripts/ei-parity/corpus-manifest.json#L1)

- La baseline versionnée lie 133 écarts au manifeste exact.
  [`corpus-baseline.json:1`](../../../../../scripts/ei-parity/corpus-baseline.json#L1)

**Vérification et usage**

- Les tests couvrent succès, altérations, incohérences et confidentialité.
  [`test_ei_diff.py:1`](../../../../../tests/scripts/test_ei_diff.py#L1)

- Le workbench documente régénération et contrat non personnel.
  [`ei-parity-workbench.md:26`](../../../../../docs/ei-parity-workbench.md#L26)
