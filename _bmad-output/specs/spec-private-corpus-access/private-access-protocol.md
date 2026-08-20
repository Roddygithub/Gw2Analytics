# Protocole privé d'accès au corpus

> **EXPERIMENTAL / NOT OPERATIONAL — DO NOT USE WITH REAL PRIVATE CORPUS**

## Invariants d'architecture

```text
corpus maître hors dépôt (roddy, groupe de lecture privé)
    │  aucune appartenance permanente de gw2agent
    │  autorisation humaine liée à une tâche
    ▼
autorité système root-owned
    │  résout une sélection privée ou le scope full
    ▼
unité systemd éphémère
    ├─ User=gw2agent + SupplementaryGroups=<groupe-lecture-privé>
    ├─ namespace de montage isolé
    ├─ BindReadOnlyPaths=<source privé>:<runtime opaque>
    ├─ worktree autorisé, persistant et distinct du montage
    └─ profil de commande autorisé
    ▼
résultat autorisé non sensible → Lead
fin/unité arrêtée/reboot → montage + runtime supprimés
```

Le groupe de lecture privé est une capacité du processus systemd, pas une
capacité de connexion de `gw2agent`. Le corpus maître est possédé par `roddy`;
ses permissions de groupe permettent la lecture à cette seule identité
supplémentaire. `gw2agent` ne devient jamais membre permanent de ce groupe et
ne reçoit aucune ACL durable ou temporaire sur le corpus.

L'unité est créée par une autorité locale administrée, root-owned. Elle
applique au minimum : `User=gw2agent`, groupe supplémentaire privé,
`BindReadOnlyPaths=`, namespace de montage privé, protection des homes,
réduction des chemins inscriptibles au worktree explicitement autorisé et au
runtime, et `NoNewPrivileges=`. Les options exactes sont figées lors de la
future implémentation, contre la version de systemd effectivement installée.

Le processus voit les données sous
`/run/gw2analytics-private/<access-id>/input`. `<access-id>` est aléatoire ou
opaque et ne contient ni nom de corpus, ni nom de combat. Ce chemin n'existe ni
dans le worktree, ni pour les processus ordinaires de `gw2agent`.

## Demande, autorisation et UX

Le Lead formule une demande concise, sans données privées :

```yaml
task_id: stable-id
purpose: validation parser|ei|ingestion|reproduction|analyse
scope: subset|full
why_private_data: justification orientée résultat
worktree_ref: identifiant ou chemin de worktree autorisé
command_profile: parser-tests|ei-parity|ingestion-ephemeral|diagnostic-approuvé
selection_ref: opaque-private-ref # obligatoire seulement pour subset
requested_output: résultat agrégé non sensible
```

Pour `subset`, le Lead présente : « Cette tâche nécessite l'accès à des logs
privés. Je recommande un accès subset en lecture seule pour cette validation.
Autorisez-vous cet accès ? » Le mainteneur peut répondre « Oui ».

Pour `full`, le Lead présente le motif global, l'absence d'alternative subset,
le worktree et le profil de commande : « Cette analyse nécessite l'ensemble du
corpus privé en lecture seule. Confirmez-vous explicitement l'accès `full` pour
la tâche `<task_id>` ? » Une réponse générique « Oui » ne vaut pas confirmation
`full`; la confirmation doit contenir `full` ou reprendre l'identifiant de
tâche et le scope.

La demande autorisée est consommable une fois, avec une durée maximale bornée.
Une nouvelle commande, un nouveau worktree, un autre scope ou une reprise après
expiration créent une nouvelle demande. Le mainteneur ne manipule ni groupes,
ni montages, ni unités.

## Sélection privée

Une sélection `subset` est définie dans un registre privé hors dépôt, accessible
seulement à l'autorité système et au mainteneur. `selection_ref` est un jeton
opaque associé à une liste de fichiers ou de répertoires et à une durée; il ne
révèle aucune entrée par sa valeur, par le journal ni par le handoff.

L'autorité vérifie que la sélection reste sous le corpus maître, ne suit aucun
lien sortant, et monte uniquement les éléments résolus. Le sous-ensemble peut
être un ou plusieurs fichiers ou un répertoire nécessaire à l'outil. `full`
monte la racine du corpus maître seulement après confirmation renforcée.

La sélection n'est ni copiée ni matérialisée dans le dépôt. Le bind mount est
préféré à un staging de données : il ne crée pas de seconde copie. Un staging
temporaire sur runtime peut être autorisé uniquement lorsqu'un outil ne sait pas
consommer un montage direct; il doit être en mémoire ou dans un espace runtime
privé, supprimé avec l'unité, et faire l'objet d'une autorisation documentée.

## Exécution, sorties et révocation

L'autorité refuse tout argv libre. Un `command_profile` désigne une commande
connue avec paramètres bornés, workdir contrôlé et chemin d'entrée injecté par
la plateforme. Le profil reçoit le runtime input par argument ou variable
explicitement définie; il ne déduit aucun chemin privé par défaut.

Les sorties de processus sont privées par défaut : stdout/stderr brut est
capturé dans le runtime et détruit lors du nettoyage. Le profil retourne au Lead
seulement son résultat contractuel non sensible : statut, compteurs agrégés,
identifiant de tâche et diagnostic sans nom ni contenu de log. Toute sortie
porteuse de données privées exige une décision humaine distincte, hors du flux
normal.

Les sorties temporaires vivent sous le runtime de l'unité. Un profil
`ingestion-ephemeral` utilise en plus une base, un stockage et une file de test
éphémères. Ni upload, ni export EI, ni rapport détaillé ne peut être écrit dans
le worktree ou dans un stockage persistant par défaut.

L'unité est `stop`pée à la fin, à l'expiration ou à l'annulation. Le runtime est
supprimé avec elle. Au reboot, les unités transient et `/run` disparaissent; un
worktree persistant n'emporte donc jamais le montage. En cas d'échec ou
d'interruption, l'autorité stoppe l'unité, vérifie l'absence de montage et de
runtime, enregistre le résultat minimal, puis refuse toute reprise automatique.

Le rollback est l'arrêt de l'unité et l'invalidation de l'autorisation. Si une
future configuration de groupe, permissions ou service s'avère incorrecte,
elle est retirée par une procédure administrée séparée; aucune réparation ne
doit ouvrir le corpus à `gw2agent` par défaut.

## Intégrations outils et worktrees

Les CLI parser, EI et ingestion doivent accepter un chemin de données privé
explicite, sous forme d'option `--corpus-dir`/`--input-dir` ou d'une variable
injectée par le profil. Sans injection, elles ne trouvent aucun corpus réel et
échouent avec un message ne révélant pas de chemin privé. Les chemins implicites
privés existants doivent être retirés lors de la phase d'implémentation, avec
compatibilité documentée pour les fixtures synthétiques.

Les profils initiaux sont : tests parser sur sélection, parité EI sur sélection,
parité EI globale, reproduction contrôlée et ingestion éphémère. Chaque profil
déclare ses entrées, sorties autorisées, services de test éphémères et règle de
nettoyage avant d'être activé.

Herdr ne reçoit jamais le montage dans un pane normal. Lorsqu'un worker doit
valider des données privées, le Lead lie la demande à son worktree persistant
et déclenche le profil via l'exécuteur. Un autre worktree, pane ou agent sous
le même UID ne voit pas les données : l'isolation est celle du processus et de
son namespace, non une promesse fondée sur le seul chemin du worktree.
