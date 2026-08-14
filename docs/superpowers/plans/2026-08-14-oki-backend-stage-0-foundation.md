# Oki Backend Stage 0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the runnable FastAPI/PostgreSQL 18/Celery/Keycloak foundation, shared contracts, workflow kernel, and authorization boundary used by every later stage.

**Architecture:** A modular monolith exposes FastAPI routes and deploys queue-specific Celery workers from the same package. PostgreSQL is authoritative; Redis transports tasks and caches only disposable state.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 async, Alembic, PostgreSQL 18, Celery, Redis, Keycloak OIDC, pytest, testcontainers, Ruff, mypy, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-14-oki-localization-backend-design.md`

## Global Constraints

- PostgreSQL 18 is the authoritative database.
- All identifiers are UUIDv7-compatible UUID values exposed as strings in JSON.
- API failures use RFC 9457 problem details with stable `code` and `correlation_id` fields.
- Every command endpoint requires `Idempotency-Key`.
- Heavy work starts only through command endpoints and never through dashboard reads.
- No application secret, token, password, or production credential is committed.
- Use UTC timestamps and integer milliseconds for media coordinates.
- Avoid provider-specific types outside adapter modules.
- The directory is not currently a Git repository; omit commit commands until the owner initializes Git.

---

### Task 1: Python workspace and application kernel

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.env.example`
- Create: `src/oki/__init__.py`
- Create: `src/oki/main.py`
- Create: `src/oki/config.py`
- Create: `src/oki/api/errors.py`
- Create: `src/oki/api/middleware.py`
- Create: `src/oki/db/base.py`
- Create: `src/oki/db/session.py`
- Create: `src/oki/domain/types.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_app.py`

**Interfaces:**
- Produces: `create_app(settings: Settings | None = None) -> FastAPI`.
- Produces: `Settings`, `get_settings()`, `DatabaseSession`, `Problem`, `ProblemException`, `IdempotencyKey`, `UtcDateTime`, and `MediaMilliseconds`.
- Consumes: no earlier application code.

- [ ] **Step 1: Write the failing app and error-contract tests**

```python
from fastapi.testclient import TestClient
from oki.main import create_app


def test_health_is_available_without_auth() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_problem_response_has_stable_shape() -> None:
    response = TestClient(create_app()).get("/api/_test/not-found")
    body = response.json()
    assert response.status_code == 404
    assert body["type"].startswith("https://errors.oki.app/")
    assert body["code"] == "resource_not_found"
    assert body["correlation_id"]
```

- [ ] **Step 2: Run the focused test and observe the missing package failure**

Run: `uv run pytest tests/unit/test_app.py -q`  
Expected: collection fails because `oki` is not importable.

- [ ] **Step 3: Define dependencies and the application kernel**

`pyproject.toml` must define the `src` package, Python `>=3.12,<3.14`, FastAPI, Uvicorn, Pydantic Settings, SQLAlchemy asyncpg, Alembic, Celery Redis, Authlib/PyJWT cryptography, HTTPX, boto3, structlog, OpenTelemetry, Sentry, and test/type/lint groups. `create_app` must install correlation, problem, and structured-request middleware; register `/health`; and expose `/openapi.json`.

```python
def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="Oki Creator Localization Engine", version="1.0.0")
    app.state.settings = resolved
    install_middleware(app)
    register_problem_handlers(app)
    app.include_router(health_router)
    return app
```

- [ ] **Step 4: Run the focused tests**

Run: `uv run pytest tests/unit/test_app.py -q`  
Expected: both tests pass.

### Task 2: PostgreSQL models, migrations, and portable services

**Files:**
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/0001_foundation.py`
- Create: `src/oki/db/mixins.py`
- Create: `src/oki/db/uow.py`
- Create: `src/oki/health.py`
- Create: `compose.yaml`
- Create: `docker/api.Dockerfile`
- Create: `docker/worker.Dockerfile`
- Create: `tests/integration/test_database.py`
- Create: `tests/integration/test_health_dependencies.py`

**Interfaces:**
- Consumes: `Settings` and SQLAlchemy `Base` from Task 1.
- Produces: `UnitOfWork`, `TimestampMixin`, `VersionMixin`, database readiness, and containers named `postgres`, `redis`, `minio`, `keycloak`, and `clamav`.

- [ ] **Step 1: Write database transaction and readiness tests**

```python
async def test_unit_of_work_rolls_back_on_error(uow_factory) -> None:
    with pytest.raises(RuntimeError):
        async with uow_factory() as uow:
            await uow.session.execute(text("create temporary table should_rollback(id int)"))
            raise RuntimeError("stop")
    async with uow_factory() as uow:
        exists = await uow.session.scalar(text("select to_regclass('pg_temp.should_rollback')"))
    assert exists is None
```

- [ ] **Step 2: Run integration tests against PostgreSQL 18**

Run: `uv run pytest tests/integration/test_database.py tests/integration/test_health_dependencies.py -q`  
Expected: fail because migrations, UoW, and dependency probes do not exist.

- [ ] **Step 3: Implement foundation schema and Compose topology**

Migration `0001_foundation` creates `users`, `organizations`, `memberships`, `roles`, `permissions`, `role_permissions`, `idempotency_records`, `outbox_events`, `audit_events`, and `security_events`. Audit tables grant application insert/select but no update/delete through the documented application role. Compose pins PostgreSQL major `18`, exposes health checks, persistent volumes, and no hard-coded non-development secret.

- [ ] **Step 4: Apply migrations and run integration tests**

Run: `uv run alembic upgrade head`  
Expected: exit 0.  
Run: `uv run pytest tests/integration/test_database.py tests/integration/test_health_dependencies.py -q`  
Expected: pass.

### Task 3: Idempotency, transactional outbox, Celery, and workflow kernel

**Files:**
- Create: `src/oki/jobs/enums.py`
- Create: `src/oki/jobs/models.py`
- Create: `src/oki/jobs/idempotency.py`
- Create: `src/oki/jobs/outbox.py`
- Create: `src/oki/jobs/state_machine.py`
- Create: `src/oki/jobs/tasks.py`
- Create: `src/oki/worker.py`
- Create: `migrations/versions/0002_workflow_kernel.py`
- Create: `tests/unit/jobs/test_state_machine.py`
- Create: `tests/integration/jobs/test_idempotency.py`
- Create: `tests/integration/jobs/test_outbox.py`

**Interfaces:**
- Produces: `WorkflowState`, `WorkflowEvent`, `TransitionDecision`, `WorkflowStateMachine.transition(...)`, `IdempotencyService.execute(...)`, `OutboxPublisher.publish_batch(...)`, and Celery app `oki.worker.app`.
- Produces tables: `projects`, `localization_jobs`, `workflow_transitions`, `task_runs`, `task_checkpoints`, `dead_letters`, `outbox_events`, `provider_usage`.
- Consumes: `UnitOfWork`, UUID/time types, and problem errors.

- [ ] **Step 1: Write state and idempotency tests**

```python
def test_publication_cannot_skip_private_and_platform_checks(machine, job) -> None:
    with pytest.raises(InvalidTransition):
        machine.transition(job, WorkflowEvent.PUBLISH_APPROVED)


async def test_same_idempotency_key_returns_original_result(idempotency_service) -> None:
    calls = 0
    async def command():
        nonlocal calls
        calls += 1
        return {"job_id": "01900000-0000-7000-8000-000000000001"}
    first = await idempotency_service.execute("org", "POST:/api/jobs/analyze", "same", command)
    second = await idempotency_service.execute("org", "POST:/api/jobs/analyze", "same", command)
    assert first == second
    assert calls == 1
```

- [ ] **Step 2: Run focused tests**

Run: `uv run pytest tests/unit/jobs tests/integration/jobs -q`  
Expected: fail on missing workflow classes.

- [ ] **Step 3: Implement exact state machine and task records**

Implement the primary sequence from `CREATOR_LEAD` through `ARCHIVED` and exceptional `BLOCKED`, `FAILED`, `CANCELLED`, `RIGHTS_REVOKED`. Every transition persists actor, guard result, reason, correlation ID, and prior resumable state. Outbox records are inserted in the same transaction as domain state. Celery queues are `analysis`, `translation`, `dubbing`, `audio`, `render`, `shorts`, `publishing`, `analytics`, and `notifications`.

- [ ] **Step 4: Run migration and focused tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/jobs tests/integration/jobs -q`  
Expected: pass.

### Task 4: Keycloak authentication, RBAC, and creator scope

**Files:**
- Create: `src/oki/identity/enums.py`
- Create: `src/oki/identity/models.py`
- Create: `src/oki/identity/schemas.py`
- Create: `src/oki/identity/keycloak.py`
- Create: `src/oki/identity/authorization.py`
- Create: `src/oki/identity/dependencies.py`
- Create: `src/oki/identity/router.py`
- Create: `migrations/versions/0003_identity_permissions.py`
- Create: `deploy/keycloak/oki-realm.json`
- Create: `tests/unit/identity/test_authorization.py`
- Create: `tests/integration/identity/test_oidc.py`

**Interfaces:**
- Produces: `Principal`, `Action`, `ResourceScope`, `TokenVerifier.verify(token) -> Principal`, `Authorizer.require(principal, action, resource) -> None`, FastAPI dependencies `current_principal` and `require_action(Action)`.
- Consumes: `users`, organizations, memberships, roles, permissions, and application settings.

- [ ] **Step 1: Write authorization tests**

```python
def test_creator_cannot_read_another_creator_project(authorizer, creator_principal, foreign_project) -> None:
    with pytest.raises(ForbiddenProblem) as error:
        authorizer.require(creator_principal, Action.PROJECT_READ, foreign_project)
    assert error.value.code == "resource_scope_denied"


def test_publisher_cannot_approve_agreement(authorizer, publisher, agreement) -> None:
    with pytest.raises(ForbiddenProblem):
        authorizer.require(publisher, Action.AGREEMENT_APPROVE, agreement)
```

- [ ] **Step 2: Run identity tests**

Run: `uv run pytest tests/unit/identity tests/integration/identity -q`  
Expected: fail on missing principal and verifier.

- [ ] **Step 3: Implement OIDC verification and action permissions**

Validate issuer, audience, signature, expiry, not-before, authorized-party, and token type against cached Keycloak JWKS with bounded refresh. Map subject to local organization memberships. Configure the exported Oki realm for employee and creator accounts, required employee TOTP MFA, password recovery, verified email, bounded sessions, refresh-token rotation, brute-force protection, and administrative session revocation. Seed distinct permissions for legal approval, voice-consent recording, sponsor replacement, creator review, private upload, public release, unpublish, payout approval, dead-letter replay, and audit read.

- [ ] **Step 4: Run identity tests and application smoke**

Run: `uv run pytest tests/unit/identity tests/integration/identity -q`  
Expected: pass.  
Run: `docker compose config --quiet`  
Expected: exit 0.

## Stage 0 Acceptance

Run: `uv run pytest tests/unit tests/integration/test_database.py tests/integration/test_health_dependencies.py tests/integration/jobs tests/integration/identity -q`  
Expected: pass with PostgreSQL 18/Redis/Keycloak test dependencies. `/health` is public, `/ready` reports dependencies, protected endpoints reject invalid tokens, idempotency returns one result, and invalid workflow shortcuts are impossible.
