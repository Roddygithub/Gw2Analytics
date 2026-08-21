# Phase 8 — exécuteur privé éphémère

> **EXPERIMENTAL / NOT OPERATIONAL — DO NOT USE WITH REAL PRIVATE CORPUS**
>
> Ne pas utiliser cet exécuteur avec `WvW/` ou tout corpus réel. Il est conservé pour reprise auditable et
> validation synthétique uniquement ; le repli humain `roddy` est le mécanisme
> temporaire autorisé pour une tâche privée explicitement approuvée.

Les sources de l’exécuteur sont dans `ops/private-corpus/`. Elles ne donnent
aucun accès au corpus : l'installateur place le wrapper, son contrat, l'unité,
la règle sudo et la copie UV dédiée root-owned seulement après accord explicite.

Le runtime est exclusivement `/run/gw2analytics-private/<access-id>/`. Les
profils admis sont `parser-validation-readonly`, `ei-parity-readonly` et
`pytest-private-fixture`; ils construisent eux-mêmes leurs arguments. Un
profil inconnu, un worktree non enregistré, un jeton réemployé, un argv libre
ou `full` sans confirmation explicite est refusé avant la création d’une unité.
Le worktree enregistré est utilisé seulement comme répertoire de travail et
reste read-only : caches Python, pytest et temporaires sont redirigés vers le
runtime de l’unité.

L’unité conserve `ProtectHome=yes`. L’installateur copie le binaire UV 0.12.5
statiquement lié depuis Mise seulement après contrôle de sa version et de son
empreinte, vers `/usr/local/lib/gw2analytics-private/` root-owned (`root:root`,
`0511`). Avant chaque demande, le wrapper revalide propriétaire, permissions,
empreinte et version. L’unité ne rend accessible que cette unique copie, par
bind mount read-only vers le runtime ; les profils utilisent ce chemin absolu
et ne résolvent jamais le shim Mise ni un `uv` fourni par `PATH`.
`UV_CACHE_DIR` demeure dans le runtime.

Les diagnostics sont réservés au registre synthétique et au purpose
`validation`. Ils sont root-owned, à durée de vie bornée, sans chemin, sortie,
contenu ou justification, et accessibles à `roddy` seulement via la commande
sudo fermée de lecture.

Les tests de contrat synthétiques automatisent les refus, le wiring subset/full
et le nettoyage demandé au wrapper. Les preuves live V-1 à V-6 (namespace,
montage et isolation effectifs) restent à exécuter sur l’hôte autorisé ; V-7
reste un contrôle de maintenance avant toute activation réelle. Les journaux
bruts et les rapports EI détaillés restent dans le runtime
et sont supprimés avec l’unité. Seul un tombstone root-owned non sensible
(tâche, scope, profil) demeure afin de refuser le réemploi du jeton.

Les essais hôte synthétiques actuels se terminent par `unit-failed/service`.
La catégorie ne distingue pas encore lancement systemd, bind de sandbox,
exécution de l'outil et sortie du profil : aucune nouvelle correction ne doit
être engagée sans observabilité redacted de ces quatre cas. Les critères de
passage à OPERATIONAL sont consignés dans
`phase8-final-checkpoint-2026-08-21.md`.
