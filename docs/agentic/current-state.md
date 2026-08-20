# État courant agentique

## Phase 6 — Validation réelle de l'infrastructure

- **Statut :** corrections des findings Phase 6 réalisées ; livrable candidat
  à une seconde review indépendante. Phase 7 interdite sans accord.
- **Base :** `72ec29fd4eb71c41f02ff2bf1ccbff7c4468dc9c` sur `main`.
- **Objectif :** démontrer les profils et politiques dans Codex/Herdr réels,
  sans développement fonctionnel.
- **Profil Lead initial :** Codex / `gpt-5.6-terra` / `medium`.
- **Autonomie :** Level 1 pour tous les domaines.
- **Fallback :** non configuré et non déclaré opérationnel.
- **Confidentialité :** `WvW/` interdit à toute lecture, énumération,
  indexation, modification ou ajout Git sans autorisation explicite.
- **Prérequis utilisateur local :** l'entrée de confiance Codex du dépôt est
  présente et valide dans la configuration utilisateur ; son contenu hors de
  cette entrée ne fait pas partie du dépôt.

## Dettes acceptées de la revue Phase 5

Ajustements réalisés, en attente de seconde review indépendante avant toute
promotion au-delà du Level 1 : tests sémantiques des garde-fous (Reviewer,
`WvW/`, fallback, handoff et reprise), critères objectivables pour Ultra, et
procédure worktree de conflit ou d'abandon.

## Validations

- PASS — `uv run pytest tests/scripts/test_agentic_infrastructure.py
  tests/scripts/test_bmad_framework.py` : 11 tests.
- PASS — Ruff ciblé sur les deux tests d'infrastructure.
- PASS — Codex réel : Lead `gpt-5.6-terra` / `medium`, interaction read-only,
  profils custom et handoff Explorer → Reviewer validés.
- PASS — Herdr 0.8.0 : socket, pane temporaire, Codex read-only, état et
  résultat récupérés, puis pane supprimé.
- PASS — reprise fresh-context : une session Codex éphémère reconstruit Phase
  6, Level 1, confidentialité, fallback, dettes et prochaine action depuis les
  documents versionnés.
- PASS — interfaces Codex/Herdr : CLI Codex 0.148.0 ; Herdr 0.8.0 expose les
  commandes d'intégration et de worktrees documentées.
- PASS — résolveurs `resolve_config.py` et `resolve_customization.py` BMAD.
- PASS — `git diff --check`.
- BLOCKED — spawn dans `codex exec --ephemeral` : ce mode ne fournit pas de
  thread parent au routeur. Le même test persistant read-only est passé.
- NOT RUN — worktree temporaire : non requis pour le flux Herdr sans écriture.

## Reprise

Faire la seconde review indépendante read-only des ajustements Phase 6. Ne pas
créer de worktree d'écriture, modifier les niveaux d'autonomie ou configurer un
fallback sans accord explicite.
