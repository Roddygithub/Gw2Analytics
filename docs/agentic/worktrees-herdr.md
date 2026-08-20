# Worktrees et Herdr

Herdr 0.8.0 est disponible, mais n'est pas sur le chemin critique des tâches
simples. Le Lead l'emploie seulement lorsqu'au moins deux flux d'écriture sont
réellement indépendants, avec fichiers, contrats et critères d'acceptation non
recouvrants.

## Protocole macro

1. Le Lead fixe le commit de base, les frontières, validations et propriétaire
   d'intégration.
2. Créer une branche `agent/<task-id>-<slug>` et un worktree externe par flux.
   Aucun worktree n'est créé pour une exploration read-only.
3. Lancer au plus deux workers d'écriture, sans subagents Codex ni Ultra dans
   ces workers.
4. Chaque worker rend son diff, ses validations et son handoff ; Herdr ne décide
   ni qu'un travail est intégré, ni qu'un worktree peut être supprimé.
5. Le Lead intègre, demande une review indépendante, vérifie les validations,
   puis seulement nettoie branche et worktree après preuve d'intégration.

Ne jamais partager une branche entre worktrees. Ne jamais laisser un worker
modifier le même fichier ou contrat qu'un autre. `WvW/` ne doit être copié,
listé ou rendu accessible à aucun worktree agentique.
