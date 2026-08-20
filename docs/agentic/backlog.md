# Backlog agentique

## Dettes de revue — Phase 5

**Statut : ajustements Phase 6 validés.** Ils restent à réévaluer avant toute
promotion au-delà du Level 1.

1. Renforcer les tests sémantiques des garde-fous : indépendance du Reviewer,
   confidentialité `WvW/`, fallback indisponible, handoff et reprise.
2. Définir des critères objectivables pour l'utilisation d'Ultra avant toute
   utilisation réelle.
3. Compléter le protocole worktree avec une procédure explicite de conflit et
   d'abandon.
4. Ajouter une assertion ciblée du checkpoint Phase 6 : un état Herdr ne permet
   jamais seul le nettoyage ; résultat récupéré et absence de travail utile,
   diff, commit ou artefact non intégré doivent être vérifiés indépendamment.

## Initiative prioritaire — Git/GitHub Governance & Delivery Architecture

**Statut : proposée, non démarrée.** À traiter seulement après validation du
système agentique initial et avant toute modification structurelle GitHub.

La future proposition devra couvrir : stratégie de branches, PR obligatoires,
protections de `main`, checks requis, DCO, Conventional Commits, séparation CI/CD,
Release Please ou alternative, versioning, tags, releases, Dependabot, sécurité,
builds Docker, politique de merge, nettoyage des branches, et droits des agents
pour commit, push, PR, merge et release aux Levels 1/2/3.

Elle doit inventorier l'état réel, proposer les changements avant de les faire,
et aligner code, CI, documentation et règles GitHub sans les modifier pendant
la Phase 5.
