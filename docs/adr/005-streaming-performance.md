# ADR 005 — Streaming Performance Improvements

## Contexte

Plusieurs opérations du pipeline d'upload chargeaient
l'intégralité des données en mémoire avant de les traiter :
upload (lecture complète du fichier), parsing EVTC
(matérialisation de tous les fights en liste), sérialisation
JSONL (liste de tous les événements).

## Décisions

### 5.1 Upload streaming

Les fichiers >10 MB sont lus par chunks de 8 KB vers un
fichier temporaire. Le SHA-256 est calculé incrémentalement
pendant la lecture. Pour les petits fichiers, la lecture
directe est conservée.

### 5.2 Parsing itératif

`_parser.parse()` retourne un itérateur. Le premier fight
est extrait via `next()` ; les fights supplémentaires sont
logués et ignorés. `list()` n'est plus appelé.

### 5.3 JSONL streaming

La sérialisation JSONL utilise `gzip.GzipFile` avec un
`BytesIO` intermédiaire au lieu de construire la chaîne
complète en mémoire.

### 5.4 Batch UPSERT

Les `OrmFightPlayerSummary` sont écrits via
`postgres_insert.on_conflict_do_update` au lieu de
DELETE + INSERT par ligne.

## Conséquences

- Utilisation mémoire réduite pendant l'upload
- Pas de latence additionnelle pour les petits fichiers
- UPSERT = une seule opération DB au lieu de N+1

## Status

Accepté
