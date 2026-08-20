# Architecture agentique minimale

## Invariants

Le **GW2Analytics Lead** est un rôle, non un modèle ni un processus permanent.
Il route le travail, garde le contexte décisionnel court et reçoit les synthèses.
Les profils Codex sont déclaratifs sous `.codex/agents/` : ils ne lancent aucun
agent tant qu'une tâche ne l'exige pas.

| Capacité | Permission | Profil initial | Responsabilité |
| --- | --- | --- | --- |
| Lead | écriture seulement si autorisée | Terra / medium | intention, risque, autorisation, orchestration |
| Explorer | read-only | Luna / medium | cartographie et preuves ciblées |
| Implementer | workspace-write | Terra / medium | changement local explicitement autorisé |
| Reviewer | read-only | Terra / high | review indépendante et couverture de validation |
| Specialist | read-only | Sol / high | EVTC, analytics, migrations, données, architecture critique |

Les valeurs sont des profils de départ. Le Lead peut demander un effort supérieur
ou un autre profil lorsque le risque le justifie ; le rôle reste inchangé.

## Mémoire et reprise

Les faits durables vivent dans le dépôt. Chaque fin de phase ou interruption
significative met à jour `current-state.md` avec l'objectif, le dernier état
validé, les validations, les risques, le prochain mouvement et le profil de
reprise recommandé. Les agents transmettent des références de fichiers et de
commits, pas des copies de logs ni du corpus privé.

Le rapport d'audit local historique a seulement fourni cette synthèse assainie :
une configuration Codex minimale, un Lead explicite, quatre capacités réutilisables,
un routing par risque, un fallback non déclaré et une gouvernance Git/GitHub à
traiter séparément. Le rapport brut reste non suivi.

## Fallback

Aucun fallback n'est configuré en Phase 5. En cas de limite ou d'indisponibilité,
le Lead sauvegarde le checkpoint, réessaie ou ajuste le profil OpenAI si cela est
autorisé. Un fallback OSS ou multi-provider exige ultérieurement une installation
épinglée, une configuration à privilèges minimaux et des évaluations par rôle.

Sans équivalent vérifié du Specialist, l'humain valide obligatoirement toute
architecture, migration, sémantique EVTC, modèle de données, analytique critique
ou opération irréversible.
