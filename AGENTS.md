# Règles de session — Gw2Analytics

## Mémoire durable et confidentialité

- Le dépôt est la mémoire durable : code/tests/CI pour le comportement livré,
  SPEC acceptées pour le contrat à construire, ADR pour les décisions et
  `docs/agentic/` pour les checkpoints opérationnels.
- Supermemory est un outil personnel optionnel ; il ne constitue ni une
  dépendance, ni une source de vérité, ni une obligation de fin de session.
- `WvW/` contient des données personnelles locales de combats : ne jamais les
  ajouter à Git, les exfiltrer ou les ouvrir hors du périmètre du dépôt. Leur
  analyse locale (développement, tests et validations inclus) est autorisée en
  permanence : elle ne requiert ni token, ni sudoers, ni executor dédié, ni une
  nouvelle intervention humaine.

## GW2Analytics Lead

- Le rôle d'entrée stable est **GW2Analytics Lead** ; son moteur initial est
  Codex / `gpt-5.6-terra` / `medium`, mais le rôle n'est pas lié à ce profil.
- Distinguer intention et autorisation : une question, une idée, une analyse ou
  un bug signalé autorisent la lecture et une proposition, jamais une écriture
  implicite. Une demande explicite d'implémentation reste soumise au niveau
  d'autonomie du domaine.
- Appliquer le guide unique `docs/agentic/README.md` pour le routing, les
  handoffs, l'autonomie et les checkpoints utiles.
- « Continue GW2Analytics » autorise le Lead à sélectionner et exécuter la
  prochaine tâche sûre, avec checkpoints concis; il s'arrête seulement devant
  une décision produit ambiguë, une opération destructive ou une permission
  réellement inaccessible.

<!-- bmad:context -->
<!-- Verified 2026-08-13 against 553b40c. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## Gw2Analytics

Plateforme d'analyse de combats WvW. Les contrats et conventions détaillés vivent dans `README.md`, `CONTRIBUTING.md` et `docs/`; les SPEC BMAD acceptées vivent dans `_bmad-output/specs/`.

## Policy

- Ne jamais pousser directement sur `main`; passer par une PR, conserver un historique linéaire et squash-merger.
- Signer chaque commit avec le trailer DCO `Signed-off-by:`.
- Ne jamais créer de commit sans demande explicite du mainteneur.
- Ne jamais committer les logs EVTC ou exports Elite Insights privés; ne versionner que leur manifeste et leurs empreintes.

## Where things are

- Comparaison EI canonique: `libs/gw2_analytics/src/gw2_analytics/ei_compare.py`; pilotes et corpus local: `scripts/ei-parity/`.
- Décisions d'architecture acceptées: `docs/adr/`; contrat BMAD actif: `_bmad-output/specs/`; checkpoints opérationnels: `docs/agentic/`.
- Les roadmaps, backlogs, sessions et plans explicitement marqués historiques ne définissent pas la priorité. Au Level 1, une nouvelle priorité exige une proposition puis l'accord du mainteneur.

## Running and verifying

- Exécuter les outils Python via `uv run`; une invocation Python nue contourne l'environnement du workspace.
- Itérer avec les tests ciblés; la suite Python complète impose une couverture globale de 90 % et peut nécessiter les services Docker pour les tests d'intégration.
- Les skills BMAD canoniques vivent dans `.agents/skills/bmad-*` et sont intégrés à Codex. Le framework est dans `_bmad/`. Le noyau (`resolve_config.py`, `resolve_customization.py`, `render_skill.py`, `memlog.py`) ne dépend que de la stdlib — vérifiable via `tests/scripts/test_bmad_framework.py`.
- Régénérer une intégration BMAD par l'installeur officiel épinglé plutôt que modifier les fichiers gérés à la main. OpenCode n'est plus un harness actif ; tout fallback multi-provider exige une configuration et une validation distinctes.

## Conventions that differ from defaults

- `libs/gw2_core` est l'unique contrat partagé et reste sans I/O; le frontend consomme OpenAPI, jamais les structures EVTC ou ORM.
- Dans l'API, respecter `routes -> services -> repositories -> ORM`; les repositories ne commitent jamais, les services possèdent les transactions.

## Known pitfalls

- Comparer chaque entrée joueur EI à sa fenêtre `firstAware`/`lastAware`, pas aux totaux du combat entier; un même compte peut avoir plusieurs slices contiguës.
- Résoudre propriétaires, changements de personnage et identifiants d'agent avec le temps; une table globale `instance_id -> owner` produit de fausses attributions.
- Distinguer canal arcdps et classification EI pour les dégâts d'altération; les effets de vol de vie ne sont pas des altérations EI.

<!-- /bmad:context -->

## Priorité d'autonomie actuelle

La mention Level 1 du bloc BMAD géré ci-dessus est historique et ne régit plus
`Continue GW2Analytics`. La règle du **GW2Analytics Lead** définie avant ce
bloc, puis `docs/agentic/README.md`, prévaut : il exécute la prochaine tâche
sûre et déterminable sans attendre de checkpoint humain. Une décision produit
ambiguë, une opération destructive/externe ou une permission réellement
inaccessible restent les seules frontières.
