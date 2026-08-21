# Checkpoint historique — Phase 8 : prérequis d'environnement

> Ce checkpoint couvre uniquement la reprise initiale de `uv`. Son état courant
> est consolidé dans `phase8-final-checkpoint-2026-08-21.md` : l'exécuteur
> privé est **EXPERIMENTAL / NOT OPERATIONAL** et le repli humain `roddy` est
> le mécanisme temporaire autorisé.

> **EXPERIMENTAL / NOT OPERATIONAL — DO NOT USE WITH REAL PRIVATE CORPUS**

## Statut

Phase 8, Level 1. Reprise limitée aux validations précédemment bloquées par
l'absence de `uv` et à la documentation du prérequis correspondant. Aucune
étape de Git/GitHub Governance n'est commencée.

## Décisions conservées

- `uv 0.12.5`, fourni par `mise` sous l'environnement `gw2agent`, est un
  prérequis pour exécuter les outils Python du dépôt avec `uv run`.
- Le sandbox Codex peut refuser l'accès au socket Herdr. Les contrôles read-only
  de disponibilité Herdr sont effectués hors sandbox sous `gw2agent`. Ce refus
  ne signale pas un échec de Herdr et ne modifie pas les limites Level 1.

## Validations reprises

| Validation | État | Preuve |
| --- | --- | --- |
| Disponibilité `uv` | PASS | `uv 0.12.5 (x86_64-unknown-linux-musl)` |
| Tests d'infrastructure agentique et du framework BMAD | PASS | `uv run pytest tests/scripts/test_agentic_infrastructure.py tests/scripts/test_bmad_framework.py --tb=short -q` : 11 tests |
| Ruff ciblé | PASS | `uv run ruff check tests/scripts/test_agentic_infrastructure.py tests/scripts/test_bmad_framework.py` |
| Format Ruff ciblé | PASS | `uv run ruff format --check tests/scripts/test_agentic_infrastructure.py tests/scripts/test_bmad_framework.py` : 2 fichiers déjà formatés |

La première tentative dans le sandbox Codex a été bloquée seulement parce que
`uv` ne pouvait pas créer son cache dans `/home/gw2agent/.cache/uv`. Les mêmes
validations ont donc été exécutées hors sandbox sous `gw2agent`, où `uv` a créé
l'environnement requis et elles ont passé.

## Périmètre explicitement non touché

- `WvW/` n'a pas été ouvert, énuméré, indexé, déplacé, modifié ou ajouté à Git.
- Aucun stash n'a été consulté ou modifié.
- Aucune configuration GitHub ni activité Git/GitHub Governance n'a été
  commencée.

## Décision ultérieure consignée

Le mainteneur a ensuite approuvé une implémentation synthétique de la cible
« corpus maître + exécuteur privé éphémère ». Les artefacts obtenus sont
conservés pour reprise, mais aucun accès réel, migration de `WvW/`, changement
de permission du corpus maître ni activité Git/GitHub n'est autorisé par ce
checkpoint.
