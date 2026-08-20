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

## Conflit, abandon et récupération

- **Handoff :** il ne contient qu'une synthèse, l'état, les décisions, les
  validations et des références. Un patch ou un diff reste un artefact externe
  (branche, commit ou fichier archivé) référencé par le handoff ; il n'est
  jamais recopié intégralement dans celui-ci.
- **Conflit :** le worker s'arrête, gèle son worktree, enregistre les fichiers
  concernés, validations et référence d'artefact dans son handoff, puis le Lead
  décide de l'intégration. Aucun autre worker ne résout le conflit dans ce
  worktree ni ne devient propriétaire de ses fichiers sans handoff explicite.
- **Abandon :** conserver le worktree et son diff jusqu'à ce que le Lead ait
  confirmé qu'aucun travail utile ne doit être transféré. Documenter la raison,
  le propriétaire, la référence d'artefact et la prochaine action dans le
  checkpoint.
- **Récupération :** une nouvelle session relit le handoff et le checkpoint,
  localise l'artefact référencé, choisit reprise ou abandon explicite, puis
  exécute les validations prévues.
- **Nettoyage sûr :** seulement après intégration prouvée ou abandon consigné,
  vérifier que le worktree est propre ou que son diff est archivé et référencé,
  puis supprimer worktree et branche par la procédure Git validée. Les états
  Herdr `done`, `idle` ou `terminated` sont seulement des signaux
  d'orchestration : ils ne sont jamais une preuve suffisante d'intégration ni
  une autorisation de suppression.

Ne jamais partager une branche entre worktrees. Ne jamais laisser un worker
modifier le même fichier ou contrat qu'un autre. `WvW/` ne doit être copié,
listé ou rendu accessible à aucun worktree agentique.
