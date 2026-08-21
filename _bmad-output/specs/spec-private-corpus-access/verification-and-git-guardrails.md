# Vérification et garde-fous Git

> **EXPERIMENTAL / NOT OPERATIONAL — DO NOT USE WITH REAL PRIVATE CORPUS**

## Matrice de preuve avant activation

| ID | Preuve | Méthode sans corpus réel | Verdict attendu |
| --- | --- | --- | --- |
| V-1 | Refus par défaut | Exécuter une sonde sous `gw2agent` hors unité contre un corpus de test administré. | Accès refusé; aucun point de montage runtime visible. |
| V-2 | Scope subset | Autoriser une sélection de test à plusieurs entrées et demander un seul élément. | L'élément autorisé est lisible dans l'unité; les autres sont absents et le corpus source reste invisible. |
| V-3 | Scope full | Autoriser explicitement `full` sur un corpus de test. | La racine est visible seulement dans l'unité et seulement pour la durée autorisée. |
| V-4 | Lecture seule | Tenter création, modification, renommage et suppression via le chemin runtime. | Toutes échouent; le corpus de test est inchangé. |
| V-5 | Isolation processus | Lancer simultanément une sonde `gw2agent` hors unité et une tâche autorisée. | Seule la tâche autorisée lit le montage. |
| V-6 | Nettoyage et expiration | Laisser expirer, annuler et tuer une unité de test. | Plus aucun montage ni runtime; le jeton ne peut être réemployé. |
| V-7 | Reboot | Créer une unité de test puis redémarrer l'hôte dans une fenêtre de maintenance. | L'unité et `/run` ont disparu; le worktree demeure sans accès. |
| V-8 | Sorties | Faire produire par le profil une sortie de test marquée sensible. | Elle reste runtime et n'apparaît ni dans journal d'audit, ni worktree, ni journal système standard. |

Ces tests utilisent un corpus factice administré. Ils ne lisent ni n'énumèrent
le corpus WvW réel. Après réussite, une validation manuelle limitée sur le
corpus réel peut seulement vérifier le profil demandé et son résultat agrégé;
elle ne verse aucun détail dans le rapport versionné.

## Audit minimal

Le journal root-owned contient seulement : timestamp, `task_id`, demandeur,
scope `subset|full`, profil de commande, identité opaque du worktree, décision,
début, fin, résultat et motif d'échec générique. Il exclut noms, chemins,
compteurs de fichiers, empreintes, contenu, stdout/stderr et arguments privés.

L'autorisation et la sélection sont stockées hors dépôt. Leur expiration et
leur consommation unique sont vérifiables dans ce stockage privé sans que les
données de corpus rejoignent Git ou les checkpoints.

## Protections Git à implémenter ultérieurement

1. Le runtime privé reste hors du dépôt; aucun montage ne cible le worktree.
2. Les règles d'ignorance couvrent les répertoires de données privées et les
   extensions de combat pertinentes, mais ne sont jamais la seule barrière.
3. Un contrôle pré-commit inspecte les chemins et contenus indexés et refuse
   les signatures ou formats de logs définis par la politique, y compris un
   ajout forcé connu.
4. La CI vérifie les règles et les tests de garde-fou sans nécessiter le
   corpus. Elle refuse toute fixture réelle ou référence à un chemin privé.
5. Les profils privés écrivent leurs outputs exclusivement au runtime; les
   tests vérifient qu'aucun fichier de corpus ou dérivé n'apparaît dans le
   worktree après exécution.

Ces protections sont une phase séparée : elles ne donnent pas l'autorisation
de modifier Git, GitHub, le stash ni les workflows de gouvernance dans cette
SPEC.

## Critères d'acceptation d'implémentation

- Les V-1 à V-6 passent avant la première autorisation de corpus réel.
- V-7 est exécuté lors d'une maintenance planifiée avant de déclarer le
  mécanisme opérationnel après reboot.
- Aucun outil ne conserve un chemin privé par défaut; parser, EI et ingestion
  documentent leur option ou variable explicite et conservent les tests
  synthétiques sans corpus.
- Un subset autorisé peut être validé par un « Oui »; un full est refusé sans
  confirmation textuelle explicite de son scope.
- Une revue indépendante confirme que le journal et les artefacts de test ne
  contiennent aucune donnée réelle ou identifiant sensible.
