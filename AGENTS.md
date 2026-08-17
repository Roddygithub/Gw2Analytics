# Règles de session — Gw2Analytics

## Compactions / résumés de session
À CHAQUE fin de session (ou à chaque compaction), sauvegarder le résumé complet de la session dans **supermemory** :

- Espace actif par défaut (ne pas en créer d'autre).
- Format : titre `## PROJET Gw2Analytics — Résumé de session (YYYY-MM-DD)` puis sections : Objectif, État du travail (fait/en cours/bloqué), Next Move, Fichiers clés, Probes, Notes de décision.
- Toujours inclure les diffs de parité actuels (par joueur), les mappings EI identifiés, et les IDs/GUIDs en jeu.
- Utiliser `supermemory_add_memory` avec `action: "save"`.

Ne PAS garder le résumé uniquement dans le contexte de session — il doit être persistant dans supermemory pour les sessions suivantes.

<!-- bmad:context -->
<!-- Verified 2026-08-13 against 553b40c. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## Gw2Analytics

Plateforme d'analyse de combats WvW. Les contrats et conventions détaillés vivent dans `README.md`, `CONTRIBUTING.md` et `docs/`; la planification BMAD vit dans `_bmad-output/`.

## Policy

- Ne jamais pousser directement sur `main`; passer par une PR, conserver un historique linéaire et squash-merger.
- Signer chaque commit avec le trailer DCO `Signed-off-by:`.
- Ne jamais créer de commit sans demande explicite du mainteneur.
- Ne jamais committer les logs EVTC ou exports Elite Insights privés; ne versionner que leur manifeste et leurs empreintes.

## Where things are

- Comparaison EI canonique: `libs/gw2_analytics/src/gw2_analytics/ei_compare.py`; pilotes et corpus local: `scripts/ei-parity/`.
- Décisions d'architecture acceptées: `docs/adr/`; contrat BMAD actif: `_bmad-output/specs/`.

## Running and verifying

- Exécuter les outils Python via `uv run`; une invocation Python nue contourne l'environnement du workspace.
- Itérer avec les tests ciblés; la suite Python complète impose une couverture globale de 90 % et peut nécessiter les services Docker pour les tests d'intégration.
- Les skills BMAD vivent dans `.agents/skills/bmad-*` (chargés via `skills.paths` d'`opencode.json`) et le framework dans `_bmad/`. Le noyau (`resolve_config.py`, `resolve_customization.py`, `render_skill.py`, `memlog.py`) ne dépend que de la stdlib — vérifiable via `tests/scripts/test_bmad_framework.py`.
- opencode ne substitue aucune variable dans les skills (à la différence de Claude Code) : remplacer manuellement `{project-root}` par la racine du repo (`/home/roddy/Work/Gw2Analytics`) et `{skill-root}` par le répertoire du skill invoqué (le bloc « Base directory » de l'outil skill).

## Conventions that differ from defaults

- `libs/gw2_core` est l'unique contrat partagé et reste sans I/O; le frontend consomme OpenAPI, jamais les structures EVTC ou ORM.
- Dans l'API, respecter `routes -> services -> repositories -> ORM`; les repositories ne commitent jamais, les services possèdent les transactions.

## Known pitfalls

- Comparer chaque entrée joueur EI à sa fenêtre `firstAware`/`lastAware`, pas aux totaux du combat entier; un même compte peut avoir plusieurs slices contiguës.
- Résoudre propriétaires, changements de personnage et identifiants d'agent avec le temps; une table globale `instance_id -> owner` produit de fausses attributions.
- Distinguer canal arcdps et classification EI pour les dégâts d'altération; les effets de vol de vie ne sont pas des altérations EI.

<!-- /bmad:context -->
