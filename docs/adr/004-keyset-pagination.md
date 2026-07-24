# ADR 004 — Keyset Pagination for Player List

## Contexte

Le endpoint `GET /api/v1/players` utilisait `LIMIT ? OFFSET ?` pour
la pagination. Pour les pages profondes (offset > 10k), le
SGBD doit scanner et ignorer les lignes précédentes, ce qui
dégrade les performances.

## Décision

Remplacer `OFFSET` par une pagination par curseur (keyset
pagination) pour le listing principal des joueurs.

Le curseur est un objet JSON encodé en base64url contenant
les champs `last_damage` et `last_account`. La requête SQL
filtre avec :

```sql
WHERE (total_damage < :last_damage)
   OR (total_damage = :last_damage AND account_name > :last_account)
ORDER BY total_damage DESC, account_name ASC
LIMIT :limit + 1
```

Le `+1` évite une requête COUNT séparée pour détecter la
présence d'une page suivante.

## Conséquences

- Les pages profondes sont O(log n) au lieu de O(n)
- L'API expose `X-Next-Cursor` en en-tête de réponse
- Le paramètre `offset` est conservé pour la rétrocompatibilité
- Les clients doivent parser l'en-tête pour naviguer

## Status

Accepté
