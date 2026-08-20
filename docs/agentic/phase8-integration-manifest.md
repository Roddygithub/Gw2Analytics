# Manifeste d'intégration — Phase 8

> **EXPERIMENTAL / NOT OPERATIONAL — DO NOT USE WITH REAL PRIVATE CORPUS**

Ce manifeste définit le seul périmètre autorisé d'un futur commit Phase 8. Il
préserve les sources de reprise et exclut les données, installations et runtime
locaux. Il ne rend pas l'exécuteur opérationnel et n'autorise aucun accès réel.

## Fichiers suivis modifiés

- `docs/agentic/README.md`
- `docs/agentic/backlog.md`
- `docs/agentic/current-state.md`
- `scripts/ei-parity/ei_diff.py`
- `tests/scripts/test_agentic_infrastructure.py`

## Artefacts expérimentaux à versionner

- `ops/private-corpus/README.md`
- `ops/private-corpus/contract.json`
- `ops/private-corpus/executor.py`
- `ops/private-corpus/gw2analytics-private-corpus.sudoers`
- `ops/private-corpus/gw2analytics-private-corpus@.service`
- `ops/private-corpus/private-test-registry.json`
- `tools/install-private-corpus-executor.sh`
- `tests/private_corpus/test_executor_contract.py`
- `tests/private_corpus/test_mounted_input.py`
- `docs/agentic/phase8-environment-prerequisites-2026-08-20.md`
- `docs/agentic/phase8-final-checkpoint-2026-08-21.md`
- `docs/agentic/private-corpus-executor.md`
- `_bmad-output/implementation-artifacts/spec-phase8-private-corpus-executor.md`
- `_bmad-output/specs/spec-private-corpus-access/SPEC.md`
- `_bmad-output/specs/spec-private-corpus-access/private-access-protocol.md`
- `_bmad-output/specs/spec-private-corpus-access/verification-and-git-guardrails.md`

## À ne jamais versionner

- `.memlog.md`, caches Python ou `uv`, outputs de test et instrumentation de
  diagnostic temporaire ;
- jetons, tombstones, diagnostics, stdout/stderr, journaux systemd et runtime ;
- installations hôte sous `/etc`, `/usr/local`, `/run` ou `/var/lib` ;
- registre privé réel, sélections, autorisations et copie UV installée ;
- `WvW/`, logs privés et tout dérivé de combat ou export EI privé.

## Éléments strictement locaux

Le corpus maître, les montages, le repli humain `roddy`, les commandes privées
autorisées par tâche et leurs résultats non redacted demeurent locaux. Ils ne
figurent ni dans le commit, ni dans un pane Herdr, ni dans un handoff.

## Dette de reprise

**Private Corpus Executor Finalization — GPT-5.6 Sol / High** est une tâche
système dédiée, non bloquante pour GW2Analytics. Lors de tout `codex exec
resume`, le Lead réapplique explicitement le modèle et le reasoning effort,
vérifie le runtime observé et s'arrête avant diagnostic en cas de divergence.
