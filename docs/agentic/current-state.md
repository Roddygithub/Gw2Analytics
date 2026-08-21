# État courant agentique

> **EXPERIMENTAL / NOT OPERATIONAL — DO NOT USE WITH REAL PRIVATE CORPUS**

## Phase 8 — clôture Level 1

- **Statut :** décision Phase 8 clôturée au Level 1 ; l'implémentation de
  l'exécuteur privé reste en review expérimentale, **EXPERIMENTAL / NOT
  OPERATIONAL**, et ne doit jamais être utilisée avec `WvW/` réel.
- **Autonomie :** Level 1 pour tous les domaines, inchangé.
- **Confidentialité :** `WvW/` n'a pas été ouvert, énuméré, indexé, déplacé,
  modifié ou ajouté à Git. `gw2agent`, Herdr et les worktrees n'ont aucun
  accès permanent au corpus.
- **Mécanisme temporaire autorisé :** repli humain `roddy`, par tâche
  explicitement approuvée : `subset` par défaut, `full` après confirmation
  distincte, commande précise exécutée sous `roddy`, résultat redacted seul
  partagé avec les agents, puis nettoyage des temporaires.

## Findings consolidés

| Domaine | Statut | Décision opérationnelle |
| --- | --- | --- |
| Routing et rôles | PASS | Lead stable ; séparation intention/autorisation conservée. |
| Worktrees persistants | PASS | Worktrees séparés du corpus ; aucun montage privé persistant. |
| Confidentialité | PASS | Corpus privé absent des accès par défaut et du dépôt. |
| `uv` | PASS | `uv 0.12.5` via Mise est un prérequis `gw2agent`; Python passe par `uv run`. |
| Herdr | PASS avec limite connue | Le socket peut être refusé par le sandbox Codex ; contrôles read-only hors sandbox sous `gw2agent`. |
| Exécuteur privé avancé | EXPERIMENTAL / NOT OPERATIONAL | Sources, contrats et tests synthétiques conservés ; aucun accès réel autorisé. |
| Stash `codex-pre-phase7-main-sync` | ABSENT / NON APPLIQUÉ | Aucun ref `stash` n'est présent lors de ce checkpoint ; aucun patch n'a été appliqué ni inspecté. |

## Validations Phase 8

- PASS — prérequis `uv 0.12.5`, tests d'infrastructure agentique et framework
  BMAD ; voir `phase8-environment-prerequisites-2026-08-20.md`.
- PASS — tests de contrat de l'exécuteur synthétique, garde-fous documentaires,
  Ruff, formatage, syntaxe Bash et `git diff --check`.
- PASS — diagnostics synthétiques root-owned : création atomique, redaction,
  TTL et lecture fermée sous `roddy`.
- PASS — demandes synthétiques `subset` et `full` validées jusqu'à l'étape
  service ; les jetons sont à usage unique.
- NOT OPERATIONAL — l'unité retourne encore `unit-failed/service` pour les
  deux scopes. Son code retour effectif n'est pas suffisamment observé pour
  justifier une nouvelle correction.

## Dette et reprise

Ne pas reprendre le debug systemd sans accord humain explicite. La reprise doit
d'abord ajouter une observabilité fermée distinguant `systemd-start`,
`sandbox-bind`, `tool-exec` et `profile-exit`, avec seulement
`ExecMainStatus`, code retour et profil logique redacted. Elle devra ensuite
prouver en live synthétique namespace, bind UV root-owned, `.venv`, cache,
lecture seule, nettoyage succès/échec/interruption et reboot avant tout accès
réel.

Les artefacts expérimentaux ne sont pas recommandés pour intégration
opérationnelle tant que les tests live et les garde-fous de l'exécuteur ne sont
pas satisfaits. Leur présence non suivie est volontaire à ce stade : une future
décision d'intégration devra examiner explicitement leur inventaire et les
findings de review.

Le checkpoint détaillé est
`phase8-final-checkpoint-2026-08-21.md`. Git/GitHub Governance & Delivery
Architecture reste non commencée.
