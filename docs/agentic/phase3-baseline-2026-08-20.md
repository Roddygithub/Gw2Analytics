# Phase 3 — Baseline (arrêt sur divergence) — 2026-08-20

## Cadre

- Autorisation : Phase 3 uniquement, autonomie Level 1.
- Commit de base gelé : `89b47ec3f7b4bb90a5c01793be893d172fb1ce17`
  (`main` et `origin/main` au démarrage).
- Aucun commit, push, PR, changement de stratégie Git/GitHub, nettoyage BMAD ou
  Phase 4. Les seules modifications de code autorisées ensuite sont les corrections
  ESLint locales décrites ci-dessous.
- Le corpus local non suivi sous `WvW/` a été préservé et n'a pas été ouvert,
  parsé, copié ni inclus dans ce rapport.

## Inventaire et prérequis

- État Git initial : aucun diff suivi ; corpus `WvW/` non suivi et préexistant ;
  `docs/agentic/` non suivi et préexistant.
- Toolchains restaurées conformément aux voies documentées :
  - `uv 0.12.5`, installateur officiel Astral ; CPython `3.12.14` géré par uv.
  - `pnpm 11.22.0`, majeur 11 conforme au composite CI.
- Synchronisations verrouillées réussies :
  - `uv sync --frozen --all-packages` — 148 paquets, 5.5 s environ.
  - `pnpm install --frozen-lockfile` — lockfile validé, 5.3 s environ.
- Docker est installé (`29.7.2`) mais le socket local est inaccessible à cette
  session : propriétaire/groupe `nobody:nobody`, alors que l'utilisateur courant
  n'appartient pas à ce groupe. C'est un blocage d'environnement pour les services,
  pas un diagnostic applicatif.

## GitHub et PR

- PR [#248](https://github.com/Roddygithub/Gw2Analytics/pull/248) : ouverte,
  non brouillon, base `89b47ec`, tête `6f88500cd4d29c2e0943d6877b55af08a68cf5b5`,
  état GitHub `clean` et fusionnable au moment du relevé.
- Aucun changement distant effectué.

## Validations exécutées

| Palier | Commande | Résultat | Durée approximative |
|---|---|---|---:|
| Lint Python | `uv run ruff check --output-format=concise` | succès | 5.2 s (avec format) |
| Format Python | `uv run ruff format --check` | succès, 354 fichiers | 5.2 s (avec lint) |
| Garde SQLAlchemy | absence de `db.query(` dans `apps/api/src`, `libs` | succès | 0.1 s |
| Type-check Python | `uv run mypy libs --no-incremental` puis API | succès, 96 + 68 sources | 21.4 s |
| Audit Python | `uv run pip-audit --strict ...` (exceptions CI) | succès, aucune sortie de vulnérabilité | ~32 s |
| Tests ciblés scripts | `uv run pytest tests/scripts/ --tb=line -q` | succès, 64 tests | 5.6 s |
| Dérive OpenAPI | génération dans `/tmp`, puis `diff` avec le client suivi | succès, aucune dérive | 4.3 s |
| Type-check web (initial) | `pnpm typecheck` | succès | inclus ci-dessous |
| Lint web (initial) | `pnpm lint` | échec : 23 erreurs, 18 avertissements | 12.8 s (avec type-check) |

La première tentative de génération OpenAPI a été exécutée depuis la racine et
`pnpm exec` l'a refusée car le package se trouve sous `web/`. Elle a été relancée
depuis le répertoire explicitement imposé par la CI et a réussi ; il s'agit d'une
erreur de contexte de commande, pas d'une divergence du dépôt.

## Correction ciblée autorisée — Level 1

Le mainteneur a ensuite autorisé uniquement la correction des erreurs ESLint
purement mécaniques, sans changement fonctionnel, refactoring ni modification de
CI. Les fichiers corrigés sont tous suivis par Git ; `WvW/` n'a pas été ouvert,
lu, modifié, déplacé, indexé ou ajouté. Aucun autre chemin non suivi n'a été
modifié, à l'exception de la présente mise à jour de checkpoint autorisée.

### Corrections mécaniques appliquées (11 erreurs)

- `web/src/app/fights/[id]/page.tsx` : retrait de cinq imports/types/constantes
  inutilisés.
- `web/src/components/CreateWebhookPanel.tsx` : retrait du type `Phase` inutilisé.
- `web/src/components/FightSummaryCards.tsx` : retrait de la prop inutilisée
  `valueFormatter` de `SummaryPlayerRow`; le formatage reste effectué par
  `SummaryCard` avant l'appel du composant.
- `web/src/components/PlayerPositionHeatmap.tsx` : retrait de l'import
  `FALLBACK_COLOR` inutilisé.
- `web/src/components/TimelineChart.tsx` : retrait de la constante inutilisée
  `BUTTON_STYLE`.
- `web/src/lib/fetchCached.ts` : commentaire dans le `catch` de parsing JSON ; le
  fallback sur le texte de réponse est inchangé.
- `web/tests/setup.ts` : renommage du paramètre de shim inutilisé en `_obj`.

### Erreurs React initialement à décision fonctionnelle/architecturale (12)

Aucune de ces erreurs n'a été modifiée : les corriger impose de restructurer les
hooks ou le flux d'état, avec un risque de changement de comportement.

- `web/src/app/fights/compare/page.tsx` : 2 mises à jour synchrones de l'état
  dans les effets de chargement A/B.
- `web/src/components/LazyTabbedTimelineSection.tsx` : 1 mise à jour synchrones
  de l'état dans un effet.
- `web/src/components/PlayerPositionGrid.tsx` : 1 appel de chargement depuis un
  effet qui met l'état à jour de façon synchrone.
- `web/src/components/PlayerPositionHeatmap.tsx` : 3 mises à jour synchrones de
  l'état dans des effets et 1 callback `draw` auto-référencée avant déclaration.
- `web/src/components/ReadoutTabClient.tsx` : 3 `useMemo` conditionnels (ordre
  des hooks) et 1 chargement depuis un effet avec mise à jour synchrone.

Le mainteneur a ensuite autorisé leur traitement local après analyse de chaque
composant. Les corrections appliquées préservent les états de chargement, d'erreur,
l'annulation des requêtes périmées et l'affichage attendu :

- `fights/compare/page.tsx` : chaque colonne de combat est isolée dans un enfant
  cléé par son identifiant ; son état initial remplace les remises à zéro
  synchrones dans l'effet.
- `LazyTabbedTimelineSection.tsx`, `PlayerPositionGrid.tsx` et
  `ReadoutTabClient.tsx` : même principe, avec un enfant cléé par les paramètres
  de chargement et un effet réservé aux résolutions/rejets asynchrones.
- `PlayerPositionHeatmap.tsx` : chargement, autoplay et arrêt de l'animation sont
  déclenchés depuis les callbacks asynchrones ou `requestAnimationFrame`; la
  référence de dessin est stabilisée par un ref. L'autoplay immédiat de deux
  secondes est le comportement voulu.
- `ReadoutTabClient.tsx` : les trois `useMemo` sont désormais toujours appelés,
  avec un tableau vide stable lorsque les données sont absentes.

Le test `player-position-heatmap` a été adapté uniquement de `Lecture` vers
`Pause` après le chargement, conformément à cet autoplay déjà documenté et au
test voisin qui le vérifie.

### Validation de la correction ciblée

| Commande | Résultat |
|---|---|
| `git diff --check` | succès |
| `pnpm lint` | **échec contrôlé : 12 erreurs restantes, 18 avertissements** ; les 11 erreurs mécaniques ne réapparaissent pas |
| `pnpm typecheck` | succès |
| `pnpm vitest run tests/lib/fetchCached.test.ts tests/lib/fetchCached-isolation.test.ts tests/app/fights-page.test.tsx tests/components/CreateWebhookPanel.test.tsx` | succès : 4 fichiers, 27 tests |
| `pnpm vitest run tests/components/player-position-heatmap.test.tsx tests/components/ReadoutTabClient.test.tsx` | succès : 15 tests |
| `pnpm lint` après toutes corrections | succès : 0 erreur, 16 avertissements préexistants/non bloquants |
| `pnpm typecheck` après toutes corrections | succès |
| `pnpm test:unit` | succès : 54 fichiers, 379 tests, 3 ignorés |
| `pnpm audit --audit-level=high` | succès : aucune vulnérabilité connue |
| `pnpm build` sans configuration de production | échec attendu : `API_BASE_URL` requise |
| `API_BASE_URL=http://api:8000 NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 pnpm build` en exécution isolée | **NOT RUN / limite d'environnement** : l'isolation interdit à Node de créer le sous-processus `tsc`, puis Next reçoit une sortie vide |
| même commande avec l'autorisation d'exécution nécessaire | succès : build Next.js complet, génération des 7 pages statiques terminée |
| `git diff --check` final | succès |

La suite web émet des avertissements non bloquants de test concernant `act(...)`
et le contexte canvas non implémenté dans jsdom. Les assertions passent ; ces
avertissements ne sont pas traités pendant la baseline car ils ne constituent ni
une erreur ESLint ni une régression démontrée.

ESLint est désormais vert. La divergence de couverture CI reste cohérente avec le
drift déjà relevé : le workflow
`.github/workflows/ci.yml` exécute le type-check, les tests et l'audit web, mais
pas `pnpm lint`, alors que `README.md` prescrit ce lint. Cela explique qu'une CI
verte ne prouvait pas auparavant le lint local. La couverture ESLint de la CI doit
être traitée dans sa phase dédiée ; la CI n'a pas été modifiée pendant cette
Phase 3.

## Diagnostic ciblé — build Next.js / TypeScript

Le premier échec de build reste une précondition de production documentée :
`API_BASE_URL` doit être définie. La seconde erreur observée est désormais
expliquée et ne provient ni du code applicatif ni de `tsconfig.json`.

- Versions effectives : Node `v26.7.0`, pnpm `11.22.0`, Next.js `16.3.0` et
  TypeScript `5.9.3` (verrouillé par `web/pnpm-lock.yaml`). Le package Next
  déclare Node `>=20.9.0`; aucune incompatibilité de versions n'a été observée.
- `web/package.json` lance exactement `next build`; `web/tsconfig.json` et
  `web/next.config.ts` étaient inchangés. La sortie directe de
  `pnpm exec tsc --showConfig --project tsconfig.json --pretty false` fait
  9 247 octets, est du JSON valide et se termine avec le code `0`.
- Le traceur de processus confirme que Next exécute
  `node <typescript>/bin/tsc --showConfig --project <web>/tsconfig.json --pretty false`.
  Dans l'exécution isolée, la création d'un sous-processus par Node est refusée
  (`EPERM`). Une sonde minimale `child_process.spawnSync(node, ['-e', ...])`
  retourne ce même `EPERM`; le processus enfant asynchrone ne fournit alors ni
  stdout ni stderr. Next tente donc de parser une chaîne vide et son erreur a pour
  cause `SyntaxError: Unexpected end of JSON input`.
- Avec les valeurs non sensibles documentées
  `API_BASE_URL=http://api:8000` et
  `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`, la même commande exécutée
  hors de cette restriction termine avec succès (compilation, type-check,
  collecte des données et génération statique). Elle démontre que le build est
  vert dans un environnement autorisant les sous-processus Node.
- La CI web configure Node 22 et pnpm 11; le Dockerfile de production construit
  également avec Node 22. Le job `lint-web` de CI n'exécute cependant pas
  `pnpm build` : il vérifie seulement le type-check, les tests et l'audit. Cette
  différence ne permet donc pas d'affirmer ici le résultat d'un build Next sur
  GitHub Actions.

Correction minimale recommandée : **aucun patch du dépôt**. Exécuter le build
dans un environnement qui autorise les sous-processus Node (CI, Docker lorsque le
socket est disponible, ou une exécution locale non isolée) est la seule action
requise. Risque fonctionnel : nul; aucun code, configuration, lockfile ou CI n'a
été modifié. Le build dans l'isolation restrictive est classé `NOT RUN` plutôt
que `FAIL` applicatif.

## Non exécuté après arrêt

- build API ;
- suite Python complète ;
- démarrage des services Docker, migrations Alembic et test de migration ;
- Playwright, builds Docker, parité Elite Insights et tout accès au corpus privé.

Les validations dépendantes de Docker restent impossibles : Docker est installé,
mais son socket est inaccessible à cette session (propriétaire/groupe
`nobody:nobody`, utilisateur courant hors de ce groupe). Aucune tentative de
contournement ni modification d'environnement n'a été faite.

## État de reprise

- Modifications suivies non commitées : 12 fichiers web (les sept fichiers
  mécaniques, les cinq composants/pages React corrigés et le test Heatmap).
  Aucun commit, push, PR ou ajout à l'index.
- Revue du diff final : les changements se limitent au retrait des symboles
  inutilisés, à l'isolation cléée des états de chargement, à l'ordre inconditionnel
  des hooks et à l'assertion d'autoplay autorisée ; aucun changement métier,
  d'API, de données ou de CI n'a été identifié.
- Fichier de checkpoint non suivi mis à jour :
  `docs/agentic/phase3-baseline-2026-08-20.md`.
- Les artefacts locaux de dépendances (`.venv`, `web/node_modules`) et sorties
  temporaires `/tmp` ne sont pas des modifications suivies du projet.
- Phase 3 reste en attente de la décision du mainteneur : les validations
  applicatives et ESLint sont vertes et le build web est validé hors de
  l'isolation restrictive. Aucun correctif de build ni Phase 4 ne doit être
  engagé sans autorisation explicite. Aucune consultation Sol n'est nécessaire :
  le diagnostic confirme une limite d'exécution, non une question architecturale
  ou métier.

## Bilan final consolidé — validation du mainteneur

Le mainteneur valide le diagnostic Next.js/TypeScript et classe le build isolé
comme une limitation d'environnement. La partie web de la baseline est donc
validée pour les contrôles exécutables dans cette session. Cette section est le
checkpoint de clôture de la Phase 3; elle n'autorise pas la Phase 4.

### PASS

- synchronisations verrouillées Python et web;
- Ruff, format Python, garde SQLAlchemy, mypy, audit Python, tests de scripts et
  absence de dérive OpenAPI;
- ESLint web : 0 erreur (16 avertissements non bloquants);
- typecheck web;
- tests web ciblés : 15 tests, puis suite complète : 54 fichiers, 379 tests,
  3 ignorés;
- audit pnpm : aucune vulnérabilité connue;
- build Next.js complet avec les variables de production documentées, dans une
  exécution autorisant les sous-processus Node;
- `git diff --check`.

### FAIL réel

Aucun échec applicatif ou de validation reproductible ne reste ouvert dans le
périmètre exécuté. Le premier `pnpm lint` historique (23 erreurs) et l'assertion
Heatmap incohérente ont été résolus pendant cette Phase 3 et ne constituent pas
des échecs finaux.

### NOT RUN — limitation d'environnement

- build Next.js dans l'isolation restrictive : Node ne peut pas créer le
  sous-processus TypeScript (`EPERM`); le build est validé hors de cette limite;
- services Docker, migrations Alembic, test de migration, builds Docker : socket
  Docker inaccessible à cette session;
- Playwright et parité Elite Insights : non lancés, car ils dépendent de services
  ou du corpus privé que la Phase 3 ne doit pas ouvrir;
- build API et suite Python complète : non lancés après les arrêts Level 1
  précédents; ils restent des validations à programmer dans un environnement
  approprié, pas des échecs connus.

### Modifications applicatives de Phase 3

- retrait de 11 violations ESLint mécaniques (symboles/props/styles inutilisés,
  paramètre de mock, commentaire de fallback);
- correction locale de 12 violations React : états de chargement initialisés via
  composants cléés, effets limités aux retours asynchrones, hooks inconditionnels,
  animation Heatmap stabilisée;
- mise à jour ciblée du test Heatmap pour l'autoplay immédiat de deux secondes
  explicitement validé par le mainteneur.

Ces modifications sont non commitées et ont été couvertes par lint, typecheck,
tests ciblés et suite web complète.

### Gouvernance et CI à traiter ultérieurement

- le workflow CI web ne lance pas ESLint alors que le README le prescrit;
- le CI ne lance pas `pnpm build`, donc le build Next doit être couvert par une
  étape dédiée dans une phase de gouvernance distincte;
- les avertissements de test jsdom (`act(...)` et canvas) restent non bloquants
  et hors du périmètre de correction Phase 3.

### Confidentialité

`WvW/` est toujours non suivi, n'a été ni ouvert, ni lu, ni indexé, ni modifié.
Le checkpoint est le seul fichier non suivi modifié dans `docs/agentic/`.
Les validations EI et tout corpus privé restent explicitement non exécutés.

### État Git de clôture

- base auditée : `89b47ec3f7b4bb90a5c01793be893d172fb1ce17`;
- 12 fichiers web suivis modifiés, non indexés et non commités;
- chemins non suivis préservés : `WvW/` et `docs/agentic/`;
- aucun commit, push, PR, ajout à l'index ou changement CI/GitHub.

### Recommandation Phase 4

Après autorisation explicite, commencer par le nettoyage BMAD approuvé dans le
plan de migration, puis installer l'infrastructure agentique de façon
progressive. Conserver les contrôles web validés comme prérequis et planifier
séparément la couverture CI ESLint/build ainsi que les validations Docker,
migrations et parité EI dans un environnement disposant des services et du
corpus autorisés. Ne pas intégrer les modifications web de Phase 3 avant une
revue indépendante et une décision de commit/PR du mainteneur.

## Revue indépendante read-only — en attente de résolution

Deux Reviewers Terra High indépendants des Implementers ont relu le diff des
12 fichiers web sans modifier le dépôt. La couche `verification-gap` BMAD n'a
pas pu être lancée : la limite de threads du harness était atteinte. Cette
limite réduit la couverture de revue, mais n'est pas un finding de code.

### Findings triés

- **Moyen — réinitialisation de l'onglet Readout lors d'un changement de combat**
  (`web/src/components/ReadoutTabClient.tsx:504-505`). Le nouveau `key={fightId}`
  remonte tout le composant et remet `activeTableTab`, filtres et états de tri à
  leurs valeurs initiales. L'ancien composant conservait ces interactions pendant
  le rechargement. Le diff Phase 3 visait uniquement ESLint : préserver cet état
  est la correction attendue avant intégration.
- **Moyen — réinitialisation de l'onglet Timeline lors d'un changement de fenêtre**
  (`web/src/components/LazyTabbedTimelineSection.tsx:103-110`).
  `key={fightId}:${windowS}` remonte `PerFightTimelineSection`; un analyste peut
  donc perdre son onglet actif quand il change la fenêtre temporelle. L'ancien
  effet ne réinitialisait que la requête; préserver l'interaction est requis.
- **Faible — effet de bord dans un updater d'état Heatmap**
  (`web/src/components/PlayerPositionHeatmap.tsx:146-153`).
  `setPlaying(false)` est appelé depuis l'updater de `setCurrentTime`. Les
  updaters devraient rester purs, même si l'appel est idempotent. Correction
  locale et non ambiguë à prévoir avec les deux findings moyens.

### Points non bloquants / différés

- La minuterie d'autoplay peut aussi arrêter une lecture reprise manuellement
  avant son expiration. Ce comportement existait avant le diff Phase 3 : il est
  réel mais non causé par cette baseline.
- La capture initiale de `positionsData`, les requêtes non annulées et les retries
  canvas non annulés existaient également avant les corrections; ils ne sont pas
  des régressions introduites ici.
- Les tests passent, mais il manque des tests explicites de conservation des
  interactions lors des remounts cléés; ils devront accompagner les corrections
  des deux findings moyens.

Verdict de revue : **non approuvée pour intégration telle quelle**. Aucun risque
haut, aucune modification API/données/CI, mais les deux réinitialisations UX
contredisent l'objectif de correction ESLint minimale. Aucun finding n'a été
corrigé; commit, PR et Phase 4 restent interdits jusqu'à décision du mainteneur.

### Corrections autorisées de la première revue

Le mainteneur a autorisé les trois corrections ci-dessus. Elles ont été
appliquées sans traiter les dettes préexistantes : `ReadoutTabClient` conserve
désormais ses contrôles pendant le chargement, `LazyTabbedTimelineSection`
conserve son onglet, et l'updater Heatmap a été rendu pur. Tests ciblés : 25
succès; ESLint : 0 erreur; typecheck : succès; suite web : 54 fichiers, 381
tests, 3 ignorés; `git diff --check` : succès. Aucun audit/build n'a été
relancé, leurs résultats validés antérieurement restent inchangés.

### Seconde revue indépendante — nouveaux findings bloquants

Deux Reviewers read-only, toujours distincts de l'Implementer, ont relu le diff
après ces corrections. Elle révèle trois régressions introduites par la solution
de conservation d'état :

- **Moyen — curseur Heatmap et reprise de lecture incohérents**
  (`web/src/components/PlayerPositionHeatmap.tsx:148-150,472-479`). Le handler
  du curseur met à jour l'état affiché mais pas `currentTimeRef`; à la reprise,
  l'animation repart donc de l'ancienne valeur. La synchronisation du ref dans
  le handler est une correction locale non ambiguë, mais elle n'a pas été
  appliquée sans nouvelle autorisation.
- **Moyen — retour A → B → A peut afficher le résultat A périmé**
  (`web/src/components/ReadoutTabClient.tsx:552-558`). Le tag par `fightId`
  masque A pendant B, mais redevient valide lors d'un retour à A avant la
  résolution de la nouvelle requête A. Il faut distinguer les générations de
  requêtes tout en préservant les contrôles de table.
- **Moyen — retour 10 s → 20 s → 10 s peut afficher la timeline 10 s périmée**
  (`web/src/components/LazyTabbedTimelineSection.tsx:129-134`). Même défaut de
  tag : `fightId/windowS` ne distingue pas deux requêtes successives pour la
  même clé. Il faut un identifiant de génération, sans remonter l'onglet.

Points mineurs : la dernière frame d'animation est planifiée même après la fin;
les dettes préexistantes d'autoplay, `positionsData`, abort de requête et retries
canvas restent exclues. Les tests nouveaux couvrent les chemins directs mais pas
les retours rapides ni le curseur suivi d'une reprise.

Verdict actuel : **non approuvée pour intégration**. Les trois corrections
autorisées sont validées par les tests, mais ces trois nouveaux findings moyens
doivent être corrigés et retestés avant commit/PR ou Phase 4. Aucun fichier n'a
été modifié par la seconde revue.

### Clôture — revue indépendante finale

Les trois findings de la seconde revue ont été corrigés localement et couverts
par les tests de régression. Validation finale : 28 tests ciblés, ESLint sans
erreur, typecheck, suite web complète (54 fichiers, 384 succès, 3 ignorés) et
`git diff --check` sont au vert. Le Reviewer indépendant `review_edge`, distinct
de l'Implementer et en lecture seule, a relu le diff final avec un focus sur les
états conservés, les réponses asynchrones périmées, les changements rapides de
paramètres, l'autoplay et les dépendances d'effets; verdict : **clean**.

Verdict Phase 3 : **prête à intégrer sous réserve de la décision du mainteneur**.
Les validations environnementales déjà classées `NOT RUN` restent inchangées;
aucun finding bloquant ne subsiste dans le diff web. Recommandation : effectuer
une revue humaine finale du diff, puis créer une branche/PR dédiée et un commit
signé avec trailer DCO lorsque le mainteneur l'autorisera. Ne pas commencer la
Phase 4 avant cette décision explicite.

### Intégration

La Phase 3 a été intégrée dans `main` par squash-merge de la PR #249 le
2026-08-20. Commit d'intégration : `b7db5f82722336b241bc11ac4a43d90f7402d822`
(`fix(web): complete phase 3 baseline (#249)`). Tous les checks requis de la PR
étaient au vert; aucun changement CI, BMAD ou Phase 4 n'était inclus.

## Résolution autorisée des trois findings de revue — Phase 3 / Level 1

Le mainteneur a autorisé exclusivement les trois corrections locales ci-dessous.
Elles ferment les findings de revue sans toucher à la minuterie d'autoplay,
la capture initiale de `positionsData`, l'annulation de requêtes, les retries
canvas, la CI ou une autre dette préexistante.

- `ReadoutTabClient.tsx` : suppression du remount cléé. L'état de chargement est
  désormais étiqueté par `fightId`; lors du changement de combat, les anciennes
  données et erreurs sont masquées jusqu'à la réponse correspondante, tandis que
  l'onglet de table, le filtre de rôle et les tris restent montés. Le test ciblé
  vérifie le chargement sans donnée périmée, puis la conservation des trois
  contrôles.
- `LazyTabbedTimelineSection.tsx` : même étiquetage par `fightId` et `windowS`,
  sans remount de `PerFightTimelineSection`. Une ancienne réponse ne s'affiche
  jamais; l'onglet Per-player demeure sélectionné à travers le chargement d'une
  nouvelle fenêtre. Le test ciblé couvre cette transition.
- `PlayerPositionHeatmap.tsx` : l'updater de temps est pur. Un `ref` porte le
  temps courant dans la boucle RAF; l'arrêt de lecture se produit après le calcul
  de la valeur bornée, hors de tout updater, sans changer l'autoplay immédiat de
  deux secondes ni l'arrêt en fin de timeline.

### Validations de la résolution

| Commande | Résultat |
|---|---|
| `pnpm test:unit tests/components/ReadoutTabClient.test.tsx tests/components/per-fight-timeline-chart.test.tsx tests/components/player-position-heatmap.test.tsx` | succès : 3 fichiers, 25 tests |
| `pnpm lint` | succès : 0 erreur, 16 avertissements non bloquants |
| `pnpm typecheck` | succès |
| `pnpm test:unit` | succès : 54 fichiers, 381 tests, 3 ignorés |
| `git diff --check` | succès |

Les avertissements jsdom/canvas, `act(...)` et de style de test restent sans
échec d'assertion et hors périmètre. L'audit pnpm et le build Next configuré
étaient déjà PASS dans la baseline précédente et n'ont pas été relancés pour ces
trois corrections locales.

### État final après résolution de revue

Les trois findings ci-dessus sont résolus et leurs tests sont présents. Les
points explicitement différés demeurent préexistants et non modifiés. La
divergence CI/ESLint reste documentée séparément : la CI n'exécute toujours pas
`pnpm lint`, alors que le README le prescrit; aucune modification CI n'a été
faite. `WvW/` n'a jamais été ouvert, lu, indexé ni modifié. Le checkpoint reste
le seul chemin non suivi modifié. Les 14 fichiers web suivis sont non indexés et
non commités; aucun commit, push, PR ou passage en Phase 4 n'est autorisé.

## Corrections locales supplémentaires autorisées — concurrence et seek

Trois regressions de concurrence ont été corrigées dans le même périmètre Phase
3 / Level 1, sans modifier la stratégie de cache, les retries canvas,
`positionsData`, l'autoplay, l'annulation réseau, la CI ou les autres dettes
différées.

- `PlayerPositionHeatmap.tsx` : le changement du curseur met désormais à jour
  `currentTimeRef` et l'état affiché ensemble. Une reprise de lecture part donc
  de la position choisie et non d'un temps précédemment mémorisé.
- `ReadoutTabClient.tsx` : l'état de requête porte une génération augmentée de
  façon conditionnelle lors d'un changement de `fightId`. Le cycle A → B → A ne
  peut plus afficher l'ancienne réponse A avant la résolution de la nouvelle
  requête A; onglet, rôle et tri restent conservés.
- `LazyTabbedTimelineSection.tsx` : la même génération est appliquée à la paire
  `fightId` / `windowS`. Le cycle 10 → 20 → 10 masque l'ancienne fenêtre 10
  jusqu'à la réponse actuelle, sans remonter l'onglet Per-player.

### Validations de cette itération

| Commande | Résultat |
|---|---|
| `pnpm test:unit tests/components/player-position-heatmap.test.tsx tests/components/ReadoutTabClient.test.tsx tests/components/per-fight-timeline-chart.test.tsx` | succès : 3 fichiers, 28 tests |
| `pnpm lint` | succès : 0 erreur, 16 avertissements non bloquants |
| `pnpm typecheck` | succès |
| `pnpm test:unit` | succès : 54 fichiers, 384 tests, 3 ignorés |
| `git diff --check` | succès |

Les mêmes avertissements jsdom/canvas, `act(...)` et de style de test restent
non bloquants; aucune assertion n'échoue. Les audits, builds et validations
Docker ne sont pas relancés pour ces corrections locales; leurs états antérieurs
restent inchangés. `WvW/` demeure strictement non ouvert et le checkpoint reste
le seul fichier non suivi modifié.
