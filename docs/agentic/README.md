# Travailler sur GW2Analytics

Herdr + Codex sont le workflow principal. Démarrez la session à la racine puis dites
`Continue GW2Analytics`. Herdr conserve la session; Codex est le Lead, choisit la
prochaine tâche sûre, délègue, valide et garde un handoff court (objectif, chemins,
contraintes, validation, résultat). OpenCode n'est pas un second orchestrateur.

Chaque sous-tâche est reclassifiée : Luna (`none`/`low`) pour recherche, tests et
travail mécanique; Terra (`medium`, puis `high`/`xhigh`) pour développement normal;
Sol seulement pour architecture ou risque exceptionnel. Les efforts réels sont
`none`, `low`, `medium`, `high`, `xhigh`, `max`; `pro` est distinct. On augmente
d'abord le reasoning, puis le modèle si nécessaire, et on redescend immédiatement
pour la tâche suivante. BMAD est optionnel, réservé aux changements transverses.

Les protections restent normales : pas de secrets ni de données locales dans Git,
pas de root arbitraire, pas d'opération destructive non confirmée. `WvW/` peut être
analysé localement pour le développement, les tests et les validations sans nouvelle
autorisation humaine, mais jamais versionné ou exfiltré. Les executors
Private Corpus et Root Admin ont été retirés. Reprenez le produit via
`docs/ROADMAP.md`, les SPEC actives et les tests/CI.

Le Lead applique **Continuous Execution** : un checkpoint n'est pas une fin de
mission. Tant qu'une étape sûre reste exécutable, il enchaîne automatiquement la
suivante; il ne rend la main que pour un blocage démontré, une permission/TTY
inaccessible ou une décision destructive/externe.

## Lifecycle GW2Analytics

`gw2a` crée une entrée fraîche dans Herdr sous `gw2agent`; elle ne rattache jamais
silencieusement une session déjà active.

- `gw2a` : démarrer une session arrêtée.
- `exit` : arrêter la session GW2Analytics et revenir au shell roddy qui a
  lancé `gw2a`.
- `Ctrl+Space`, puis `d` : détacher le client Herdr tout en laissant la session
  et ses panes tourner.
- `gw2a status` : afficher l’état Herdr, l’identité, les groupes et Docker.
- `gw2a stop` : arrêter la session avec Herdr.
- `gw2a restart` : arrêter la session avec Herdr puis en créer une fraîche.

Si `gw2a` signale une session active, utilisez `gw2a status` ou `gw2a restart`.
Depuis une session déjà exécutée sous `gw2agent`, `gw2a` répond
`Already inside GW2Analytics` et ne lance pas sudo.
