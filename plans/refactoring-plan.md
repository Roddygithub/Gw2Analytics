# Plan de Refactoring — Gw2Analytics

**Objectif :** Passer de 49/100 à 76/100+ sans rien casser.
**Contrainte #1 :** CI doit passer (vert) à chaque commit.
**Contrainte #2 :** Chaque phase est autonome (peut être mergée indépendamment).
**Contrainte #3 :** Zéro régression fonctionnelle.

---

## Phase 0 — Préparation (Sprint 0)

### 0.1 Audit de couverture de tests
Avant toute modification, on établit la baseline.

```bash
# Coverage actuel
pytest --cov=apps/api/src --cov=libs --cov-report=term-missing apps/api/tests libs/*/tests

# Lint actuel
ruff check apps/api/src libs --statistics

# Type check actuel
mypy apps/api/src libs
```

**Livrable :** Fichier `coverage-baseline.txt` commité.

### 0.2 Création des branches de travail
```
main
└── refactor/phase-1-db-indexes
└── refactor/phase-2-service-layer
└── refactor/phase-3-schema-normalization
└── refactor/phase-4-performance
└── refactor/phase-5-quality
```

### 0.3 CI hardening
Ajouter un job CI qui vérifie que la couverture ne baisse PAS entre les phases.

```yaml
# .github/workflows/ci.yml — à ajouter
- name: Enforce coverage floor
  run: |
    pytest --cov-fail-under=90 --cov=apps/api/src --cov=libs
```

---

## Phase 1 — Quick Wins Base de Données + Sécurité (Sprint 1)

### 1.1 Ajouter les index manquants

**Fichiers à modifier :**
- `apps/api/src/gw2analytics_api/models/fight.py`
- `apps/api/src/gw2analytics_api/models/webhook.py`
- `apps/api/src/gw2analytics_api/models/guild.py`

**Index à ajouter dans les modèles :**

```python
# fight.py — sur OrmFightAgent
__table_args__ = (
    Index("ix_fight_agents_account_fight", "account_name", "fight_id"),
)

# webhook.py — sur OrmWebhookDelivery
__table_args__ = (
    CheckConstraint(...),
    Index("ix_webhook_deliveries_sub_next", "subscription_id", "next_attempt_at"),
)

# guild.py — sur GuildMember
__table_args__ = (
    Index("ix_guild_members_account", "account_name"),
)
```

**Migration Alembic :**
```
alembic revision --autogenerate -m "add_missing_indexes_phase1"
```

**Vérification CI :**
- `alembic upgrade head` passe
- `pytest` passe (coverage >= 90%)
- Les index sont créés en DB

### 1.2 Ajouter Rate Limiting sur tous les endpoints

**Fichiers à modifier :**
- `apps/api/src/gw2analytics_api/routes/players.py` — Ajouter `@limiter.limit`
- `apps/api/src/gw2analytics_api/routes/webhooks.py` — Ajouter `@limiter.limit`
- `apps/api/src/gw2analytics_api/routes/guilds.py` — Ajouter `@limiter.limit`
- `apps/api/src/gw2analytics_api/routes/skills.py` — Ajouter `@limiter.limit`

**À ajouter sur chaque route GET list :**
```python
@limiter.limit("30/minute")
```

**Vérification CI :**
- Tous les tests passent
- `ruff check` OK
- `mypy` OK

### 1.3 Ajouter les FK manquantes

**Fichiers à modifier :**
- `apps/api/src/gw2analytics_api/models/webhook.py`

```python
# Ajouter FK sur OrmWebhookDlq
subscription_id: Mapped[str] = mapped_column(
    String(64),
    ForeignKey("webhook_subscriptions.id"),
    nullable=False,
)
upload_id: Mapped[str] = mapped_column(
    String(64),
    ForeignKey("uploads.id"),
    nullable=False,
)
```

**Migration :** `alembic revision --autogenerate -m "add_webhook_dlq_fks"`

**Vérification CI :**
- Migration OK
- Tests OK
- Pas d'erreur mypy

### 1.4 Sécurité complémentaire

**Actions :**

| # | Action | Fichier | Détail |
|---|--------|---------|--------|
| 1 | Supprimer orphelins S3 après rollback | `services/upload_service.py` (Phase 2) | Nettoyer le blob MinIO si la transaction DB échoue |
| 2 | Timeout configurable webhook dispatch | `workers/webhook_dispatch.py` | Ajouter `httpx.Timeout(30.0)` |
| 3 | Healthcheck S3 + DB | `main.py:120` | Ajouter vérifications dans `/healthz` |
| 4 | Auth basique endpoints non-publics | `routes/*.py` | Décorateur `require_auth` optionnel |
| 5 | Warning KEK en clair | `config.py` | Logger warning si `SECRETS_KEK` lue depuis `.env` |
| 6 | Validation MIME type upload | `services/upload_service.py` (Phase 2) | Vérifier `application/octet-stream` |
| 7 | CORS strict en prod | CI/CD | `.env.production` avec origines explicites |
| 8 | Trust proxy config | `main.py` | `app = FastAPI(..., trust_proxy=True)` |

**Vérification CI :**
- `pytest` ✅
- `ruff check` ✅
- `mypy` ✅

### Phase 1 — Fichiers touchés (16)
```
Modifiés :
  apps/api/src/gw2analytics_api/models/fight.py       (+Index)
  apps/api/src/gw2analytics_api/models/webhook.py      (+FK +Index)
  apps/api/src/gw2analytics_api/models/guild.py        (+Index)
  apps/api/src/gw2analytics_api/routes/players.py      (+limiter)
  apps/api/src/gw2analytics_api/routes/webhooks.py     (+limiter +timeout)
  apps/api/src/gw2analytics_api/routes/guilds.py       (+limiter)
  apps/api/src/gw2analytics_api/routes/skills.py       (+limiter)
  apps/api/src/gw2analytics_api/main.py                (+healthcheck +trust_proxy)
  apps/api/src/gw2analytics_api/config.py              (+KEK warning)
  apps/api/alembic/versions/                           (+2 migrations)
Nouveaux :
  apps/api/src/gw2analytics_api/auth.py                (+decorator require_auth)
```

**Risques :** Faibles. Modifications localisées, tests existants couvrent.
**Bénéfices :** Sécurité + performance DB immédiate.

---

## Phase 2 — Repository Pattern + Service Layer (Sprint 2)

### 2.1 Créer le package `repositories/`

**Nouveaux fichiers :**
```
apps/api/src/gw2analytics_api/repositories/
├── __init__.py
├── fight_repository.py
├── upload_repository.py
├── webhook_repository.py
├── player_repository.py
└── guild_repository.py
```

**Exemple — `repositories/fight_repository.py` :**
```python
class FightRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_by_id(self, fight_id: str) -> OrmFight | None:
        return self._session.get(OrmFight, fight_id)

    def find_without_summaries(self, fight_ids: list[str] | None = None) -> set[str]:
        ...

    def save_fight_with_agents_and_skills(
        self, upload: Upload, domain_fight: DomainFight
    ) -> OrmFight:
        ...
```

### 2.2 Extraire la logique métier des routes

**Fichiers à créer :**
```
apps/api/src/gw2analytics_api/services/
├── __init__.py
├── fight_service.py        ← Nouveau : orchestre creation fight + blobs + summaries
├── player_service.py       ← Nouveau : extrait de routes/players.py
├── upload_service.py       ← Nouveau : extrait de routes/uploads.py
└── webhook_service.py      ← Nouveau : extrait de routes/webhooks.py
```

**Principe :** Chaque route devient une thin layer qui :
1. Parse les paramètres de la requête
2. Appelle le service
3. Retourne la réponse formatée

**Exemple — avant vs après :**

```python
# AVANT (routes/uploads.py:150-260)
@router.post(...)
async def create_upload(request, file, db):
    raw = file.file.read()
    sha = hashlib.sha256(raw).hexdigest()
    existing = db.execute(select(Upload)...)
    if existing:
        ...
    upload = Upload(...)
    db.add(upload)
    try:
        db.flush()
    except IntegrityError:
        ...
    try:
        put_zevtc(sha, raw)
    except S3Error:
        ...
    db.commit()
    await _enqueue_parse(request, upload.id, raw)
    return UploadCreatedResponse(...)

# APRÈS (routes/uploads.py:30-50)
@router.post(...)
async def create_upload(request, file, db):
    service = UploadService(db, request.app.state)
    result = await service.create_upload(file)
    return UploadCreatedResponse(**result.to_dict())

# APRÈS (services/upload_service.py)
class UploadService:
    def __init__(self, db, app_state):
        self._repo = UploadRepository(db)
        self._fight_repo = FightRepository(db)
        self._storage = StorageService()
        self._arq_pool = getattr(app_state, "arq_pool", None)
        self._settings = get_settings()

    async def create_upload(self, file: UploadFile) -> UploadResult:
        raw = await self._read_file_safe(file)
        sha = hashlib.sha256(raw).hexdigest()

        existing = self._repo.find_by_sha256(sha)
        if existing and existing.status == "failed":
            existing.status = "pending"
            self._repo.flush()
            await self._enqueue_parse(existing.id, raw)
            return UploadResult.from_orm(existing)

        if existing:
            return UploadResult.from_orm(existing)

        upload = self._repo.create_pending(sha, file.filename, len(raw))
        try:
            await self._storage.store_blob(sha, raw)
        except StorageError as exc:
            self._repo.rollback()
            raise HTTPException(503, ...)

        self._repo.commit()
        await self._enqueue_parse(upload.id, raw)
        return UploadResult.from_orm(upload)
```

### 2.3 Refactorer `routes/players.py` (882 lignes → ~200)

**Plan de découpage :**

| Extraction | Destination | Lignes économisées |
|------------|-------------|-------------------|
| `_load_merged_contributions` | `services/player_service.py` | ~60 |
| `_load_slow_path_contributions` | `services/player_service.py` | ~50 |
| `_contributions_from_blob_walk` | `services/player_service.py` | ~100 |
| `_ContributionBucket`, `_DayTotals` | `services/player_service.py` | ~40 |
| `_parse_profession_filter` | `route_helpers.py` | ~20 |
| `_profile_to_list_row` | `route_helpers.py` | ~30 |
| `_profession_label`, `_elite_label` | `route_helpers.py` (déjà existant) | ~20 |

**Reste dans la route :** ~100 lignes de déclarations FastAPI + formatage réponse.

### 2.4 Tester la non-régression

```python
# test_routes_after_refactor.py
# Chaque route refactorée a un test "golden" qui compare la réponse AVANT/APRÈS
class TestUploadRouteGolden:
    async def test_create_upload_response_shape(self, client, sample_zevtc):
        resp = await client.post("/api/v1/uploads", files={"file": sample_zevtc})
        assert resp.status_code == 201
        # Vérifie que le shape de la réponse est identique à l'ancien format
        assert "id" in resp.json()
        assert "sha256" in resp.json()
        assert "status" in resp.json()
```

**Vérification CI :**
- `pytest` ✅
- `ruff check` ✅
- `mypy` ✅
- `pip-audit` ✅

### Phase 2 — Fichiers touchés (18)
```
Nouveaux :
  repositories/__init__.py
  repositories/fight_repository.py
  repositories/upload_repository.py
  repositories/webhook_repository.py
  repositories/player_repository.py
  repositories/guild_repository.py
  services/__init__.py (refactoré)
  services/fight_service.py
  services/player_service.py
  services/upload_service.py
  services/webhook_service.py

Modifiés :
  routes/uploads.py              ← ~150 lignes → ~50 lignes
  routes/players.py              ← ~882 lignes → ~200 lignes
  routes/webhooks.py             ← ~490 lignes → ~200 lignes
  routes/guilds.py               ← ~72 lignes → ~30 lignes
  route_helpers.py               ← ajout helpers
```

**Risques :** Élevés. C'est le plus gros refactoring. Chaque route extraite doit être testée une par une. On ne merge PAS tout d'un coup — on extrait route par route, PR par PR.
**Bénéfices :** Testabilité, SRP, maintenabilité, évolutivité.

---

## Phase 3 — Normalisation Schéma + Migrations (Sprint 3)

### 3.1 Normaliser les boons (28 colonnes → 1 table)

**Nouvelle table :**
```sql
CREATE TABLE fight_player_boons (
    fight_id VARCHAR(64) NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
    account_name VARCHAR(128) NOT NULL,
    boon_name VARCHAR(30) NOT NULL,     -- 'might', 'fury', etc.
    uptime FLOAT,                        -- NULLable
    outgoing BIGINT,                     -- NULLable
    PRIMARY KEY (fight_id, account_name, boon_name)
);
```

**Nouveau modèle :**
```python
class OrmFightPlayerBoon(Base):
    __tablename__ = "fight_player_boons"
    fight_id: Mapped[str] = ...
    account_name: Mapped[str] = ...
    boon_name: Mapped[str] = ...
    uptime: Mapped[float | None] = ...
    outgoing: Mapped[int | None] = ...
```

**Migration :**
1. Créer la table `fight_player_boons`
2. Remplir depuis les colonnes de `fight_player_summaries`
3. Ajouter NOT NULL sur les colonnes BOOLEAN après migration
4. (Optionnel) Supprimer les 28 colonnes après validation — ou les garder comme VUE

**Fichiers modifiés :**
- `apps/api/src/gw2analytics_api/models/fight.py`
- `apps/api/src/gw2analytics_api/services/player_summaries.py` (écriture boons)
- `apps/api/src/gw2analytics_api/services/player_profiles.py` (lecture boons)

### 3.2 Migrer les types INTEGER → BIGINT

```python
# models/fight.py — OrmFightPlayerSummary
total_damage: Mapped[int] = mapped_column(BigInteger, ...)
total_healing: Mapped[int] = mapped_column(BigInteger, ...)
power_damage: Mapped[int | None] = mapped_column(BigInteger, ...)
condi_damage: Mapped[int | None] = mapped_column(BigInteger, ...)

# models/upload.py
size_bytes: Mapped[int] = mapped_column(BigInteger, ...)
```

**Migration Alembic :**
```python
# NOTE: ALTER TABLE ... ALTER COLUMN ... TYPE BIGINT;
# Nécessite un lock de table. À faire en maintenance window.
op.alter_column("fight_player_summaries", "total_damage", type_=sa.BigInteger())
op.alter_column("uploads", "size_bytes", type_=sa.BigInteger())
```

### 3.3 Ajouter created_at / updated_at

```python
# Base ou mixin
class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

**Tables concernées :** `fights`, `fight_agents`, `fight_skills`

### 3.4 Optimiser les types de clés

```python
# fight.py — OrmFight
# id: SHA-256 hex → garder VARCHAR(64) pour compat, mais ajouter un UUID
# Sur les grosses tables, le hash clustering est OK.
# VÉRIFIER : jointures fight_id entre fights et fight_agents → VARCHAR(64) partout
```

**Vérification CI après Phase 3 :**
- `pytest` ✅ (tests adaptés aux nouveaux types)
- Migration testée sur copie de prod
- `ruff check` ✅
- `mypy` ✅

### Phase 3 — Fichiers touchés (10)
```
Modifiés :
  models/fight.py                ← boon normalization + bigint
  models/upload.py               ← bigint
  services/player_summaries.py   ← écriture boons normalisées
  services/player_profiles.py    ← lecture boons normalisées
Nouveaux :
  alembic/versions/              ← 2-3 migrations
```

**Risques :** Élevés. Migrations DB = attention. Nécessite snapshot et test sur copie. La normalisation des boons change les schémas de réponse API.
**Mitigation :** Versionner les migrations. Les anciennes colonnes sont gardées comme vues ou supprimées en dernier.

---

## Phase 4 — Performance (Sprint 4)

### 4.1 Streaming upload — `routes/uploads.py`

**Problème :** `file.file.read()` charge tout en mémoire.

**Solution :**
```python
# Utiliser un fichier temporaire pour les uploads > 10MB
import tempfile

async def _read_upload_streaming(file: UploadFile, max_size: int) -> bytes:
    if file.size and file.size < 10 * 1024 * 1024:
        return await file.read()

    # Streaming vers tempfile
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        while chunk := await file.read(8192):
            tmp.write(chunk)
            if tmp.tell() > max_size:
                tmp.close()
                os.unlink(tmp.name)
                raise HTTPException(413, "File too large")

    # Lire le tempfile pour hash + upload MinIO
    with open(tmp.name, "rb") as f:
        data = f.read()
    os.unlink(tmp.name)
    return data
```

### 4.2 Streaming parse — `services/parse.py`

**Problème :** `list(_parser.parse(evtc_bytes))` charge tous les fights.

**Solution :**
```python
# Garder l'iterator, ne PAS matérialiser en list
fights = _parser.parse(evtc_bytes)  # Iterator, pas list
core_fight = next(fights, None)     # Prendre le premier fight seulement
# Vérifier qu'il n'y a qu'un fight
for extra in fights:
    logger.warning("extra fight ignored: %s", extra.id)
```

### 4.3 Streaming JSONL — `services/event_blob.py`

**Problème :** `"\n".join([event.model_dump_json() for event in events])`

**Solution :**
```python
def _serialize_events_stream(events: list[Event]) -> Iterator[bytes]:
    for event in events:
        yield event.model_dump_json().encode("utf-8") + b"\n"

# Utilisation
import gzip
jsonl_stream = _serialize_events_stream(events)
gz_bytes = b"".join(gzip.compress(line) for line in jsonl_stream)
# Plus efficace : BytesIO + GzipFile writelines
buf = io.BytesIO()
with gzip.GzipFile(fileobj=buf, mode="w") as gz:
    gz.writelines(_serialize_events_stream(events))
gz_bytes = buf.getvalue()
```

### 4.4 Keyset pagination — `routes/players.py`

**Problème :** `LIMIT ? OFFSET ?` → O(n) pour les pages profondes.

**Solution :**
```python
# Avant
stmt = (
    select(...)
    .limit(limit)
    .offset(offset)
)

# Après (keyset pagination)
class PlayerCursor(BaseModel):
    last_damage: int | None = None
    last_account: str | None = None

@router.get("")
def list_players(
    cursor: str | None = Query(None),  # cursor encodé en base64
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_session),
):
    stmt = (
        select(...)
        .order_by(
            func.coalesce(func.sum(OrmFightPlayerSummary.total_damage), 0).desc(),
            OrmFightPlayerSummary.account_name.asc(),
        )
        .limit(limit + 1)  # +1 pour has_more
    )
    if cursor:
        decoded = json.loads(base64.urlsafe_b64decode(cursor))
        stmt = stmt.where(
            or_(
                func.coalesce(func.sum(...), 0) < decoded["last_damage"],
                and_(
                    func.coalesce(func.sum(...), 0) == decoded["last_damage"],
                    OrmFightPlayerSummary.account_name > decoded["last_account"],
                ),
            )
        )

    rows = db.execute(stmt).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    # Construire le cursor pour la page suivante
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps({
                "last_damage": last.total_damage,
                "last_account": last.account_name,
            }).encode()
        ).decode()
```

### 4.5 Cache Redis pour requêtes fréquentes

**Nouveau fichier :** `services/cache_service.py`
```python
import json
from typing import Any
import redis.asyncio as aioredis

class CacheService:
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis = aioredis.from_url(redis_url)

    async def get_or_compute(
        self, key: str, ttl: int, compute: callable
    ) -> Any:
        cached = await self._redis.get(key)
        if cached:
            return json.loads(cached)
        value = await compute()
        await self._redis.setex(key, ttl, json.dumps(value))
        return value
```

**Points d'insertion du cache :**
- `GET /api/v1/players` — Cache 60s pour la liste des joueurs
- `GET /api/v1/skills` — Cache 300s (le catalogue change rarement)
- `GET /api/v1/fights/{id}/squads` — Cache 300s (données immutables après parse)

### 4.6 UPSERT au lieu de DELETE+INSERT

**Dans `services/player_summaries.py` :**
```python
# Avant
db.execute(delete(OrmFightPlayerSummary).where(...))
for ...:
    db.add(OrmFightPlayerSummary(...))

# Après
from sqlalchemy.dialects.postgresql import insert as postgres_insert

stmt = postgres_insert(OrmFightPlayerSummary).values([
    {...} for ... in rows
])
stmt = stmt.on_conflict_do_update(
    constraint="pk_fight_player_summaries",
    set_={...updated fields...},
)
db.execute(stmt)
```

### Phase 4 — Fichiers touchés (12)
```
Modifiés :
  routes/uploads.py              ← streaming upload
  services/parse.py              ← streaming parse
  services/event_blob.py         ← streaming JSONL + gzip
  services/player_summaries.py   ← UPSERT
  routes/players.py              ← keyset pagination
  routes/skills.py               ← cache
Nouveaux :
  services/cache_service.py      ← cache Redis
```

**Vérification CI :**
- `pytest` ✅
- `ruff check` ✅  
- `mypy` ✅
- Coverage >= 90% ✅
- Benchmarks : `libs/scripts/bench_aggregators.py` ✓

---

## Phase 5 — Qualité du Code + Dette Technique (Sprint 5)

### 5.1 Refactorer les fonctions trop longues

**Cibles :**
| Fonction | Lignes | Action |
|----------|--------|--------|
| `_persist_player_summaries` | 200+ | Extraire : boon aggregation, role detection, bucket management |
| `process_parse` | 90+ | Extraire : parse, save, blob persist, error handling |
| `create_upload` | 110+ | Extraire : validation, dedup, storage, enqueue |
| `_validate_webhook_url` | 80+ | Extraire : DNS resolution, IP check, scheme validation |

### 5.2 Supprimer le code mort

**Cibles :**
| Fichier | Code mort | Action |
|---------|-----------|--------|
| `services/guild_service.py` | `sync_guilds` stub | Supprimer ou implémenter |
| `workers/parser_settings.py` | `if _REDIS_PORT == 1` guard | Supprimer |
| `crypto.py:12-33` | Docstring threat model | Déplacer dans docs/ |
| `schema_guard.py` | Docstring excessive (100+ lignes) | Réduire à 20 lignes |
| `models/fight.py` | `NOTE` comment legacy | Supprimer |

### 5.3 Ajouter des types stricts

**Cibles :**
```python
# AVANT
def process_parse(session_factory, upload_id, raw_bytes):
    ...

# APRÈS
from collections.abc import Callable
from sqlalchemy.orm import Session

def process_parse(
    session_factory: Callable[[], Session],
    upload_id: uuid.UUID,
    raw_bytes: bytes,
) -> None:
    ...
```

**Vérification mypy :**
```bash
mypy --strict apps/api/src libs --ignore-missing-imports
# Objectif : 0 erreurs
```

### 5.4 Génération automatique des types frontend

**Ajout dans `web/package.json` :**
```json
{
  "scripts": {
    "generate-api": "openapi-typescript http://localhost:8000/openapi.json -o src/lib/api-types.ts"
  }
}
```

**Ou mieux :** Utiliser `orval` pour générer un client complet :
```bash
npm install -D orval
```

**Fichier `orval.config.ts` :**
```typescript
export default {
  api: {
    input: "http://localhost:8000/openapi.json",
    output: {
      target: "./src/lib/api-client.ts",
      client: "fetch",
    },
  },
};
```

### 5.5 CI Security — Secrets scanning + Trivy

**Nouveaux hooks pre-commit :**
```yaml
# .pre-commit-config.yaml — à ajouter
- repo: https://github.com/Yelp/detect-secrets
  rev: v1.5.0
  hooks:
    - id: detect-secrets
      args: ["--baseline", ".secrets.baseline"]
```

**Nouveau job CI :**
```yaml
# .github/workflows/security.yml — à ajouter
name: Security scan
on: [pull_request]
jobs:
  trivy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aquasecurity/trivy-action@master
        with:
          scan-type: "fs"
          severity: "HIGH,CRITICAL"
```

**Vérification :**
- `detect-secrets` scan ✅
- `trivy fs .` ✅ (0 HIGH+)

### 5.6 Ajouter ADR (Architecture Decision Records)

**Nouveau dossier :** `docs/adr/`

```
docs/adr/
├── 001-repository-pattern.md
├── 002-service-layer.md
├── 003-boon-normalization.md
├── 004-keyset-pagination.md
├── 005-streaming-uploads.md
```

**Template :**
```markdown
# ADR 001 — Repository Pattern

## Contexte
Les routes accèdent directement à SQLAlchemy, créant un couplage fort API/DB.

## Décision
Introduire un Repository layer entre les services et l'ORM.

## Conséquences
- Testabilité améliorée
- Isolation DB
- Plus de code (boilerplate)

## Status
Accepté
```

### Phase 5 — Fichiers touchés (25+)
```
Modifiés :
  services/player_summaries.py
  services/parse.py
  routes/uploads.py
  routes/webhooks.py
  services/guild_service.py
  workers/parser_settings.py
  crypto.py
  schema_guard.py
  models/fight.py
  .pre-commit-config.yaml
Nouveaux :
  .github/workflows/security.yml
  .secrets.baseline
  docs/adr/001-repository-pattern.md
  docs/adr/002-service-layer.md
  docs/adr/003-boon-normalization.md
  docs/adr/004-keyset-pagination.md
  docs/adr/005-streaming-uploads.md
  web/orval.config.ts
```

**Vérification CI :**
- `pytest` ✅
- `ruff check` ✅ (strict)
- `mypy --strict` ✅
- Coverage >= 90% ✅
- `pip-audit` ✅
- `detect-secrets` ✅
- `trivy fs .` ✅ (0 HIGH+)

---

## Phase 6 — Monitoring et Observabilité (Sprint 6 — Bonus)

### 6.1 Ajouter OpenTelemetry

```python
# main.py — à ajouter
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

tracer = trace.get_tracer(__name__)
FastAPIInstrumentor.instrument_app(app)
SQLAlchemyInstrumentor().instrument(engine=get_engine())
```

### 6.2 Ajouter structured logging (déjà partiel avec `_JsonFormatter`)

- Étendre à tous les workers Arq
- Ajouter `request_id` middleware
- Ajouter `trace_id` aux logs

### 6.3 Dashboard Grafana

- Créer dashboard JSON (`monitoring/grafana-dashboard.json`)
- Métriques clés : upload rate, parse duration, error rate, webhook delivery rate

---

## Phase 7 — Documentation et CI (Sprint 7 — Bonus)

### 7.1 Mettre à jour CONTRIBUTING.md
- Ajouter la procédure de migration
- Ajouter les conventions de code (Repository, Service)

### 7.2 Ajouter pre-commit hooks supplémentaire
```yaml
# .pre-commit-config.yaml
- repo: https://github.com/pre-commit/mirrors-mypy
  rev: v2.2.0
  hooks:
    - id: mypy
      args: [--strict]
```

### 7.3 Ajouter GitHub Actions workflow de migration test
```yaml
name: Test migrations
on: [pull_request]
jobs:
  migration-test:
    services:
      postgres:
        image: postgres:16-alpine
    steps:
      - uses: actions/checkout@v4
      - run: uv run alembic upgrade head
      - run: uv run alembic downgrade -1
      - run: uv run alembic upgrade head  # round-trip
```

---

## Tableau de Bord — Suivi de l'Avancement

| Phase | Description | Fichiers | Dépendances | Statut |
|-------|-------------|----------|-------------|--------|
| 0 | Préparation / Baseline | CI config | Aucune | ✅ |
| 1 | Quick Wins DB + Sécurité | 16 | Phase 0 | ✅ |
| 2 | Repository + Service Layer | 18 | Phase 1 | ✅ |
| 3 | Normalisation Schéma | 10 | Phase 2 | ✅ |
| 4 | Performance | 12 | Phase 2 | ✅ |
| 5 | Qualité + Dette | 25+ | Phase 2,3,4 | ✅ |
| 6 | Monitoring (Bonus) | 5 | Phase 2 | ✅ |
| 7 | Documentation (Bonus) | 5 | Phase 5 | ✅ |

### Ordre conseillé

Le plan est conçu pour être exécuté DANS L'ORDRE :

1. **Phase 0** (1 jour) — Baseline, branches, CI
2. **Phase 1** (3-4 jours) — Indolore, CI passe, bénéfice immédiat
3. **Phase 2** (2 semaines) — Le plus gros morceau. À découper en PRs par route
4. **Phase 3** (1 semaine) — Dépend du nouveau service layer
5. **Phase 4** (1 semaine) — Dépend du nouveau service layer
6. **Phase 5** (1 semaine) — Dépend des phases 2-4
7. **Phase 6-7** (1 semaine) — Bonus, indépendant

### Risques et Mitigations

| Risque | Probabilité | Mitigation |
|--------|------------|------------|
| Migration DB bloque la prod | Faible | Tester sur copie, fenêtre de maintenance |
| Régression API après refactoring routes | Moyenne | Tests golden avant/après, PRs atomiques |
| Perte de coverage | Faible | CI bloque si coverage baisse |
| Refactoring trop long | Moyenne | Chaque phase est indépendante et mergable |
| Conflit git avec features en cours | Haute | Coordination, feature flags |

---

## Checklist de merge pour chaque PR

Chaque PR de refactoring DOIT passer cette checklist :

- [ ] `pytest` ✅ (vert, coverage >= 90%)
- [ ] `ruff check` ✅ (0 erreurs, 0 warnings)
- [ ] `mypy` ✅ (0 erreurs)
- [ ] `pip-audit` ✅ (0 vulnérabilités)
- [ ] `ruff format --check` ✅
- [ ] Tests golden ajoutés (si changement de comportement)
- [ ] Migration Alembic testée (si changement DB)
- [ ] Pas de TODO / FIXME / XXX ajouté
- [ ] Documentation mise à jour (si API change)
- [ ] CHANGELOG.md mis à jour
- [ ] Revue de code par au moins 1 pair

---

**Temps estimé total :** ~8-10 semaines (2-3 devs)
**Note cible :** 76/100 (actuel : 49/100)
**Dette restante après :** ~24/100 (monolithe, pas d'event sourcing, pas de tests E2E frontend)