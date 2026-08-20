# État courant agentique

## Phase 5 — Infrastructure minimale

- **Statut :** revue PASS conditionnel acceptée ; intégration Phase 5 en cours.
  Phase 6 interdite sans accord.
- **Base :** `7a347f5dfe2c64cbcd0998e550477b64908448c9` sur `main`.
- **Objectif :** rôle Lead stable, profils Codex, politiques de routing,
  communication, autonomie, worktrees/Herdr et reprise persistante.
- **Profil Lead initial :** Codex / `gpt-5.6-terra` / `medium`.
- **Autonomie :** Level 1 pour tous les domaines.
- **Fallback :** non configuré et non déclaré opérationnel.
- **Confidentialité :** `WvW/` interdit à toute lecture, énumération,
  indexation, modification ou ajout Git sans autorisation explicite.

## Dettes acceptées de la revue Phase 5

À traiter avant toute promotion au-delà du Level 1 et à réévaluer pendant la
Phase 6 : tests sémantiques des garde-fous (Reviewer, `WvW/`, fallback,
handoff et reprise), critères objectivables pour Ultra, et procédure worktree
de conflit ou d'abandon.

## Validations

- PASS — `uv run pytest tests/scripts/test_agentic_infrastructure.py
  tests/scripts/test_bmad_framework.py` : 10 tests.
- PASS — Ruff ciblé sur les deux tests d'infrastructure.
- PASS — `codex --strict-config exec --help` : configuration sans clé inconnue.
- PASS — interfaces Codex/Herdr : CLI Codex 0.148.0 ; Herdr 0.8.0 expose les
  commandes d'intégration et de worktrees documentées.
- PASS — résolveurs `resolve_config.py` et `resolve_customization.py` BMAD.
- PASS — `git diff --check`.
- NOT RUN — conversation Codex réelle, spawn et routing de bout en bout : la
  couche `.codex/config.toml` est chargée seulement lorsqu'un client marque le
  dépôt fiable ; aucun appel modèle payant ni modification de configuration
  utilisateur hors dépôt n'a été effectué.
- BLOCKED — statut live Herdr et flux macro : le socket serveur est inaccessible
  depuis ce sandbox ; aucun worktree ou pane n'a été créé.

## Reprise

Avant la validation fonctionnelle de Phase 6, ouvrir le dépôt dans un client
Codex fiable, vérifier qu'il charge `.codex/config.toml`, puis tester un seul
cas read-only du Lead. Ne pas activer Herdr, créer de worktree, modifier les
niveaux d'autonomie ou configurer un fallback sans accord explicite.
