# Règles de session — Gw2Analytics

## Compactions / résumés de session
À CHAQUE fin de session (ou à chaque compaction), sauvegarder le résumé complet de la session dans **supermemory** :

- Espace actif par défaut (ne pas en créer d'autre).
- Format : titre `## PROJET Gw2Analytics — Résumé de session (YYYY-MM-DD)` puis sections : Objectif, État du travail (fait/en cours/bloqué), Next Move, Fichiers clés, Probes, Notes de décision.
- Toujours inclure les diffs de parité actuels (par joueur), les mappings EI identifiés, et les IDs/GUIDs en jeu.
- Utiliser `supermemory_add_memory` avec `action: "save"`.

Ne PAS garder le résumé uniquement dans le contexte de session — il doit être persistant dans supermemory pour les sessions suivantes.
