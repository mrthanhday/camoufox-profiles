# Phase 3 Implementation Plan - cfox-server + Cloud Sync

> Version: 2.0 | Date: 2026-05-09 | Based on ARCHITECTURE_V5.md + Review Feedback

---

## Context

cfox-server is a **self-hosted dedicated server** for individuals or small teams to manage
profiles across multiple machines. It is NOT a public cloud service — the user deploys and
manages their own instance (Docker + PostgreSQL).

## Overview

Phase 3 adds cfox-server and integrates it with cfox-local for distributed profile management.
Cloud profiles can be launched from any machine with lock-protected session handover and
essential data sync.

### Architecture

```
cfox-local :7600 ----REST+WS----> Web UI (React)
       |
       +----httpx----> cfox-server :8700 ----SQLAlchemy----> PostgreSQL
                              |
                              +----filesystem----> essential_data/
```

### Key Design Decision: Unified Data Layer

Both cfox-local and cfox-server use **SQLAlchemy 2.0 async ORM** with shared model definitions:

| Component | Engine | Connection |
|-----------|--------|------------|
| cfox-local | SQLite | `sqlite+aiosqlite:///profiles.db` |
| cfox-server | PostgreSQL | `postgresql+asyncpg://...` |

**Shared models** live in `src/camoufox_profiles/models_sa.py` (new SQLAlchemy models).
The existing `store.py` (raw SQL) will be **replaced** by `store_sa.py` using SQLAlchemy queries.
This eliminates data model divergence and simplifies dual-source merge.

**Migration path**: Alembic with auto-migrate on startup for both backends.

### Sub-phases

| # | Sub-phase | Files | Effort |
|---|-----------|-------|--------|
| 3.0 | Unified data layer refactor | 3 new + 2 modify | High |
| 3.1 | cfox-server scaffolding | 5 new + 1 config | Medium |
| 3.2 | Profile CRUD + Lock protocol | 4 new | High |
| 3.3 | Essential data storage | 2 new | High |
| 3.4 | Sync service (local, no server needed) | 1 new | Very High |
| 3.5 | cfox-local cloud client | 2 new | Medium |
| 3.6 | Upload queue + Heartbeat | 2 new | Medium-High |
| 3.7 | Dual-source modification | 3 modify | Very High |
| 3.8 | Docker + Deployment | 2 new + 1 modify | Low-Medium |

---

## 3.0 Unified Data Layer Refactor

### Goal
Replace raw SQL + dataclass models with SQLAlchemy ORM models shared between local and server.
Existing `store.py` becomes a thin wrapper around SQLAlchemy queries.

### Files to Create

#### NEW: `src/camoufox_profiles/models_sa.py`
SQLAlchemy 2.0 declarative models (dialect-agnostic):
```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Text, Boolean, DateTime, JSON, ForeignKey

class Base(DeclarativeBase):
    pass

class ProfileModel(Base):
    __tablename__ = "profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_used_at: Mapped[str | None] = mapped_column(Text)
    target_os: Mapped[str] = mapped_column(String(20), nullable=False)
    fingerprint_config: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string
    proxy_server: Mapped[str | None] = mapped_column(Text)
    proxy_username: Mapped[str | None] = mapped_column(Text)
    proxy_password: Mapped[str | None] = mapped_column(Text)
    user_data_dir: Mapped[str] = mapped_column(Text, nullable=False)
    total_sessions: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON array string
    notes: Mapped[str] = mapped_column(Text, default="")
    drift_schedule: Mapped[str] = mapped_column(Text, default="{}")  # JSON string
    firefox_base_version: Mapped[int | None] = mapped_column(Integer)
    proxy_id: Mapped[str | None] = mapped_column(String(36))
    warmup_completed: Mapped[int] = mapped_column(Integer, default=0)
    creation_ip: Mapped[str | None] = mapped_column(Text)
    creation_region: Mapped[str | None] = mapped_column(Text)
    last_known_ip: Mapped[str | None] = mapped_column(Text)
    last_known_region: Mapped[str | None] = mapped_column(Text)
    # Phase 3 cloud fields (nullable, unused until cloud enabled)
    locked_by: Mapped[str | None] = mapped_column(String(36))
    lock_token: Mapped[str | None] = mapped_column(String(36))
    locked_at: Mapped[str | None] = mapped_column(Text)
    lock_expires_at: Mapped[str | None] = mapped_column(Text)
    essential_data_version: Mapped[int] = mapped_column(Integer, default=0)
    essential_data_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    essential_data_checksum: Mapped[str | None] = mapped_column(String(64))
    sync_incomplete: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[str | None] = mapped_column(Text)
    last_sync_machine: Mapped[str | None] = mapped_column(String(36))
    last_heartbeat_at: Mapped[str | None] = mapped_column(Text)

class DriftEventModel(Base):
    __tablename__ = "drift_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id", ondelete="CASCADE"))
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    drift_type: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[str] = mapped_column(Text, default="")
    new_value: Mapped[str] = mapped_column(Text, default="")

class ProxyPoolModel(Base):
    __tablename__ = "proxy_pool"
    # ... same fields as current schema

class TagMetaModel(Base):
    __tablename__ = "tags_meta"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    color: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

# Phase 3: Multi-user auth
class UserModel(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="member")  # "admin", "member"
    label: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_used_at: Mapped[str | None] = mapped_column(Text)
```

#### NEW: `src/camoufox_profiles/db.py`
Shared database engine factory:
```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

def create_engine(url: str):
    """Create engine for sqlite+aiosqlite:// or postgresql+asyncpg://"""
    return create_async_engine(url, echo=False)

def create_session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)

async def init_db(engine):
    """Auto-create tables (auto-migrate on startup)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

#### NEW: `src/camoufox_profiles/store_sa.py`
SQLAlchemy-based ProfileStore replacing raw SQL store.py:
- Same public API as current `ProfileStore` (create, get, list, update, delete, count, etc.)
- Uses SQLAlchemy async sessions instead of raw aiosqlite
- Conversion helpers: `ProfileModel` ↔ `Profile` dataclass (keep dataclass for business logic)

### Files to Modify

#### MODIFY: `src/camoufox_profiles/manager.py`
- Switch from `ProfileStore` (raw SQL) to `ProfileStoreSA` (SQLAlchemy)
- Pass database URL from config

#### MODIFY: `cfox_local/config.py`
- Add `database_url` field (default: `sqlite+aiosqlite:///{base_dir}/profiles.db`)

### Backward Compatibility
- Existing SQLite databases migrated via Alembic auto-migration on first startup
- `store.py` kept but deprecated (not imported by default)
- `models.py` dataclasses kept as business layer DTOs

---

## 3.1 cfox-server Scaffolding

### Goal
New FastAPI app using shared data layer, multi-user API key auth, Docker-ready.

### Files to Create

#### NEW: `cfox_server/__init__.py`
Empty init.

#### NEW: `cfox_server/config.py`
```python
class Settings(BaseSettings):
    database_url: str  # postgresql+asyncpg://user:pass@host:5432/cfox
    storage_dir: Path = Path("data/essential_data")
    host: str = "0.0.0.0"
    port: int = 8700
    lock_ttl_minutes: int = 120
    lock_cleanup_interval_seconds: int = 60
    max_versions: int = 3
    admin_api_key: str  # initial admin key, set via env var
```

#### NEW: `cfox_server/app.py`
- FastAPI app factory with lifespan
- Lifespan: init DB (shared `init_db()`), start lock TTL cleanup task
- Include route modules
- API key middleware (validate Bearer token, lookup in `users` table)
- CORS for cfox-local origins

#### NEW: `cfox_server/middleware.py`
- `APIKeyMiddleware`: validate Bearer token against `users.api_key_hash`
- Track `last_used_at` per user
- Extract user role for permission checks
- Exclude `/api/health` from auth

#### NEW: `cfox_server/schemas.py`
Pydantic v2 schemas for request/response:
- `ProfileCreate`, `ProfileUpdate`, `ProfileResponse`, `ProfileListResponse`
- `LockRequest`, `LockResponse`, `HeartbeatRequest`, `UnlockRequest`
- `EssentialDataInfo`, `VersionListItem`
- `UserCreate`, `UserResponse`, `UserListResponse`

### Files to Modify

#### MODIFY: `pyproject.toml`
- Add `cfox-server` entry point
- Add dependencies: sqlalchemy[asyncio]>=2.0, asyncpg>=0.29, aiosqlite>=0.20, alembic>=1.13

---

## 3.2 Profile CRUD + Lock Protocol

### Goal
REST API for cloud profile management with optimistic concurrency and lock protocol.

### Files to Create

#### NEW: `cfox_server/routes/__init__.py`
Empty init.

#### NEW: `cfox_server/routes/profiles.py`
- `GET /api/profiles` -> list all (filter by tag, os, pagination: `?limit=50&offset=0`)
- `POST /api/profiles` -> create (returns 201)
- `GET /api/profiles/{id}` -> detail
- `PUT /api/profiles/{id}` -> update (requires `If-Match` header, returns 409 on conflict)
- `DELETE /api/profiles/{id}` -> delete (cannot delete locked profile)

Uses shared `ProfileStoreSA` — same query logic as cfox-local.

#### NEW: `cfox_server/routes/locks.py`
- `POST /api/profiles/{id}/lock` -> acquire lock (body: machine_id, ttl_minutes)
  - If already locked + not expired -> 423 {locked_by, expires_at}
  - If expired -> overwrite silently
  - Returns: lock_token, previous_lock info (including `last_heartbeat_at` for race detection)
- `PUT /api/profiles/{id}/heartbeat` -> renew lock (validates lock_token + machine_id)
  - Updates lock_expires_at = now + ttl
  - Invalid token -> 403
- `DELETE /api/profiles/{id}/lock` -> release lock (validates lock_token + machine_id)
  - If token mismatch (lock was reacquired by another machine) -> 403 (handle gracefully)
- `POST /api/profiles/{id}/lock/force` -> force unlock (admin role only)

#### NEW: `cfox_server/routes/users.py`
- `GET /api/users` -> list users (admin only)
- `POST /api/users` -> create user + generate API key (admin only)
- `DELETE /api/users/{id}` -> remove user (admin only)
- `PUT /api/users/{id}/role` -> change role (admin only)
- `POST /api/users/{id}/rotate-key` -> regenerate API key

#### NEW: `cfox_server/services/lock_service.py`
- `cleanup_expired_locks()` -> background task, runs every 60s
  - Finds profiles where lock_expires_at < now AND locked_by IS NOT NULL
  - Clears lock fields
- Helper: `validate_lock_ownership(profile, lock_token, machine_id)` -> bool

---

## 3.3 Essential Data Storage

### Goal
Upload/download essential data ZIPs with versioning, checksum, and rollback.

### Files to Create

#### NEW: `cfox_server/routes/storage.py`
- `PUT /api/profiles/{id}/essential_data` -> upload
  - Headers: `If-Match: <base_version>`, `Content-SHA256: <sha256>`, `X-Lock-Token: <token>`
  - Validates lock_token ownership
  - Validates If-Match (409 if mismatch)
  - Validates Content-SHA256 (400 if mismatch)
  - Saves ZIP to `storage_dir/{profile_id}/`
  - Rotates versions (keep last 3)
  - Updates metadata: version++, checksum, size, sync_incomplete=false
  - **Warning**: if size > 200MB, return header `X-Warning: large-upload`
- `GET /api/profiles/{id}/essential_data` -> download current ZIP
  - Response header: `Content-SHA256`
- `GET /api/profiles/{id}/essential_data/info` -> {version, size, checksum, uploaded_at}
- `GET /api/profiles/{id}/essential_data/versions` -> list retained versions
- `POST /api/profiles/{id}/essential_data/rollback/{version}` -> rollback

#### NEW: `cfox_server/services/storage_service.py`
- `save_version(profile_id, version, zip_bytes, checksum)` -> path
- `get_current_path(profile_id, version)` -> Path
- `rotate_versions(profile_id, max_versions=3)` -> deletes oldest
- `verify_checksum(zip_bytes, expected_sha256)` -> bool
- `get_version_list(profile_id)` -> list of VersionInfo

---

## 3.4 Sync Service (Local — No Server Dependency)

### Goal
Collect essential browser data into ZIP, restore cleanly. Copy-before-zip pattern.
SHA-256 checksum verification. **This is the core risk — implement and test early.**

> Moved before cloud client (was 3.5) because it has NO server dependency
> and is the highest-risk component. Can be tested entirely with local Firefox profiles.

### Files to Create

#### NEW: `cfox_local/services/__init__.py`
Empty init.

#### NEW: `cfox_local/services/sync_service.py`

**ESSENTIAL_PATTERNS constant (configurable):**
```python
ESSENTIAL_PATTERNS = [
    "cookies.sqlite*",              # cookies + WAL
    "webappsstore.sqlite*",         # localStorage
    "storage/default/",             # IndexedDB, Cache API, Service Workers
    "serviceworker.txt",
    "SiteSecurityServiceState.txt", # HSTS
    "permissions.sqlite*",          # site permissions (notifications, geo, etc.)
    "formhistory.sqlite*",          # form autofill data
    "content-prefs.sqlite*",        # per-site zoom, encoding prefs
]
```

**Functions:**

- `collect_essential_data(user_data_dir: Path, patterns: list[str] | None = None) -> tuple[bytes, str]`
  1. Create temp copy directory
  2. Copy essential files from user_data_dir to temp (using patterns or ESSENTIAL_PATTERNS)
  3. Create ZIP from temp copy (never ZIP from live directory)
  4. Return (ZIP bytes, SHA-256 checksum)

- `restore_essential_data(user_data_dir: Path, zip_bytes: bytes, expected_checksum: str | None = None) -> None`
  1. Verify SHA-256 if expected_checksum provided -> reject if mismatch
  2. Delete existing essential files + cache directories
  3. Extract ZIP cleanly into user_data_dir
  4. Clear cache2/ and startupCache/ directories

- `compute_sha256(data: bytes) -> str`

---

## 3.5 cfox-local Cloud Client

### Goal
HTTP client in cfox-local for communicating with cfox-server.

### Files to Create

#### NEW: `cfox_local/services/cloud_client.py`
- `CloudClient` class:
  - Constructor: base_url, api_key
  - Internal httpx.AsyncClient with Bearer auth header
  - `request(method, path, **kwargs)` -> wrapper with retry on 5xx
  - Profile CRUD: create, get, list, update, delete
  - Lock protocol: acquire_lock, heartbeat, release_lock
  - Essential data: upload, download
  - Connection: health_ping, is_connected property
  - Retry config: 3 retries, exponential backoff, max 30s per attempt
  - **Cloud profile cache**: cache `list()` results for 30s, invalidate on any write operation

#### NEW: `cfox_local/routes/server.py`
- `GET /api/server/status` -> {connected, server_url, last_ping, user_role}
- `POST /api/server/connect` -> {url, api_key} -> validate + save
- `POST /api/server/disconnect` -> disable cloud

#### MODIFY: `cfox_local/config.py`
- Add fields: server_url, server_api_key, cloud_enabled

#### MODIFY: `cfox_local/app.py`
- Include server route module
- Init CloudClient if configured

---

## 3.6 Upload Queue + Heartbeat Service

### Goal
Reliable upload queue with deduplication and graduated heartbeat failure handling.

### Files to Create

#### NEW: `cfox_local/services/upload_queue.py`
- `UploadQueue` class:
  - `_queue: dict[profile_id, UploadTask]`
  - `_semaphore: asyncio.Semaphore(3)`
  - `enqueue(profile_id, session_data)` -> dedup by profile_id
  - `_worker(profile_id)` -> internal coroutine:
    1. Acquire semaphore
    2. Collect essential data
    3. Upload with retry (5 retries, exponential backoff, max 300s delay)
    4. Emit WS event: progress, complete, or failed
    5. Release semaphore

#### NEW: `cfox_local/services/heartbeat_service.py`
- `HeartbeatService` class:
  - `start(profile_id, lock_token, machine_id)` -> background task every 30s
  - Graduated failure handling:
    - 2 fails (60s): WS `heartbeat_warning` event
    - 5 fails (150s): WS `heartbeat_critical` event
    - 10 fails (300s): **force-close browser context** + `heartbeat_death` event
      - Must prevent continued use of stale data (split-brain protection)
  - `stop(profile_id)` -> cancel background task
  - `stop_all()` -> cancel all

---

## 3.7 Dual-Source Modification

### Goal
Modify existing cfox-local code to support cloud profiles alongside local.

### Files to Modify

#### MODIFY: `cfox_local/session_manager.py`

Add cloud launch flow:
```python
async def launch_cloud(profile_id, cloud_client, sync_service, heartbeat_service):
    # 1. Acquire lock on server
    lock_result = await cloud_client.acquire_lock(profile_id, machine_id)
    if lock_result.status == 423:
        raise ProfileLockedError(locked_by, expires_at)

    # 2. Download essential data
    zip_bytes, checksum = await cloud_client.download_essential_data(profile_id)

    # 3. Restore essential data (clean extract + cache clear)
    await sync_service.restore_essential_data(user_data_dir, zip_bytes, checksum)

    # 4. Launch browser with restored data
    session = await launch_browser(profile_id, ...)

    # 5. Start heartbeat
    heartbeat_service.start(profile_id, lock_token, machine_id)

    # 6. Store lock_token + base_version in session
    session.lock_token = lock_token
    session.base_version = lock_result.version
```

Cloud stop flow:
```python
async def stop_cloud(session):
    # 1. Stop heartbeat
    heartbeat_service.stop(session.profile_id)

    # 2. Close browser context
    await session.context.close()

    # 3. Collect essential data
    zip_bytes, checksum = await sync_service.collect(user_data_dir)

    # 4. Upload essential data
    await cloud_client.upload_essential_data(
        session.profile_id, zip_bytes,
        base_version=session.base_version, lock_token=session.lock_token
    )

    # 5. Release lock (handle 403 gracefully if lock was reacquired)
    try:
        await cloud_client.release_lock(session.profile_id, session.lock_token, machine_id)
    except LockTokenMismatchError:
        logger.warning("Lock was reacquired by another machine, skipping release")
```

Heartbeat death handler (split-brain protection):
```python
async def on_heartbeat_death(profile_id):
    """Force-close browser when heartbeat dies — another machine may have taken over."""
    session = self._sessions.get(profile_id)
    if session and session._context:
        await session._context.close()
    # Emit UI warning: "Session expired - lock lost"
    EventBus.emit("session_expired", {id: profile_id, reason: "heartbeat_death"})
```

Crash handler:
```python
async def on_browser_disconnect(session):
    if session.source == "cloud":
        try:
            await stop_cloud(session)
            EventBus.emit("session_closed", {id, "sync": "ok"})
        except Exception:
            upload_queue.enqueue(session.profile_id, session)
            EventBus.emit("session_closed", {id, "sync": "retry_pending"})
```

#### MODIFY: `cfox_local/routes/profiles.py`

Merge local + cloud profiles with cached cloud data:
```python
async def list_profiles(source: str | None = None):
    profiles = []
    if source != "cloud":
        local = await local_store.list()
        for p in local:
            p._source = "local"  # annotate source
        profiles.extend(local)
    if source != "local" and cloud_client and cloud_client.is_connected:
        cloud_profiles = await cloud_client.get_profiles()  # cached 30s
        for p in cloud_profiles:
            p._source = "cloud"
        profiles.extend(cloud_profiles)
    profiles.sort(key=lambda p: p.last_used_at or "", reverse=True)
    return {"profiles": profiles, "server_connected": cloud_client.is_connected if cloud_client else False}
```

Route by source for profile-specific operations (GET, PUT, DELETE).

#### MODIFY: `cfox_local/routes/proxies.py`
- When cloud connected: list = cloud primary + local fallback
- Add proxy: if cloud connected, add to cloud pool first

---

## 3.8 Docker + Deployment

### Goal
Production-ready deployment for self-hosted cfox-server.

### Files to Create

#### NEW: `cfox_server/Dockerfile`
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY cfox_server/ ./cfox_server/
COPY src/camoufox_profiles/ ./src/camoufox_profiles/
RUN pip install -e ".[server]"
EXPOSE 8700
CMD ["cfox-server"]
```

#### NEW: `docker-compose.yml`
```yaml
services:
  cfox-server:
    build: .
    ports: ["8700:8700"]
    environment:
      DATABASE_URL: postgresql+asyncpg://cfox:cfox@db:5432/cfox
      ADMIN_API_KEY: ${ADMIN_API_KEY}
    volumes:
      - essential_data:/app/data/essential_data
    depends_on: [db]

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: cfox
      POSTGRES_PASSWORD: cfox
      POSTGRES_DB: cfox
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
  essential_data:
```

#### MODIFY: `pyproject.toml`
- Add `cfox-server` entry point
- Add `[server]` extras: asyncpg>=0.29, pydantic-settings>=2.0
- Add shared deps: sqlalchemy[asyncio]>=2.0, aiosqlite>=0.20

---

## Dependency Graph

```
3.0 Unified data layer (prerequisite for ALL)
  |
  +---> 3.1 cfox-server scaffolding
  |       |
  |       +---> 3.2 Profile CRUD + Lock + Users
  |       |       |
  |       |       +---> 3.3 Essential data storage
  |       |
  |       +---> 3.8 Docker (can start early)
  |
  +---> 3.4 Sync service (parallel with server, NO server dependency)
          |
          +---> 3.5 Cloud client
                  |
                  +---> 3.6 Upload queue + Heartbeat
                          |
                          +---> 3.7 Dual-source modification
```

3.0 must complete first. Then 3.1-3.3 (server) and 3.4 (sync) can run in parallel.

---

## Resolved Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Profile ID strategy | UUID4 for both local and cloud. Shared ID space. |
| 2 | Multi-user | Yes — `users` table with `role` (admin/member), API key per user |
| 3 | Essential data max size | No hard limit. Warning header when > 200MB |
| 4 | Migration strategy | Auto-migrate on startup (`Base.metadata.create_all`) |
| 5 | Cloud cache strategy | Cache cloud profile list 30s, invalidate on any write operation |
| 6 | ESSENTIAL_PATTERNS | Extended: + `permissions.sqlite*`, `formhistory.sqlite*`, `content-prefs.sqlite*` |
| 7 | UI Phase 3 | Deferred — backend-first, UI in separate phase |
| 8 | Monitoring | Not needed for self-hosted |

---

## Reference

| Document | Purpose |
|----------|---------|
| `docs/ARCHITECTURE_V5.md` | Full system architecture |
| `docs/IMPLEMENTATION_PLAN.md` | Original 4-phase plan |
| `docs/PROGRESS.md` | Current progress tracker |
| `docs/TRACKING.md` | Per-file implementation checklist |
| `docs/TEST_STRATEGY.md` | Test sandbox + test cases |
