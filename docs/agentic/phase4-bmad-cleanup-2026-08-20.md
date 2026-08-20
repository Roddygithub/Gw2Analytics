# Phase 4 — Nettoyage contrôlé BMAD (2026-08-20)

## Statut

Terminé comme livrable candidat à intégration, au **Level 1**. Cette phase
reconfigure l'intégration agentique et sa documentation ; elle ne modifie aucun
code applicatif, aucune CI, aucun contrat API, aucune donnée ni aucune stratégie
Git/GitHub. La review indépendante finale est **CLEAN**.

## Décisions d'inventaire

| Statut | Éléments | Décision |
| --- | --- | --- |
| CONSERVER | `_bmad/` et les 49 skills `.agents/skills/bmad-*`, tests `tests/scripts/test_bmad_framework.py`, SPEC dans `_bmad-output/specs/`, ADR | BMAD 6.11.0 reste l'installation canonique ; les SPEC et ADR valides gardent leur rôle. |
| ADAPTER | manifeste BMAD, `AGENTS.md`, test de frontmatter, exclusions Ruff, documentation de priorité | Codex est l'intégration active ; la mémoire durable est versionnée dans le dépôt. |
| SUPPRIMER | `.opencode/commands/` (49 wrappers), `opencode.json`, exclusion Ruff `.opencode`, sauvegarde non suivie créée par l'installeur, `docs/supermemory-export.md` | Aucun consommateur actif ne les référençait après régénération Codex ; l'archive Supermemory ne contient aucun savoir durable unique non sensible. |
| INVESTIGUER | `docs/agentic/audit-proposal-2026-08-20.md`, chemins historiques `/tmp/opencode` de l'outillage EI, fichier suivi `=690` | L'audit brut reste non suivi et ne doit pas être ajouté tel quel. Les chemins EI et `=690` ne sont pas une intégration agentique et leur modification serait hors périmètre. |

## Actions effectuées

1. Régénération officielle, épinglée et non interactive :
   `npx --yes bmad-method@6.11.0 install --directory /home/roddy/Projects/Gw2Analytics --action update --modules bmm --tools codex --yes`.
2. Le manifeste BMAD déclare désormais uniquement `codex`; core et bmm restent
   en version 6.11.0. L'installeur a régénéré les skills canoniques et supprimé
   les wrappers OpenCode.
3. `AGENTS.md` décrit maintenant Codex, les checkpoints versionnés, Supermemory
   comme facultatif, et la confidentialité du corpus local `WvW/`.
4. `docs/ROADMAP.md`, `BACKLOG.md`, `SESSION.md`, `AUDIT_COMPLET.md`, les index
   `plans/` et `advisor-plans/` sont clairement signalés comme historiques
   lorsqu'ils ne constituent pas un état courant.

## Sources de vérité après nettoyage

1. comportement livré : code, tests et CI ;
2. contrat à construire : SPEC acceptées sous `_bmad-output/specs/` ;
3. décisions d'architecture : `docs/adr/` ;
4. reprise opérationnelle : checkpoints assainis dans `docs/agentic/`.

Au Level 1, les documents historiques ne déclenchent aucune exécution : toute
priorité nouvelle nécessite une proposition et l'accord du mainteneur.

## Validation

| Vérification | Résultat |
| --- | --- |
| `uv run pytest tests/scripts/test_bmad_framework.py` | PASS — 7 tests |
| `uv run ruff check tests/scripts/test_bmad_framework.py` | PASS |
| `git diff --check` | PASS |
| `resolve_config.py` | PASS — Gw2Analytics, 5 agents BMAD résolus |
| `resolve_customization.py` sur `bmad-build` | PASS |
| manifeste BMAD | PASS — `ides: [codex]`, 49 skills |
| tests applicatifs/Docker | NOT RUN — hors périmètre de configuration Phase 4 |

## Corrections après review indépendante

1. Ce checkpoint fait partie du livrable Phase 4 et est préparé pour être
   versionné ; il ne contient ni export Supermemory, ni donnée du corpus privé.
2. `docs/supermemory-export.md` a été relu sans accéder à `WvW/` :
   - les quelques invariants non sensibles qu'il rappelait sont déjà couverts
     par `AGENTS.md`, les SPEC/ADR et les tests ; aucun transfert n'est requis ;
   - son historique de sessions, ses états de travail et ses chemins sont
     redondants ou obsolètes ;
   - les identifiants et informations privées non nécessaires sont éliminés en
     supprimant l'archive entière ;
   - aucun élément à provenance ou nécessité ambiguë n'a été identifié.
3. Les tests framework vérifient désormais le manifeste `ides: [codex]`,
   l'inventaire stable des 49 skills Codex générés par BMAD 6.11.0 et l'absence
   d'une configuration OpenCode active. Ils évitent les détails volatils du
   contenu généré.
4. Après ces corrections : test framework (7 PASS), lint ciblé, résolveurs de
   configuration et de personnalisation, et `git diff --check HEAD` sont tous
   PASS.
5. Review indépendante finale : **CLEAN**, sans finding BLOCKER/HIGH/MEDIUM/LOW.
   Elle confirme la fermeture des trois findings initiaux, l'absence de contenu
   privé versionné et l'absence de changement runtime, API, données, CI, GitHub,
   SPEC ou ADR.

## Garde-fous

- Aucun contenu de `WvW/` n'a été ouvert, modifié, ajouté à Git, déplacé ou
  supprimé. Lors du contrôle final, une commande de statut trop large a
  involontairement énuméré des chemins non suivis sous `WvW/` : incident de
  confidentialité consigné ; ne pas répéter cette indexation.
- Aucun commit, push, PR ou merge n'a été créé.
- `docs/agentic/audit-proposal-2026-08-20.md` reste non suivi. Son contenu
  utile devra être synthétisé et assaini dans les documents agentiques de la
  Phase 5, jamais copié aveuglément ni publié comme état courant.
- La Phase 5 (infrastructure agentique) exige une autorisation explicite.
