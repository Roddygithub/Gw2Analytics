# Politique de routing

## Intention et autorisation

| Intention | Action initiale | Écriture |
| --- | --- | --- |
| question / explication | lire, citer les sources et répondre | non |
| idée / brainstorming | challenger, options, bénéfices et risques | non |
| analyse produit ou technique | investiguer et recommander | non |
| bug « semble cassé » | diagnostiquer, reproduire si possible, rapporter | non, sans demande de fix |
| implémente / fixe / modifie | exécuter dans le périmètre explicite | selon autonomie et risque |
| continue la roadmap | proposer la prochaine action | Level 1 : non |

Un doute d'autorisation bloque l'écriture, jamais l'analyse.

## Modèle × reasoning

| Tâche | Départ | Escalade |
| --- | --- | --- |
| documentation, test mécanique, renommage borné | Luna / low ou medium | Luna / high, puis Terra / medium |
| exploration ciblée | Luna / medium | Terra / medium si contexte croisé |
| UI simple | Luna / medium | Terra / medium si UX ou état complexe |
| feature ou backend courant | Terra / medium | Terra / high, puis xhigh |
| debug multi-fichiers ou review | Terra / high | Terra / xhigh, puis Sol / high |
| EVTC, analytics, persistance, migration, données | Sol / high ou consultation Specialist | Sol / xhigh ; max seulement avec critère mesurable |
| architecture ou causalité exceptionnelle | Sol / xhigh | Sol / max après comparaison utile |

Augmenter l'effort lorsque le modèle comprend encore la sémantique ; changer de
modèle lorsque la profondeur de contexte ou le jugement ne suffisent plus. Ne pas
faire monter Luna artificiellement jusqu'à max si Terra medium est plus fiable.

La configuration projet utilise les efforts portables `low`, `medium`, `high`
et `xhigh`. `max` et Ultra ne sont pas des valeurs par défaut de fichier : ils
requièrent une vérification du client disponible et une justification écrite.

## Parallélisme

Une seule couche possède le fan-out :

1. tâche simple : Lead seul ;
2. exploration ou review réellement indépendantes : subagents Codex read-only ;
3. deux flux d'écriture réellement indépendants : Herdr et worktrees ;
4. Ultra exceptionnel : ni Herdr ni subagents Codex supplémentaires.

Herdr, subagents Codex et Ultra ne sont jamais imbriqués sans justification
explicite, propriétaire unique, limite de concurrence et plan de récupération.
La limite Phase 5 est de deux subagents simultanés ; aucune écriture parallèle
sans worktree et frontières de fichiers/contrats indépendantes.
