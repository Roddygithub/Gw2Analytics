# GW2Analytics Lead

## Point d'entrée quotidien

Parlez au rôle **GW2Analytics Lead** depuis la racine du dépôt. Il est stable ;
le profil initial est Codex / `gpt-5.6-terra` / `medium`, mais peut évoluer sans
changer votre point d'entrée.

Exemples naturels :

- « J'ai une idée de feature. »
- « J'ai trouvé un bug. »
- « Pourquoi cette statistique fonctionne comme ça ? »
- « Implémente cette story validée. »
- « Continue la roadmap. »

Vous ne choisissez normalement ni modèle, ni reasoning, ni worker, ni
worktree, ni Reviewer. Le Lead lit l'état canonique, classe l'intention et le
risque, puis propose ou exécute seulement ce qui est autorisé.

## Discussion n'est pas exécution

| Formulation | Réponse attendue au Level 1 |
| --- | --- |
| question, idée, analyse, bug signalé | investigation et proposition ; aucune écriture implicite |
| décision validée + demande d'implémentation | exécution bornée, validations et review selon le risque |
| « Continue la roadmap » | prochaine proposition priorisée ; attente de votre accord avant écriture |

En cas de doute, le Lead continue l'analyse mais s'arrête avant toute mutation.

## Sources de vérité

1. code, tests et CI : comportement livré ;
2. SPEC acceptées sous `_bmad-output/specs/` : contrat à construire ;
3. `docs/adr/` : décisions d'architecture ;
4. ce dossier : politique agentique et checkpoints assainis ;
5. Git/GitHub : historique et état d'intégration.

Supermemory n'est pas une source opérationnelle. `WvW/` est un corpus privé :
il est interdit de l'ouvrir, de l'énumérer, de l'indexer, de le modifier ou de
l'ajouter à Git sans autorisation explicite.

## Documents opérationnels

- [Architecture](architecture.md) — composants et frontières.
- [Routing](routing-policy.md) — modèle, reasoning, risque et parallélisme.
- [Communication](communication-protocol.md) — délégation et handoff.
- [Autonomie](autonomy-policy.md) — Level 1 à 3 et rétrogradation.
- [Worktrees et Herdr](worktrees-herdr.md) — flux macro indépendants.
- [Backlog agentique](backlog.md) — initiatives à traiter ultérieurement.
- [État courant](current-state.md) — reprise après interruption.
