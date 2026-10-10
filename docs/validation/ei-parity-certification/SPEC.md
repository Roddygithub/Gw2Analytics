---
id: SPEC-ei-parity-certification
companions:
  - certification-matrix.md
sources:
  - scripts/ei-parity/corpus.txt
---

> **Contrat canonique.** Cette SPEC et les fichiers de `companions:` définissent entièrement ce qui doit être construit, testé et validé.

# Certification de parité Elite Insights

## Why

Gw2Analytics doit disposer d'un socle parser et analytics mesurable face à Elite Insights v3.26.0.0 avant d'ajouter des analyses transversales. Sans certification, une nouvelle métrique peut être cohérente en apparence tout en héritant d'attributions, de fenêtres temporelles ou d'agrégats incorrects.

## Capabilities

- **CAP-1**
  - **intent:** Le mainteneur peut exécuter un corpus EI traçable dont les fichiers privés restent hors dépôt.
  - **success:** Chaque entrée du manifeste identifie sans ambiguïté le log, son export EI, leur empreinte, la version EI attendue et les cas de couverture, et tous les fichiers locaux requis sont contrôlés avant comparaison.
- **CAP-2**
  - **intent:** Le système compare les données couvertes par log, slice joueur, bucket et compétence selon un contrat explicite.
  - **success:** La comparaison applique les mappings et tolérances de `certification-matrix.md`, sans ignorer silencieusement un champ ou un delta.
- **CAP-3**
  - **intent:** Le mainteneur peut distinguer automatiquement une parité acquise, un écart accepté et une régression.
  - **success:** Chaque résultat est classé `PASS`, `KNOWN_DELTA` ou `FAIL`, et une sortie JSON stable fournit expected, actual, delta, log, joueur, bucket et compétence lorsque disponibles.
- **CAP-4**
  - **intent:** La comparaison attribue chaque événement à la bonne identité et au bon propriétaire au moment où il survient.
  - **success:** Les changements de personnage, slices `firstAware`/`lastAware`, réutilisations d'instance ID et relations maître/pet/minion sont couverts par des tests et ne produisent aucun delta inexpliqué dans les buckets certifiés.
- **CAP-5**
  - **intent:** Chaque correction de parité reste protégée contre les régressions.
  - **success:** Toute divergence corrigée ajoute un test synthétique minimal qui échoue avant la correction, puis le corpus certifié ne contient aucun `FAIL` inexpliqué.

## Constraints

- Elite Insights v3.26.0.0 est la référence figée; un changement de version ouvre une nouvelle baseline explicite.
- Étendre `compare_elite_insights` et `scripts/ei-parity/`; ne pas créer une seconde chaîne de comparaison.
- Les logs EVTC et exports EI restent privés et hors Git; seul leur manifeste sans données personnelles est versionné.
- Prioriser les logs postérieurs à juillet lors de l'extension du corpus, sans supprimer les anciens cas limites déjà utiles.
- Les compteurs, identifiants et listes ordonnées sont exacts; toute tolérance flottante doit être définie par bucket et justifiée dans la matrice.
- Un `KNOWN_DELTA` exige une règle versionnée avec motif, périmètre et critère de retrait; aucune regex globale ne peut masquer de nouveaux écarts.

## Non-goals

- Reproduire toutes les fonctionnalités, tous les écrans ou tous les champs exportés par Elite Insights.
- Construire l'analyse des phases d'engagement avant la certification des signaux qu'elle consommera.
- Ajouter une interface web au rapport de certification.
- Versionner ou redistribuer les journaux de combat et exports EI privés.
- Réécrire le parser ou `compare_elite_insights` uniquement pour réduire leur complexité interne.

## Success signal

- Sur le corpus certifié, chaque bucket inclus est `PASS` ou possède un `KNOWN_DELTA` borné et justifié; aucun `FAIL` inexpliqué ne subsiste.
- Un nouveau couple log/export peut être ajouté par manifeste et produire le même rapport machine-lisible sans procédure spéciale ni modification de code.

## Assumptions

- Les 35 entrées actuelles de `scripts/ei-parity/corpus.txt` constituent la baseline initiale; leur disponibilité, leurs empreintes et la couverture post-juillet seront inventoriées dans la première story.

## Open Questions

- Quels buckets déjà comparés doivent entrer dans la première certification, et lesquels doivent rester explicitement hors périmètre ?
- Comment attester automatiquement que chaque export de référence a été généré par Elite Insights v3.26.0.0 ?
