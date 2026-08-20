# Protocole de communication et handoff

## Enveloppe de délégation

Chaque délégation est courte et structurée :

```yaml
task_id: story-ou-bug/sous-tache
parent_id: optionnel
intent: question|diagnose|plan|implement|review
risk: low|medium|high|critical
objective: résultat observable
acceptance: critères de succès
context_refs: chemins, commit, SPEC ou ADR
allowed_paths: frontières d'écriture
forbidden: WvW, secrets, opérations interdites
validation: commandes et preuves attendues
output: résumé, fichiers, validations, risques et blocages
```

Le parent transmet uniquement le contexte nécessaire. Le worker retourne des
références et une synthèse, jamais un dump de dépôt, de logs ou de données privées.

## États et escalade

`queued → assigned → running → blocked → review → changes_requested → validated → integrated`

Un état affiché par Herdr est une projection de terminal, jamais une preuve
d'intégration. `done`, `idle` ou `unknown` exigent toujours diff, validations et
review avant changement d'état canonique.

Avant un handoff, enregistrer dans `current-state.md` : objectif, décisions,
fichiers, commit de base, validations PASS/FAIL/NOT RUN, risques, blocages,
profil recommandé et prochaine action. Une consultation Specialist retourne au
Lead ; elle ne transfère pas automatiquement la propriété de la tâche.
