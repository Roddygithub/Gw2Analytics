# Matrice de certification

Cette matrice borne la première certification. Une ligne passe de `candidate` à `certified` uniquement après inventaire du corpus, définition de sa règle exacte et élimination des `FAIL` inexpliqués.

| Domaine | Surface actuelle | Règle cible | État initial |
|---|---|---|---|
| En-tête du combat | `arcVersion`, `triggerID`, `gW2Build`, `mapID`, `arcRevision`, `durationMS`, `success`, `eiEncounterID` | Exact | candidate |
| Identité joueur | compte, nom, profession, instance, groupe, équipe | Exact par slice EI | candidate |
| Fenêtres temporelles | `firstAware`, `lastAware`, absences et changements de personnage | Exact; comparer dans la fenêtre de l'entrée EI | candidate |
| Statistiques globales | champs de `_STAT_FIELDS` | Entiers exacts | candidate |
| DPS | `dpsAll` et composantes déjà produites par le comparateur | Entiers exacts; flottants à inventorier | candidate |
| Défense | dégâts reçus, barrier, blocks, dodges, interrupts, downs, morts | Entiers exacts | candidate |
| Boons | `buffUptimes`, stacks et durées suivies | Tolérance par champ à définir après baseline | candidate |
| Rotation | compétence, timestamp et durée | Règle existante: ±2 ms pour timestamp à durée égale, ou timestamp exact si une durée vaut zéro | candidate |
| Cibles | `statsTargets` et statistiques par cible | Exact par instance cible | candidate |
| Propriétaires | maître, pet et minion, y compris changements temporels | Exact au timestamp de l'événement | candidate |
| Classification des dégâts | direct, altération, vol de vie | Classification EI; le canal arcdps seul ne suffit pas | candidate |

## Classification des résultats

- `PASS`: aucune différence selon la règle du bucket.
- `KNOWN_DELTA`: différence correspondant à une règle versionnée, bornée à des clés précises, avec motif et critère de retrait.
- `FAIL`: toute autre différence, donnée manquante, référence incompatible ou fichier dont l'empreinte ne correspond pas au manifeste.

## Manifeste attendu

Le format exact sera décidé dans la story 1. Il doit au minimum contenir: stem, date du combat, SHA-256 du `.zevtc`, SHA-256 de l'export EI, version EI attendue, type d'export et tags de couverture. Il ne contient ni chemin absolu ni donnée personnelle issue du combat.

## Barrière de sortie

La certification est acquise lorsque toutes les lignes incluses sont `certified`, que le rapport ne contient aucun `FAIL`, et que chaque `KNOWN_DELTA` restant est explicitement accepté par le mainteneur.
