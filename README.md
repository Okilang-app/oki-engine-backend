# Oki Creator Localization Engine — Backend

FastAPI backend for licensed YouTube creator content localization, translation, dubbing, and distribution.

## Stack

- **Python** 3.12+
- **FastAPI** with SQLAlchemy 2 async ORM
- **PostgreSQL** 18 (via Docker)
- **Valkey** (Redis-compatible cache)
- **SeaweedFS** (S3-compatible object storage)
- **Keycloak** (OAuth2 / OIDC authentication)
- **Alembic** (database migrations)
- **Hatchet** (workflow orchestration)
- **ClamAV** (file scanning)

## Quick Start

### 1. Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Docker Desktop

### 2. Start backing services

```bash
# Copy environment config
cp .env.example .env

# Start PostgreSQL, Valkey, SeaweedFS, Keycloak, ClamAV
docker compose up -d
```

> On Windows, default ports may conflict. The `.env` in this repo remaps to:
> - PostgreSQL → `55432`
> - Valkey → `56379`
> - SeaweedFS S3 → `58333`
> - Keycloak → `58080`
> - ClamAV → `53310`

### 3. Install dependencies

```bash
uv sync
```

### 4. Run migrations

```bash
uv run alembic upgrade head
```

### 5. Start the server

```bash
uv run uvicorn oki.main:create_app --host 0.0.0.0 --port 8000 --reload
```

> If port 8000 is occupied by a stale process, use `--port 8001` and update `NEXT_PUBLIC_API_URL` in the frontend `.env.local`.

Verify: `curl http://127.0.0.1:8000/health` should return `{"status":"ok"}`.

### 6. API docs

- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

## Development

### Run tests

```bash
# All tests
uv run pytest tests/unit -q --tb=short

# With coverage
uv run pytest tests/unit --cov=oki --cov-report=term-missing

# Specific module
uv run pytest tests/unit/creators -q
```

### Create a migration

```bash
uv run alembic revision --autogenerate -m "description_of_change"
```

### Lint / format

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

### Type check

```bash
uv run mypy src/oki
```

## Project Structure

```
.
├── src/oki/
│   ├── main.py              # FastAPI app factory + router wiring
│   ├── config.py            # Pydantic-settings config
│   ├── db/                  # AsyncSession, UoW, connection utils
│   ├── api/                 # Shared dependencies, error handlers
│   ├── identity/            # Users, orgs, Keycloak integration
│   ├── creators/            # Creator profiles, membership
│   ├── rights/              # Rights-clearing gate
│   ├── assets/              # Source asset uploads, validation, storage
│   ├── analysis/            # Transcription, timeline segmentation
│   ├── sponsors/            # Sponsor/ad detection
│   ├── translations/        # Text translation, QA gate
│   ├── voices/              # Voice catalog, cloning
│   ├── dubbing/             # TTS dubbing pipeline
│   ├── campaigns/           # Localization campaigns
│   ├── renders/             # Video/audio rendering
│   ├── reviews/             # Review & approval workflows
│   ├── youtube/             # YouTube metadata, API
│   ├── publications/        # Publishing guards,shorts
│   ├── shorts/              # Shorts generation
│   ├── analytics/           # Attribution, conversion events
│   └── finance/             # Invoicing, royalty calculations
├── migrations/versions/     # Alembic migrations (0001–0020)
├── tests/unit/              # Unit tests mirroring src/oki/
├── compose.yaml             # Docker services
└── pyproject.toml           # uv project manifest
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OKI_ENVIRONMENT` | `local` | `local`, `staging`, `production` |
| `OKI_DATABASE_URL` | — | PostgreSQL async URL |
| `OKI_VALKEY_URL` | — | Valkey / Redis URL |
| `OKI_S3_ENDPOINT_URL` | — | SeaweedFS / S3 endpoint |
| `OKI_S3_ACCESS_KEY` | — | S3 access key |
| `OKI_S3_SECRET_KEY` | — | S3 secret key |
| `OKI_S3_BUCKET` | `oki-local` | S3 bucket name |
| `OKI_KEYCLOAK_ISSUER` | — | Keycloak realm URL |
| `OKI_KEYCLOAK_AUDIENCE` | `oki-api` | JWT audience |
| `OKI_KEYCLOAK_JWKS_URI` | — | JWKS certificate endpoint |
| `OKI_LOG_LEVEL` | `INFO` | Structlog level |

See `.env.example` for the full list.

## Authentication

The backend verifies JWT bearer tokens issued by Keycloak. The issuer, audience, and JWKS URI are configured via environment variables. No session cookies — purely stateless token validation.

## AI / Media Integrations (Stubbed for MVP)

The following integrations are modeled in the database and API but use stub implementations:

- **OpenAI Whisper** — audio transcription
- **Azure Translator** — text translation
- **ElevenLabs TTS** — text-to-speech / voice cloning
- **FFmpeg** — video/audio rendering pipeline

Replace the stub providers in the respective service modules when API keys are available.
