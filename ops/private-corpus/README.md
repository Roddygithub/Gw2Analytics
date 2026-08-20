# Exécuteur privé éphémère

> **EXPERIMENTAL / NOT OPERATIONAL — DO NOT USE WITH REAL PRIVATE CORPUS**

Ces fichiers sont des sources versionnées et ne donnent aucun accès au corpus.
L'installation, explicitement demandée à un mainteneur, place uniquement le
wrapper, le template systemd et la règle sudo root-owned. Le registre de
production et les autorisations restent hors dépôt.

Le wrapper accepte exclusivement une requête JSON sur stdin avec
`--request-stdin` ou son invocation interne
`--run-unit <access-id>`. Il refuse les arguments libres, un profil inconnu,
un worktree non enregistré, les jetons réutilisés et `full` sans confirmation
contenant `full`. Les sorties brutes restent sous `/run/gw2analytics-private`.

Un diagnostic synthétique root-owned, identifié de façon opaque, ne contient
que tâche, scope, profil, étape, catégorie et expiration. Il expire au bout de
dix minutes; `roddy` peut le lire par le sous-programme sudo fermé
`--read-diagnostic-stdin`. Les étapes et catégories sont fixées dans le contrat.
Le registre doit pointer exactement vers la racine synthétique canonique;
l’installateur échoue si `gw2agent` possède déjà le groupe lecteur permanent.

L'installateur crée seulement le groupe privé, le corpus synthétique et le
registre root-owned nécessaires à la validation; il n'ajoute jamais
`gw2agent` à ce groupe et ne référence aucun corpus réel. Le passage `sudo` de
`roddy` constitue l’autorisation humaine ; le wrapper crée avant le montage un
tombstone root-owned atomique ne contenant que task, scope et profil, et le
conserve pour refuser toute réutilisation du jeton. L’installateur ne crée ni
groupe, ni corpus, ni appartenance permanente pour `gw2agent`.

`ei-parity-readonly` est un diagnostic non certifiant tant qu’une référence EI
canonique et l’outil de référence ne sont pas fournis et vérifiés séparément.
