# Checkpoint — Phase 7 : pilote `OSError` atomique

## Statut

Story pilote validée après reprise et deux reviews indépendantes read-only.
L'intégration est autorisée uniquement par une PR atomique ; le Level 1 et
l'interdiction de démarrer la Phase 8 sans accord explicite restent applicables.

## Travail préservé

- Base : `cca199cf25794fddcd234010f8f0af8ae5af83ea`.
- Branche : `agent/phase7-oserror-atomic`.
- Worktree persistant et sauvegarde indépendante : artefacts locaux externes,
  conservés jusqu'à preuve d'intégration ; aucun chemin local ni artefact privé
  n'est versionné dans ce checkpoint.
- Fichier modifié : `tests/scripts/test_ei_diff.py` seulement.
- Intention : simuler un `OSError` de `os.replace()` pour `--report-json`,
  préserver une destination existante et vérifier la suppression du temporaire.
- La sauvegarde a permis une reprise fiable sans dépendance à la session
  initiale. Aucun artefact applicatif ni donnée de corpus n'est versionné.

## Validations

| Validation | État | Preuve |
| --- | --- | --- |
| Ruff format/check ciblé | PASS | exécuté par l'Implementer après formatage minimal |
| `git diff --check` ciblé | PASS | aucun whitespace invalide |
| Pytest ciblé | PASS après reprise | 47 tests ciblés passent avec l'interpréteur synchronisé du worktree |

## Reprise et validation post-interruption

- La reprise a conservé le diff utile : un seul fichier de test, avec 25 lignes
  ajoutées ; aucune sémantique EI, parsing, analytics ou comportement applicatif
  n'a été modifiée.
- Après synchronisation de l'environnement de développement, la validation
  ciblée a passé : 47 tests, Ruff format/check et `git diff --check`.
- `uv run` n'a pas résolu directement les scripts `pytest` et `ruff` bien que
  ceux-ci soient présents dans le venv ; `uv run --no-sync python -m pytest`
  a exécuté le test avec l'interpréteur du worktree. C'est une anomalie de
  lanceur locale, pas un échec de test ni de la story.

## Review indépendante read-only

- Trois couches distinctes de l'Implementer ont relu le diff sans modifier de
  fichier : Verification Gap (aucun gap), Edge Case Hunter et Blind Hunter.
- Le test simule réellement `OSError` sur `os.replace()`, laisse la destination
  préexistante inchangée, vérifie le message `unable to write output` et la
  suppression du temporaire. Les helpers substituent le travail EI réel : le
  test est hermétique et ne lit pas le corpus privé.
- Le finding non bloquant sur la destination de remplacement a été résolu avec
  l'accord du mainteneur : le spy conserve désormais source et destination,
  puis le test exige explicitement que la destination soit `output`.
- Les autres suggestions étaient hors contrat (métadonnées, cas d'erreur
  supplémentaires, scénarios préexistants) ou déjà couvertes : les 47 tests
  incluent le nouveau cas et ne constituent pas une preuve périmée.
- Après ce renforcement, les 47 tests ciblés, Ruff format/check et
  `git diff --check` passent encore. Le diff final reste minimal :
  `tests/scripts/test_ei_diff.py` seul, 25 lignes ajoutées.
- Une ultime review indépendante read-only (Verification Gap, Edge Case Hunter
  et Blind Hunter) est clean après triage : elle ne relève ni changement de
  production ni lacune dans le contrat de cette story.

## Routing observé

| Rôle | Prévu / demandé | Runtime observé |
| --- | --- | --- |
| Pane Herdr `w2:p5` | session interactive, hors workflow writer | Terra / high |
| Lead | Terra / medium | Terra / medium |
| Implementer initial | Luna / medium | Luna / medium |
| Implementer repris | Luna / medium attendu | Terra / medium |
| Reviewer final | Terra / high demandé | non observé directement : aucun en-tête runtime archivé |

Le changement Luna → Terra lors de `codex exec resume` est une divergence
runtime réelle : le client a indiqué reprendre une session Luna avec le modèle
par défaut Terra. Un handoff textuel n'est jamais autoritatif face à l'en-tête
runtime observé ; cette preuve doit être relevée à chaque reprise importante.
Le profil des Reviewers ne doit donc pas être présenté comme une preuve runtime.

## Incident de garde-fou

Au démarrage de la reprise, une commande `git status --short` au dépôt
principal a indirectement affiché l'existence de `WvW/`. Aucun contenu n'a été
ouvert, lu, indexé ou modifié. C'est un incident mineur à transférer avant toute
autonomie élargie : les contrôles de reprise doivent utiliser des chemins
ciblés et des exclusions explicites, jamais un statut global du dépôt.

## Findings à transférer vers Phase 8 — sans démarrer la phase

1. `codex exec resume` a repris une session demandée Luna / medium avec Terra /
   medium : divergence runtime réelle, à rendre observable et contrôlable.
2. Une commande de statut global a indirectement énuméré `WvW/` sans en lire le
   contenu : renforcer les garde-fous de commandes ciblées et d'exclusions.
3. Après synchronisation, `uv run` n'a pas résolu directement les scripts
   installés `pytest` et `ruff`, alors que `uv run --no-sync python -m pytest`
   fonctionnait : anomalie locale de lanceur à qualifier.

## Dette de cohérence

La divergence antérieure de `current-state.md` — une Phase 6 déjà intégrée y
était encore présentée comme candidate à review — est inscrite au backlog
agentique. La mise à jour minimale de l'état courant est nécessaire à cette
reprise fraîche ; la réconciliation historique complète reste une dette
distincte.

## Prochaine action

Créer et faire vérifier une PR atomique limitée à ce test et au présent
checkpoint, puis attendre les checks et la décision humaine de merge. La Phase
8 ne commence pas dans cette story.

## Confidentialité et nettoyage

Le corpus privé n'a pas été consulté. Aucun état Herdr (`idle`, `done` ou
équivalent) ne vaut preuve de complétion ou autorisation de fermeture. Avant
tout nettoyage futur, vérifier indépendamment le diff, les commits, les
artefacts et les résultats récupérés. L'ancien worktree sous `/tmp` demeure
intentionnellement présent jusqu'au redémarrage ; il n'est plus une dépendance
de reprise.
