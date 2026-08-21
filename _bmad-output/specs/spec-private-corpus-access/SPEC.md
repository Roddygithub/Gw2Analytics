---
id: SPEC-private-corpus-access
companions:
  - private-access-protocol.md
  - verification-and-git-guardrails.md
sources: []
---

> **Contrat canonique.** Cette SPEC et les fichiers de `companions:` définissent entièrement ce qui doit être construit, testé et validé.

> **EXPERIMENTAL / NOT OPERATIONAL — DO NOT USE WITH REAL PRIVATE CORPUS**

# Accès contrôlé au corpus privé WvW

## Why

Gw2Analytics doit pouvoir valider le parser, l'ingestion et la parité Elite Insights sur des combats réels sans faire du corpus privé une dépendance accessible par défaut de l'environnement de développement. Le maintien de cette frontière protège les données tout en évitant que les validations fondées sur des logs réels deviennent impraticables.

## Capabilities

- **CAP-1**
  - **intent:** Le Lead peut demander un accès privé lié à une tâche, et le mainteneur peut autoriser un accès `subset` par une confirmation simple.
  - **success:** La demande lie un identifiant de tâche, un objectif, un worktree, un profil de commande et le scope `subset`; une réponse « Oui » du mainteneur suffit sans manipulation de groupe, montage ou unité système.
- **CAP-2**
  - **intent:** Une tâche normale peut consommer uniquement une sélection privée de logs en lecture seule.
  - **success:** La sélection est résolue hors dépôt depuis une référence opaque, seuls ses éléments sont visibles au processus autorisé, et ni noms, ni chemins, ni contenu, ni empreintes du corpus ne figurent dans Git, les handoffs ou le journal d'audit.
- **CAP-3**
  - **intent:** Le mainteneur peut autoriser exceptionnellement l'ensemble du corpus lorsqu'une analyse globale le justifie.
  - **success:** Une demande `full` contient une justification concrète et exige une confirmation renforcée distincte; l'exposition reste limitée au processus éphémère, en lecture seule, et disparaît ensuite.
- **CAP-4**
  - **intent:** Les outils parser, EI et ingestion peuvent recevoir des données privées sans connaître de chemin privé par défaut.
  - **success:** Chaque outil compatible reçoit un chemin d'entrée explicitement injecté; ses sorties par défaut sont limitées au runtime ou à un environnement de test éphémère, et aucune donnée de corpus n'est écrite dans le worktree, Git, une base ou un stockage persistant sans une autorisation distincte.
- **CAP-5**
  - **intent:** L'exécution privée reste isolée, révocable et traçable sans journaliser de données de combat.
  - **success:** Une unité systemd dédiée ne donne au processus que le groupe de lecture temporaire et un bind mount read-only; fin, échec, annulation, redémarrage ou arrêt de l'unité rendent le corpus à nouveau inaccessible et ne laissent que l'audit minimal non sensible.
- **CAP-6**
  - **intent:** Le mainteneur peut démontrer les garde-fous avant d'autoriser l'usage productif du mécanisme.
  - **success:** Les contrôles décrits dans `verification-and-git-guardrails.md` prouvent le refus hors exécuteur, les scopes `subset` et `full`, la lecture seule, le nettoyage, le traitement des interruptions et l'absence de chemin de fuite Git.

## Constraints

- Le corpus maître reste hors dépôt, détenu par `roddy`, et `gw2agent` n'y possède aucun accès permanent, y compris par ACL ou groupe permanent.
- Le seul chemin d'accès est un exécuteur systemd éphémère, lancé par une autorité système administrée; un pane Herdr, une session Codex ordinaire ou un worktree ne reçoit jamais de montage persistant.
- L'exécuteur utilise un namespace de montage, un bind mount read-only et une identité `gw2agent` complétée seulement pendant l'exécution par un groupe de lecture privé non permanent.
- Le montage n'est jamais placé dans le dépôt ou dans un worktree; son chemin runtime est opaque, sous `/run/gw2analytics-private/`, et disparaît avec l'unité ou au reboot.
- `subset` est le défaut. `full` exige une justification globale et une confirmation explicite renforcée; aucun fallback implicite de `subset` vers `full` n'est permis.
- La résolution d'une sélection se fait exclusivement dans un registre privé root-owned, hors dépôt; le contrat versionné ne contient aucun nom de log, chemin, hash, extrait ou contenu de combat.
- Seuls des profils de commande approuvés peuvent être exécutés. Un shell général, l'export brut de stdout/stderr vers le journal système et la copie vers le worktree sont interdits par défaut.
- Les données privées ne sont jamais ajoutées à Git. Les protections Git complémentaires restent un chantier ultérieur, décrit mais non implémenté par cette SPEC.
- Cette Phase 8 reste au Level 1 : la SPEC autorise une future proposition d'implémentation, jamais une migration, un changement de permission, un service ou une configuration GitHub sans accord ultérieur.

## Non-goals

- Déplacer `WvW/`, créer l'unité systemd, modifier des permissions, créer un groupe ou monter le corpus dans cette phase de spécification.
- Donner à tous les processus de `gw2agent`, à tous les worktrees ou à Herdr un accès direct au corpus.
- Construire un gestionnaire de secrets, une plateforme de data catalog ou une orchestration de conteneurs.
- Versionner, archiver durablement ou redistribuer les logs, exports EI, sélections privées ou leurs dérivés.
- Commencer Git/GitHub Governance & Delivery Architecture, configurer GitHub ou intervenir sur un stash.

## Success signal

Un mainteneur peut autoriser une validation réelle par un « Oui » pour un `subset` ou une confirmation renforcée pour un `full`; seule la commande approuvée dans le worktree visé voit les données read-only, puis cet accès disparaît automatiquement sans fuite dans le dépôt ni dans l'audit.

## Open Questions

- Quelle autorité locale root-owned (service template, wrapper restreint ou règle polkit/sudo) est la plus adaptée à l'hôte lors de la future phase d'implémentation, après inspection de sa politique système ?
- Quels profils de commande initiaux doivent être admis pour parser, EI et ingestion, et quelle sortie agrégée non sensible chacun doit-il retourner au Lead ?
