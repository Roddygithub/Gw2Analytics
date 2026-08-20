# Politique d'autonomie

## Niveau actuel

Tous les domaines sont au **Level 1** : analyse → proposition → approbation
humaine → exécution. Cela inclut UI, tests, documentation, backend, analytics,
EVTC, migrations et architecture.

| Niveau | Autorisation |
| --- | --- |
| 1 | aucune exécution après analyse sans accord explicite |
| 2 | exécution bornée dans les domaines promus ; approbation pour décisions importantes |
| 3 | poursuite de roadmap dans les limites de domaine ; interruption pour produit, risque ou irréversibilité |

## Promotion

Le Lead peut recommander une promotion, jamais l'appliquer. La recommandation
cite un échantillon de stories réussies, CI, reviews, corrections, conflits,
interventions humaines, qualité de priorisation et stabilité du profil
modèle/reasoning/harness. Une promotion est spécifique au domaine **et** au
profil évalué.

## Rétrogradation

Le système peut rétrograder automatiquement un domaine après régression,
échecs répétés, mauvais routing, conflits, review insuffisante ou baisse de
confiance. Il enregistre la preuve dans le checkpoint, explique la mesure au
mainteneur et revient au Level 1. Toute nouvelle promotion exige un accord
humain explicite.

Un changement important de modèle, reasoning ou harness réduit temporairement
l'autonomie jusqu'à ce que de nouvelles preuves existent.
