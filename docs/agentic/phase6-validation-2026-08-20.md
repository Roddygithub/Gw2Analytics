# Checkpoint — Phase 6 : validation réelle

## Statut

Validations Level 1 réalisées ; corrections de revue appliquées et livrable
candidat à une seconde review indépendante. Phase 7 interdite sans accord
explicite.

## Preuves obtenues

- Le dépôt est reconnu fiable par Codex ; la configuration de projet applique
  `gpt-5.6-terra` / `medium`.
- Le Lead a traité une idée analytique en lecture seule et a demandé un accord
  avant toute écriture.
- Explorer et Reviewer ont été créés comme subagents réels, avec handoff puis
  verdict indépendant ; les trois autres profils ont aussi été reconnus par le
  runtime dans un test séquentiel read-only.
- Herdr 0.8.0 a exécuté un flux contrôlé pane → Codex read-only → résultat.
  L'état `idle` a seulement signalé la fin apparente de l'orchestration ; avant
  la fermeture du pane temporaire, la session a vérifié indépendamment que le
  résultat était récupéré et qu'aucun diff, commit, artefact ou travail utile ne
  risquait d'être perdu. Cette vérification, et non l'état Herdr, a autorisé le
  nettoyage du pane.
- Une session Codex fraîche et éphémère a reconstruit correctement la phase,
  les limites Level 1, la confidentialité, le fallback et la prochaine action
  depuis les documents versionnés seuls.
- Les trois dettes Phase 5 ont reçu un ajustement ciblé : invariants de test
  structurés pour les profils, le handoff, le fallback, le parallélisme et
  Ultra ; critères d'Ultra ; procédure worktree de conflit/abandon/récupération.

## Limites et risques

- `codex exec --ephemeral` ne peut pas accueillir un spawn : le routeur ne
  trouve pas de thread parent. Utiliser une session persistante read-only pour
  les délégations de validation.
- Aucun worktree n'a été créé : il n'est pas nécessaire sans flux d'écriture.
- Le fallback reste non opérationnel ; une indisponibilité GPT impose arrêt et
  checkpoint, jamais un provider implicite.
- Les règles qui dépendent du comportement d'un client (sandbox, lecture seule,
  absence de fan-out imbriqué) restent aussi couvertes par les essais live ; les
  tests du dépôt protègent leurs contrats déclaratifs, pas une simulation du
  runtime.

## Prochaine action

Faire une seconde review indépendante read-only du livrable Phase 6, y compris
les ajustements de garde-fous. Toute Phase 7 ou autonomie supérieure au Level 1
reste soumise à accord explicite.
