# Checkpoint final — Phase 8

> **EXPERIMENTAL / NOT OPERATIONAL — DO NOT USE WITH REAL PRIVATE CORPUS**

## Décision de clôture

La décision Phase 8 est clôturée au **Level 1**. L'exécuteur privé systemd reste
**EXPERIMENTAL / NOT OPERATIONAL** : il est interdit avec le corpus réel,
incluant `WvW/`, jusqu'aux critères de passage à OPERATIONAL ci-dessous.

Les artefacts `ops/private-corpus/`, l'installateur, les tests et la
documentation sont conservés comme base auditable de reprise. Ils ne sont pas
une autorisation d'accès réel, de migration de `WvW/`, de changement de
permission ou de lancement de service pour le corpus maître.

## Mécanisme temporaire : repli humain `roddy`

Une tâche nécessitant des logs privés suit ce protocole simple :

1. Le Lead indique le besoin, le profil précis et recommande `subset`.
2. Le mainteneur autorise explicitement la tâche ; `full` requiert une
   confirmation séparée et explicite.
3. `roddy` exécute une commande précise et limitée dans le worktree visé, avec
   lecture du corpus seulement pour cette tâche.
4. Aucun log n'est copié dans le dépôt, un pane Herdr ou un environnement
   `gw2agent`; aucun agent ne reçoit d'accès permanent.
5. Seul un résultat choisi et redacted par le mainteneur peut être transmis aux
   agents ; les temporaires sont nettoyés après la tâche.

Le repli est un contrôle humain temporaire, pas un équivalent technique de
l'exécuteur. Chaque autorisation consigne hors dépôt : identifiant de tâche,
scope, worktree, commande exacte, résultat attendu, décision de redaction et
confirmation de nettoyage. La commande ne reçoit ni shell interactif, ni argv
additionnel, ni destination persistante par défaut ; tout résultat à partager
est sélectionné par le mainteneur après exécution.

Ce repli permet parser, ingestion et parité EI sans confondre accès au code et
accès aux données privées.

## État des findings

| Sujet | État consolidé |
| --- | --- |
| Routing, rôles et Level 1 | Clair et validé ; toute exécution reste précédée d'un accord humain. |
| Worktrees persistants | Séparés du corpus ; aucun montage ou copie privée persistante. |
| Confidentialité | `WvW/` non lu, non énuméré, non déplacé, non modifié et non ajouté à Git. |
| `uv` | Prérequis `gw2agent` : version épinglée 0.12.5 via Mise, utilisation `uv run`. |
| Herdr | Contrôles de disponibilité read-only hors sandbox si le socket est refusé dans Codex. |
| Exécuteur privé | Contrats, refus, diagnostics et supply chain UV testés ; exécution systemd synthétique non validée. |
| Stash `codex-pre-phase7-main-sync` | Absent de `git stash list` lors de la clôture ; non appliqué, non inspecté. |

## Preuves et limite constatée

Les validations locales de l'exécuteur et des garde-fous documentaires passent
avec `uv run pytest tests/private_corpus tests/scripts/test_agentic_infrastructure.py -q`;
Ruff, formatage, Bash et `git diff --check` passent également. Les diagnostics
synthétiques ont démontré la validation `subset`/`full`, le tombstone à usage
unique et l'écriture redacted atomique.

Les essais hôte synthétiques retournent encore `unit-failed/service` pour les
deux scopes. La catégorie actuelle recouvre trop d'étapes et ne prouve pas à
elle seule le lancement effectif du profil. Il serait trompeur d'affirmer la
lecture read-only, le namespace ou le nettoyage live comme validés.

La review finale relève aussi que le mécanisme expérimental ne matérialise pas
encore l'autorisation humaine par tâche, que les diagnostics peuvent conserver
un `task_id` fourni par le demandeur, et que le worktree mutable exécute du code
ayant la capacité de lecture pendant la tâche. Ces risques interdisent toute
intégration opérationnelle ou accès réel.

## Dette technique : condition de reprise

Avant toute nouvelle correction systemd, ajouter une observation fermée qui
différencie :

- `systemd-start` ;
- `sandbox-bind` ;
- `tool-exec` ;
- `profile-exit`.

Elle ne peut conserver que le profil logique, `ExecMainStatus` et un code
retour ; jamais chemin privé, token, sélection, stdout/stderr ni contenu. La
reprise doit ensuite valider avec corpus synthétique : namespace de montage,
bind UV root-owned, `.venv`, cache `UV_CACHE_DIR`, lecture seule, nettoyage sur
succès/échec/interruption et reboot.

Elle doit aussi : ne jamais écraser la cause primaire par un échec de cleanup ;
contrôler l'absence d'appartenance permanente au groupe lecteur à chaque
demande ; borner les sockets locaux et le code exécutable ; refuser une
sélection `subset` qui résout vers la racine ; utiliser les binaires système
absolus ; purger les diagnostics par mécanisme indépendant ; et matérialiser un
jeton émis et lié à l'autorisation humaine.

### Private Corpus Executor Finalization — GPT-5.6 Sol / High

Cette reprise est une tâche système dédiée et ne bloque pas GW2Analytics. Elle
exige explicitement `GPT-5.6 Sol / High`. Lors de tout `codex exec resume`, le
Lead doit redemander et réappliquer explicitement le modèle et le reasoning
effort avant toute commande de diagnostic. Il vérifie le runtime effectivement
observé ; si le modèle ou l'effort ne correspond pas, il s'arrête avant tout
diagnostic et demande instruction.

## Critères de passage à OPERATIONAL

1. Les validations live synthétiques `subset` et `full` passent sous l'unité.
2. Le corpus synthétique est lisible seulement dans l'unité et son écriture y
   est refusée.
3. Aucun runtime ou montage ne demeure après succès, erreur, interruption ou
   reboot.
4. Les diagnostics restent redacted et les sorties brutes restent éphémères.
5. Une review indépendante confirme les preuves live et les garde-fous Git.
6. Le mainteneur autorise explicitement le premier accès au corpus réel.

## Hors périmètre maintenu

- Aucun déplacement de `WvW/`.
- Aucun accès réel par l'exécuteur expérimental.
- Aucun changement GitHub, aucune gouvernance Git/GitHub et aucun commit,
  push ou PR.
- Aucune intégration opérationnelle des artefacts expérimentaux. Leur future
  intégration exige un inventaire explicite des fichiers non suivis et une
  review des findings ci-dessus.
