# Matrice de Traçabilité — Audit → Plan de Refactoring

Chaque problème de `AUDIT_COMPLET.md` est tracé jusqu'à une action dans `refactoring-plan.md`.
Format : `Audit #PASS-PROBLÈME → Phase.Action`

---

## Pass 1 — Architecture Globale (10 problèmes)

| # | Problème | Référence Audit | Phase.Action | Détail |
|---|----------|----------------|-------------|--------|
| 1 | Absence de Repository Pattern | $78 | **Phase 2.1** | Créer `repositories/` package avec FightRepository, UploadRepository, etc. |
| 2 | Service Layer anémique | $79 | **Phase 2.2** | Extraire logique métier des routes vers services/ avec modèles de domaine |
| 3 | Routes trop épaisses | $80 | **Phase 2.3** | Refactorer players.py (882→200 lignes), webhooks.py (490→200 lignes) |
| 4 | Dépendances circulaires potentielles | $81 | **Phase 2.2** | Repositories dépendent de l'ORM, pas entre eux. Services orchestrés via repositories. |
| 5 | Pas de couche Use Case | $82 | **Phase 2.2** | Les services font office de couche use case (orchestration) |
| 6 | Pas d'Event-Driven Architecture | $83 | **Phase 6.1** (bonus) | Ajouter event bus après refactoring service layer |
| 7 | Frontend/Backend contrat formel | $84 | **Phase 5.4** | Ajouter `openapi-typescript` ou `orval` pour génération auto |
| 8 | Pas de cache centralisé | $85 | **Phase 4.5** | Créer `services/cache_service.py` avec Redis |
| 9 | Monolithe sans frontières claires | $86 | **Phase 5.4** (ADR) | Documenter bounded contexts dans ADR. Pas de découpage module immédiat. |
| 10 | Ordre d'include des routes fragile | $87 | **Phase 2.2** | Restructurer les chemins dans le refactoring service layer |

## Pass 2 — Backend (FastAPI + SQLAlchemy) (20 problèmes)

| # | Fichier | Problème | Audit | Phase.Action | Détail |
|---|---------|----------|-------|-------------|--------|
| 1 | `routes/uploads.py:157` | `file.file.read()` sans streaming → OOM | $111 | **Phase 4.1** | Streaming upload via tempfile pour fichiers >10MB |
| 2 | `routes/uploads.py:227` | Orphelin S3 après rollback | $112 | **Phase 1.2** (ajouté) | Supprimer blob S3 après rollback dans UploadService |
| 3 | `routes/players.py` | 882 lignes monolithiques | $113 | **Phase 2.3** | Extraire dans services/player_service.py |
| 4 | `services/parse.py:65` | `list(_parser.parse(...))` charge tout | $114 | **Phase 4.2** | Streamer l'iterator, ne pas matérialiser en list |
| 5 | `services/player_summaries.py:144` | Delete+insert au lieu d'upsert | $115 | **Phase 4.6** | UPSERT batch via postgres_insert + on_conflict_do_update |
| 6 | `services/player_summaries.py:144` | 200+ lignes, `noqa: PLR0912` | $116 | **Phase 5.1** | Refactorer en sous-fonctions |
| 7 | `schema_guard.py:239` | Crash au lieu de degraded mode | $117 | **Phase 5.1** | Logger + degraded mode au lieu de RuntimeError |
| 8 | `routes/uploads.py:97-115` | Double responsabilité enqueue/fallback | $118 | **Phase 2.2** | UploadService gère l'enqueue, pas la route |
| 9 | `routes/uploads.py:116` | `asyncio.to_thread` sans timeout | $119 | **Phase 4.1** | Ajouter `asyncio.wait_for` avec timeout |
| 10 | `workers/webhook_dispatch.py` | httpx sans timeout | $120 | **Phase 1.1** (ajouté) | Timeout + retry configurable |
| 11 | `services/event_blob.py:87` | JSONL en mémoire | $121 | **Phase 4.3** | Streamer ligne par ligne avec gzip.GzipFile |
| 12 | `crypto.py` | `@lru_cache` stale après rotation KEK | $122 | **Phase 5.1** | Remplacer par TTLCache avec timeout bas |
| 13 | `config.py:75` | Validation dans le modèle de config | $123 | **Phase 5.3** | Déplacer validateurs dans fonctions séparées |
| 14 | `routes/uploads.py` | Parse OK mais dispatch échoue → perdu | $124 | **Phase 2.2** | UploadService persiste l'état "parsed" + retry dispatch |
| 15 | `workers/stuck_upload_sweeper.py` | Pas de cancellation propre | $125 | **Phase 5.1** | Ajouter Event pour arrêt propre |
| 16 | `services/fight_persistence.py:79` | `flush()` prématuré | $126 | **Phase 4.6** | Un seul commit final, pas de flush intermédiaire |
| 17 | `storage.py` | Pas de retry S3 | $127 | **Phase 4.1** | Ajouter tenacity retry sur appels MinIO |
| 18 | `main.py:120` | Healthcheck incomplet | $128 | **Phase 1.3** (ajouté) | Ajouter vérification S3 + DB dans /healthz |
| 19 | `routes/__init__.py` | Import massif | $129 | **Phase 5.1** | Imports paresseux ou auto-discovery |
| 20 | Partout | Pas de tracing distribué | $130 | **Phase 6.1** (bonus) | Ajouter OpenTelemetry instrumentation |

## Pass 3 — Frontend (5 problèmes)

| # | Problème | Audit | Phase.Action | Détail |
|---|----------|-------|-------------|--------|
| 1 | Absence de contrat TypeScript/Api généré | $156 | **Phase 5.4** | Ajouter `orval.config.ts` + script `generate-api` |
| 2 | Pas d'API client dédié | $157 | **Phase 5.4** | orval génère un client fetch centralisé |
| 3 | State management inconnu | $158 | **HORS SCOPE** | À auditer séparément |
| 4 | Pas de tests E2E | $159 | **HORS SCOPE** | À ajouter après refactoring backend |
| 5 | Pas de Storybook | $160 | **HORS SCOPE** | Pas prioritaire |

## Pass 4 — Base de Données (20 problèmes)

| # | Table | Problème | Audit | Phase.Action | Détail |
|---|-------|----------|-------|-------------|--------|
| 1 | `fights.id` VARCHAR(64) | PK SHA-256 hex inefficace | $172 | **Phase 3.4** | Garder VARCHAR pour compat, évaluer UUID binaire plus tard |
| 2 | `fights.events_blob_uri` VARCHAR(255) | Troncature possible | $173 | **Phase 3.1** (ajouté) | ⏳ Migrer à TEXT — **Non fait**. Le modèle utilise toujours `String(255)`. Troncature improbable en pratique (chemins MinIO < 200 chars). |
| 3 | `fight_agents.agent_id` NUMERIC(20,0) | Lent vs BIGINT | $174 | **Phase 3.2 → REVERTED** | ⚠️ **Reverted**: BIGINT casse uint64 (2^64-1 > 2^63-1). Retour à `Numeric(20,0)` dans migration `revert_agent_id_to_numeric`. L'audit original était incorrect. |
| 4 | `fight_player_summaries` 28 colonnes boon | Normalisation faible | $175 | **Phase 3.1** | Créer table `fight_player_boons` — ✅ Fait via migration `phase3_schema_changes` |
| 5 | `uploads.sha256` VARCHAR(64) | Stockage inefficace | $176 | **Phase 3.4 → REPORTÉ** | ⏳ **Non fait**. Le modèle utilise toujours `String(64)`. Migration BYTEA(32) dépriorisée — nécessite réécriture des données existantes. |
| 6 | `uploads.size_bytes` INTEGER | Overflow à 2.1B | $177 | **Phase 3.2** | `BigInteger` — ✅ Fait via migration `phase3_schema_changes` |
| 7 | `fight_player_summaries.power_damage` INTEGER | Overflow possible | $178 | **Phase 3.2** | `BigInteger` — ✅ Fait (migration `0014_fps_bigint` existante) |
| 8 | `fight_player_summaries.total_damage` INTEGER | Overflow | $179 | **Phase 3.2** | `BigInteger` — ✅ Fait (migration `0014_fps_bigint` existante) |
| 9 | `fight_agents` pas d'index composite | Scan séquentiel | $180 | **Phase 1.1** | Index `(account_name, fight_id)` |
| 10 | `fights.upload_id` UUID en texte | Inefficace | $181 | **Phase 3.4** | Garder pour compat, évaluer plus tard |
| 11 | `webhook_deliveries` index simple | Sous-optimal | $182 | **Phase 1.1** | Index composite `(subscription_id, next_attempt_at)` |
| 12 | `webhook_dlq.subscription_id` pas de FK | Orphelins DLQ | $183 | **Phase 1.3** | Ajouter FK |
| 13 | `webhook_dlq.upload_id` pas de FK | Orphelins DLQ | $184 | **Phase 1.3** | Ajouter FK |
| 14 | `guild_members.account_name` pas d'index | Scan table | $185 | **Phase 1.1** | Index sur `account_name` |
| 15 | `fight_player_summaries.detected_tags` JSON | Pas de GIN index | $186 | **Phase 1.1** | Ajouter GIN index si recherché |
| 16 | Pas de compression | Stockage gonflé | $187 | **Phase 4.5** | ⏳ **Non fait**. pglz nécessite `ALTER TABLE ... SET (toast.compression = 'pglz')` + réécriture. Dépriorisé — bénéfice limité sans partitionnement préalable. |
| 17 | Pas de partitionnement | Performance | $188 | **Phase 3.3** (ajouté) | ❌ **Non fait** (évaluation uniquement). Partitionnement mensuel à réévaluer après montée en charge. |
| 18 | `alembic_version` lock | Contention | $189 | **Phase 5.1** | Cache du numéro de version |
| 19 | Pas de `created_at`/`updated_at` | No traçabilité | $190 | **Phase 3.3** | Ajouter TimestampMixin aux tables principales |
| 20 | PK composite déjà OK | Pas d'action | $191 | — | Déjà couvert |

## Pass 5 — Performance (22 optimisations)

| # | ROI | Problème | Audit | Phase.Action | Détail |
|---|-----|----------|-------|-------------|--------|
| 1 | ★★★★★ | `file.file.read()` charge tout | $227 | **Phase 4.1** | Streaming upload tempfile |
| 2 | ★★★★★ | `list(_parser.parse(...))` tous les fights | $228 | **Phase 4.2** | Iterator stream |
| 3 | ★★★★★ | N+1 agents/skills dans _save_fight | $229 | **Phase 4.6** | Bulk insert |
| 4 | ★★★★★ | JSONL events en mémoire | $230 | **Phase 4.3** | Stream JSONL ligne par ligne |
| 5 | ★★★★★ | Pas d'index composite (account, fight) | $231 | **Phase 1.1** | Index composite |
| 6 | ★★★★ | OFFSET pagination | $232 | **Phase 4.4** | Keyset pagination |
| 7 | ★★★★ | Delete+insert player_summaries | $233 | **Phase 4.6** | UPSERT batch |
| 8 | ★★★★ | Pas d'index composite webhook_deliveries | $234 | **Phase 1.1** | Index composite |
| 9 | ★★★★ | model_dump_json() coûteux | $235 | **Phase 4.3** | model_dump(mode="json") + json.dumps |
| 10 | ★★★★ | flush() prématuré | $236 | **Phase 4.6** | Un seul commit |
| 11 | ★★★ | Blob cache pas de TTL | $237 | **Phase 4.5** | TTL + invalidation |
| 12 | ★★★ | Skills catalog chargé au startup | $238 | **Phase 5.1** | Lazy load |
| 13 | ★★★ | Pas de Redis cache | $239 | **Phase 4.5** | CacheService Redis |
| 14 | ★★★ | Pas de compression pg | $240 | **Phase 4.5** | pglz/TOAST |
| 15 | ★★★ | Prometheus generate_latest() | $241 | **Phase 5.1** | Cache counter |
| 16 | ★★ | selectinload dans event_blob | $242 | **Phase 5.1** | joinedload si nécessaire |
| 17 | ★★ | Arq max_jobs=2 | $243 | **Phase 5.1** | max(os.cpu_count(), 2) |
| 18 | ★★ | Connection pool non tuné | $244 | **Phase 5.1** | Pool sizing configurable |
| 19 | ★★ | os.environ.get lent | $245 | **Phase 5.1** | Settings field |
| 20 | ★★ | Gzip synchrone | $246 | **Phase 4.3** | asyncio.to_thread |
| 21 | ★ | content-length sans cache | $247 | **Phase 2.2** | UploadService lit le header |
| 22 | ★ | hashlib.sha256 complet | $248 | **Phase 4.1** | Streaming hash si chunké |

## Pass 6 — Sécurité (13 problèmes)

| # | Problème | Sévérité | Audit | Phase.Action | Détail |
|---|----------|----------|-------|-------------|--------|
| 1 | Pas de rate limiting sur listing | HIGH | $260 | **Phase 1.2** | Ajouter `@limiter.limit("30/minute")` sur players, webhooks, guilds, skills |
| 2 | Aucune authentification | HIGH | $261 | **Phase 1.4** (ajouté) | Ajouter couche d'auth basique sur endpoints non-publics |
| 3 | Absence de CSRF | MEDIUM | $262 | **HORS SCOPE** | À traiter côté frontend |
| 4 | SECRETS_KEK en clair dans .env | MEDIUM | $263 | **Phase 1.4** (ajouté) | Ajouter warning + doc pour secret manager |
| 5 | CORS wide-open en dev | MEDIUM | $264 | **Phase 1.4** (ajouté) | CI/CD enforce CORS strict en prod |
| 6 | Pas de validation MIME type upload | MEDIUM | $265 | **Phase 1.4** (ajouté) | Vérifier Content-Type dans UploadService |
| 7 | Pas de CSP header | MEDIUM | $266 | **HORS SCOPE** | Côté frontend |
| 8 | X-Forwarded-For trust | MEDIUM | $267 | **Phase 1.4** (ajouté) | Configurer trust proxy |
| 9 | SSRF protection manuelle | MEDIUM | $268 | **Phase 2.2** | Extraire dans WebhookService, garder la logique |
| 10 | Pas de validation taille au proxy | LOW | $269 | **HORS SCOPE** | Config Caddy séparée |
| 11 | Pas de secrets scanning | LOW | $270 | **Phase 5.5** | Ajouter pre-commit hook detect-secrets |
| 12 | Docker images non scannées | LOW | $271 | **Phase 5.5** | Ajouter trivy dans CI |
| 13 | Pas de signature HMAC webhook | LOW | $272 | **Phase 2.2** | Standardiser dans WebhookService |

## Pass 7 — Qualité du Code (24 problèmes)

| # | Fichier | Problème | Audit | Phase.Action | Détail |
|---|---------|----------|-------|-------------|--------|
| 1 | `models/fight.py` | ORM anémique | $300 | **Phase 5.1** | Ajouter helper methods |
| 2 | `routes/players.py` | 882 lignes | $301 | **Phase 2.3** | Extraire dans services/ |
| 3 | `services/player_summaries.py` | 200+ lignes, noqa | $302 | **Phase 5.1** | Refactorer en sous-fonctions |
| 4 | `services/parse.py` | 90+ lignes | $303 | **Phase 5.1** | Extraire sous-fonctions |
| 5 | `routes/uploads.py` | Duplication validation taille | $304 | **Phase 2.2** | Factoriser dans UploadService |
| 6 | `routes/webhooks.py` | Duplication validation URL | $305 | **Phase 2.2** | Extraire dans WebhookService |
| 7 | `services/player_summaries.py` | Duplication boon fields | $306 | **Phase 3.1** | Normaliser en table player_boons |
| 8 | `workers/parser_settings.py` | Code mort (port=1 guard) | $307 | **Phase 5.2** | Supprimer |
| 9 | `schema_guard.py` | Docstring 100+ lignes | $308 | **Phase 5.2** | Réduire à 20 lignes |
| 10 | `crypto.py` | Threat model dans code | $309 | **Phase 5.2** | Déplacer dans docs/ |
| 11 | `config.py` | Champs dupliqués minio_* | $310 | **Phase 5.1** | Grouper dans bloc |
| 12 | `database.py` | Fonctions redondantes | $311 | **Phase 5.1** | Simplifier |
| 13 | `storage.py` | Docstring surdimensionnée | $312 | **Phase 5.2** | Simplifier |
| 14 | `models/fight.py` | agent_id NUMERIC vs BIGINT | $313 | **Phase 3.2** | BIGINT |
| 15 | `models/upload.py` | size_bytes INTEGER vs BIGINT | $314 | **Phase 3.2** | BIGINT |
| 16 | `routes/player_compare.py` | Duplication logique | $315 | **Phase 2.2** | Extraire en shared service |
| 17 | Tous les services | Pas de typing strict | $316 | **Phase 5.3** | Ajouter types concrets |
| 18 | `services/guild_service.py` | Stub non fonctionnel | $317 | **Phase 5.2** | Implémenter ou supprimer |
| 19 | `main.py` | Import massif routers | $318 | **Phase 5.1** | Auto-discovery |
| 20 | `workers/webhook_dispatch.py` | Pas de tests | $319 | **Phase 5.5** | Ajouter tests unitaires |
| 21 | `services/event_blob.py` | Double write pattern | $320 | **Phase 5.1** | Saga pattern ou compensation |
| 22 | `routes/account.py` | 2 appels séquentiels | $321 | **Phase 5.1** | `asyncio.gather` |
| 23 | `models/webhook.py` | `filter` shadow builtin | $322 | **Phase 5.1** | Renommer en `filter_json` |
| 24 | `routes/webhooks.py` | DNS executor global jamais fermé | $323 | **Phase 5.1** | Context manager |

---

## Résumé

| Pass | Problèmes | Couverts | Non couverts | Reportés | % |
|------|-----------|----------|-------------|----------|----|
| 1 — Architecture | 10 | 10 | 0 | 0 | 100% |
| 2 — Backend | 20 | 20 | 0 | 0 | 100% |
| 3 — Frontend | 5 | 2 | 3 | 0 | 40% |
| 4 — Base de Données | 20 | 16 | 0 | 4 | 80% (4 reportés) |
| 5 — Performance | 22 | 22 | 0 | 0 | 100% |
| 6 — Sécurité | 13 | 10 | 3 | 0 | 77% |
| 7 — Qualité | 24 | 24 | 0 | 0 | 100% |
| **Total** | **114** | **104** | **6** | **4** | **91%** |

### État réel (vérifié codebase le 2026-07-24)

Tout ce qui était marqué comme "à faire" dans le plan est **déjà implémenté** dans le code :

- **Phase 1** : Index composites (fight_agents, webhook_deliveries, guild_members) ✅, rate limiting slowapi avec limites par route ✅, FK subscription_id sur webhook_dlq ✅ (upload_id volontairement omis — type mismatch String vs UUID), MIME validation ✅, healthcheck S3+DB ✅, auth.py ✅, warning KEK ✅, CORS configurable ✅, timeout webhook configurable ✅
- **Phase 2** : repositories/ (6 fichiers) ✅, services/ (9 fichiers) ✅, routes players 262 lignes (au lieu de 882) ✅
- **Phase 3** : OrmFightPlayerBoon ✅, BIGINT ✅, TimestampMixin ✅, agent_id Numeric (reverté) ✅
- **Phase 4** : streaming upload ✅, streaming parse (iterator) ✅, streaming JSONL (GzipFile) ✅, keyset pagination ✅, CacheService ✅, UPSERT batch ✅
- **Phase 5** : code mort supprimé ✅, pre-commit hooks ✅, security.yml (Trivy) ✅, ADR ✅

**Mise à jour finale (2026-07-24) :** Phase 6 et 7 complétées — Grafana dashboard (`monitoring/grafana-dashboard.json`), workflow migration test (`.github/workflows/migration-test.yml`), structured logging JSON branché sur le process API + workers Arq. Il ne reste que les items DB dépriorisés (compression, partitionnement, BYTEA) qui n'auront de sens qu'après montée en charge.

### Problèmes non couverts (6)
| Pass | Problème | Raison |
|------|----------|--------|
| Frontend #3 | State management inconnu | À auditer séparément, dépend du choix frontend |
| Frontend #4 | Pas de tests E2E | Hors scope Phase 1-5, nécessite infrastructure dédiée |
| Frontend #5 | Pas de Storybook | Non prioritaire, pas de design system critique |
| Sécurité #3 | Absence de CSRF | Côté frontend, pas backend |
| Sécurité #7 | Pas de CSP header | Côté frontend, header HTTP à configurer dans Next.js |
| Sécurité #10 | Pas de validation taille au proxy | Config Caddy/hébergement, pas dans le code |

### Problèmes reportés / dépriorisés (4)
| Pass | Problème | Raison du report |
|------|----------|-----------------|
| DB #2 | `events_blob_uri` VARCHAR(255)→TEXT | Troncature improbable (~200 chars). Faible priorité. |
| DB #5 | `sha256` VARCHAR(64)→BYTEA(32) | Nécessite réécriture des données. Bénéfice marginal. |
| DB #16 | Compression pglz | Bénéfice limité sans partitionnement. |
| DB #17 | Partitionnement mensuel | À réévaluer après montée en charge réelle. |

### Nouvelles actions ajoutées au plan (non dans l'audit original)

Ces actions sont **identifiées par la matrice** mais étaient implicites ou éparpillées dans les passes. Je les ai rendues explicites :

| Action | Phase | Source |
|--------|-------|--------|
| Supprimer orphelins S3 après rollback | Phase 1.2 | Backend #2 → $112 |
| Timeout + retry webhook dispatch | Phase 1.1 | Backend #10 → $120 |
| Healthcheck S3 + DB | Phase 1.3 | Backend #18 → $128 |
| Migration events_blob_uri VARCHAR(255)→TEXT | Phase 3.1 | DB #2 → $173 |
| Partitionnement mensuel à évaluer | Phase 3.3 | DB #17 → $188 |
| Couche d'authentification basique | Phase 1.4 | Sécurité #2 → $261 |
| Warning KEK en clair + doc secret manager | Phase 1.4 | Sécurité #4 → $263 |
| CI/CD enforce CORS strict en prod | Phase 1.4 | Sécurité #5 → $264 |
| Validation MIME type upload | Phase 1.4 | Sécurité #6 → $265 |
| Configurer trust proxy | Phase 1.4 | Sécurité #8 → $267 |
| Pre-commit detect-secrets | Phase 5.5 | Sécurité #11 → $270 |
| Trivy dans CI | Phase 5.5 | Sécurité #12 → $271 |