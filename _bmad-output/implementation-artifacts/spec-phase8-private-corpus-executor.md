---

> **EXPERIMENTAL / NOT OPERATIONAL — DO NOT USE WITH REAL PRIVATE CORPUS**
title: 'Exécuteur privé éphémère Phase 8'
type: 'feature'
created: '2026-08-20'
status: 'in-review'
baseline_commit: '175f1f7a4785145e5d91878d5728cc52a4422b29'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/specs/spec-private-corpus-access/SPEC.md'
  - '{project-root}/_bmad-output/specs/spec-private-corpus-access/private-access-protocol.md'
  - '{project-root}/_bmad-output/specs/spec-private-corpus-access/verification-and-git-guardrails.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Les validations réelles ont besoin de logs de combat privés, mais
`gw2agent`, les panes Herdr et les worktrees ne doivent jamais y accéder par
défaut. Aucun mécanisme exécutable et vérifiable ne matérialise encore cette
frontière.

**Approach:** Installer un wrapper root-owned invoquable seulement par `roddy`
via sudo, qui valide une requête structurée à usage unique et démarre une unité
systemd éphémère. Elle monte un corpus synthétique de test en lecture seule,
dans son namespace, et n'exécute que trois profils fermés.

## Boundaries & Constraints

**Always:** Préserver `WvW/` sans lecture, énumération, déplacement,
modification ni permission; utiliser seulement un corpus synthétique hors
dépôt; `subset` est le défaut et `full` exige le jeton de confirmation explicite
prévu; refuser argv libre, shell, `bash -c`, worktree non enregistré et profil
inconnu; exécuter sous `gw2agent` avec groupe de lecture supplémentaire présent
seulement dans l'unité; monter les données read-only sous `/run`; journaliser
seulement les métadonnées non sensibles; supprimer runtime et autorisation sur
succès, erreur, annulation et reboot.

**Ask First:** Toute installation ou modification hors des trois artefacts
root-owned explicitement listés, toute permission sur le corpus réel, toute
migration de WvW, tout premier accès réel, toute nouvelle commande autorisée,
ou toute sortie qui pourrait contenir des données privées.

**Never:** ACL permanente ou appartenance permanente de `gw2agent` au groupe
privé; montage dans dépôt/worktree ou pane Herdr; copie persistante; profil
générique; GitHub, stash ou gouvernance Git/GitHub.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|---------------------------|----------------|
| subset | demande `subset`, sélection synthétique opaque, profil connu | unité isolée lit seulement la sélection et retourne un résumé non sensible | jeton consommé et runtime supprimé |
| full | demande `full` avec confirmation explicite | unité isolée lit le corpus synthétique entier read-only | refus sans confirmation `full` |
| refus | profil, worktree, référence ou argument non conforme | aucune unité ni montage; audit minimal | code d'erreur générique, sans chemin ni nom de fichier |
| interruption | timeout, kill ou échec du profil | arrêt de l'unité et retrait du runtime | aucune reprise automatique |

</frozen-after-approval>

## Code Map

- `scripts/ei-parity/ei_diff.py` -- dépend aujourd'hui d'un corpus et d'un préflight full; fournir une entrée explicite subset sans rapport persistant.
- `libs/gw2_evtc_parser/src/gw2_evtc_parser/__main__.py` -- CLI existante; profils privés construisent son argv et n'exposent pas `inspect-zip` ou `dump-agents`.
- `tests/scripts/test_agentic_infrastructure.py` -- garde-fous documentaires existants à étendre sans données réelles.
- `.gitignore` -- ignore déjà certains artefacts EI; compléter plus tard, sans la traiter comme barrière suffisante.

## Tasks & Acceptance

**Execution:**
- [ ] `ops/private-corpus/` -- ajouter les sources versionnées : schéma de requête, registre privé de test, profils fermés, wrapper et template systemd.
- [ ] `tools/install-private-corpus-executor.sh` -- installer de façon idempotente les trois artefacts root-owned autorisés : wrapper, template système et règle sudo limitée à `roddy`.
- [ ] `scripts/ei-parity/ei_diff.py` -- accepter un répertoire/manifest explicitement injecté et permettre une validation subset sans préflight full ni sortie persistante.
- [ ] `tests/private_corpus/` -- créer corpus, sélection, autorité et runner synthétiques; vérifier refus, subset, full, lecture seule, isolation, nettoyage et redaction.
- [ ] `tests/scripts/test_agentic_infrastructure.py` et documentation Phase 8 -- verrouiller les invariants, profils et chemins runtime sans révéler de donnée réelle.

**Acceptance Criteria:**
- Given `gw2agent` hors unité, when it sonde le corpus synthétique, then l'accès est refusé et aucun runtime privé n'est visible.
- Given une autorisation subset valide, when le profil `parser-validation-readonly` s'exécute, then seule la sélection est lisible et toute écriture échoue.
- Given une demande full sans confirmation explicite, when le wrapper la valide, then aucune unité n'est créée; with confirmation explicite, then le profil fermé s'exécute sur le corpus synthétique entier.
- Given un profil inconnu, argv libre, shell, worktree hors registre ou jeton réutilisé, when le wrapper reçoit la demande, then il échoue avant tout montage.
- Given fin, erreur, timeout ou reboot simulé, when l'exécution s'arrête, then montage, runtime, sortie brute et autorisation sont absents.
- Given le profil EI subset, when il reçoit un chemin et manifeste synthétiques injectés, then il n'exige pas le corpus complet et conserve ses rapports détaillés dans le runtime.

## Design Notes

Profils initiaux : `parser-validation-readonly` exécute des tests parser
ciblés; `ei-parity-readonly` exécute seulement la comparaison EI à entrées et
manifest injectés; `pytest-private-fixture` exécute un sous-ensemble pytest
borné. Les trois profils construisent l'argv eux-mêmes et retournent seulement
un statut et des compteurs non sensibles.

## Verification

**Commands:**
- `uv run pytest tests/private_corpus tests/scripts/test_agentic_infrastructure.py -q` -- attendu : tous les garde-fous synthétiques passent.
- `uv run ruff check ops/private-corpus tools/install-private-corpus-executor.sh scripts/ei-parity/ei_diff.py tests/private_corpus` -- attendu : aucune violation applicable.
- `uv run ruff format --check ops/private-corpus tools/install-private-corpus-executor.sh scripts/ei-parity/ei_diff.py tests/private_corpus` -- attendu : format conforme.

**Manual checks (if no CLI):**
- Sous `roddy`, valider la liste sudo exacte et la création/arrêt d'une unité de test; inspecter uniquement les métadonnées de montage et d'audit synthétiques.

## Statut de clôture Phase 8

**EXPERIMENTAL / NOT OPERATIONAL.** Les contrats, tests locaux et diagnostics
synthétiques sont conservés, mais les essais hôte `subset` et `full` retournent
encore `unit-failed/service`. Ne pas utiliser cet exécuteur avec `WvW/` réel.
Le repli temporaire est l'exécution d'une commande précise sous `roddy` après
autorisation humaine explicite, avec `subset` par défaut, `full` séparément
confirmé, résultat redacted seulement et nettoyage des temporaires.

La reprise future doit d'abord distinguer `systemd-start`, `sandbox-bind`,
`tool-exec` et `profile-exit` avec les seuls statut et code retour redacted,
puis satisfaire les critères de passage à OPERATIONAL du checkpoint Phase 8.
Le statut `in-review` signifie que cette base n'est pas un livrable accepté ni
une autorisation d'intégration opérationnelle.
