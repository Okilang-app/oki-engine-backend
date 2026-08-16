# Backend MVP Implementation Contract

## Context
- Work in `.worktrees/backend-implementation/`
- Existing code: Stage 0 (foundation) + Stage 1 partial (creators, rights)
- Missing: assets, storage, media, analysis, translation, voice, dubbing, audio, campaigns, renders, reviews, youtube, publications, shorts, analytics, finance

## Patterns (MUST follow)
1. **Models**: SQLAlchemy 2 async in `src/oki/{module}/models.py`
   - Use `from oki.db.base import Base`
   - Use mixins: `TimestampMixin`, `VersionMixin`, `CreatedAtMixin` from `oki.db.mixins`
   - UUID PKs with `Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)`
   - Enum columns use custom `Enum(..., name=..., values_callable=_enum_values)` for PostgreSQL
   - JSONB: `mapped_column(JSONB, nullable=False)` for dict/list fields
   - Foreign keys reference existing tables exactly

2. **Schemas**: Pydantic v2 in `src/oki/{module}/schemas.py`
   - Use `BaseModel` with `model_config = ConfigDict(from_attributes=True)` for ORM reads
   - Response schemas end with `Response` (e.g., `AssetResponse`)
   - Create schemas end with `Create` (e.g., `AssetCreate`)
   - Use `UUID` from standard library

3. **Services**: Dataclass or plain class in `src/oki/{module}/service.py`
   - Constructor: `(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer)`
   - Use `async with self._uow_factory() as uow:` for transactions
   - Raise `ProblemException` subclasses from `oki.api.errors`
   - Call `self._authorizer.require(principal, Action.SOME_ACTION, resource)` for auth

4. **Routers**: FastAPI `APIRouter(prefix="/api")` in `src/oki/{module}/router.py`
   - Get service from `request.app.state.{module}_service`
   - Use `current_principal` dependency from `oki.identity.dependencies`
   - Return response models directly
   - Tags should match module name

5. **Enums**: StrEnum in `src/oki/{module}/enums.py`

6. **Migrations**: Alembic in `migrations/versions/####_description.py`
   - Pre-assigned numbers; do not collide

## Pre-assigned Migration Numbers
- Track A: `0005_assets_uploads.py`, `0006_asset_validation.py`
- Track B: `0007_analysis_timeline.py`, `0008_sponsor_review.py`, `0009_translation_workspace.py`
- Track C: `0010_voice_profiles.py`, `0011_dubbing.py`, `0012_audio_mix.py`, `0013_campaigns_creatives.py`, `0014_renders.py`
- Track D: `0015_reviews.py`, `0016_youtube_connections.py`, `0017_publications.py`, `0018_shorts.py`, `0019_analytics_events.py`, `0020_finance.py`

## Existing Tables (do not modify)
- `users`, `organizations`, `memberships`, `roles`, `permissions`, `role_permissions`
- `projects`, `localization_jobs`, `workflow_transitions`, `task_runs`, `task_checkpoints`, `dead_letters`, `outbox_events`, `provider_usage`, `idempotency_records`
- `creators`, `creator_channels`, `channel_ownership_evidence`, `creator_brand_guides`, `creator_restrictions`, `rights_agreements`, `rights_agreement_versions`, `rights_grants`, `voice_consents`, `endorsement_consents`, `agreement_decisions`, `rights_evaluations`, `audit_events`

## Workflow States (used in jobs)
`CREATOR_LEAD → RIGHTS_PENDING → RIGHTS_APPROVED → SOURCE_REQUESTED → SOURCE_UPLOADED → SOURCE_VALIDATED → ANALYSIS_RUNNING → AD_REVIEW_REQUIRED → TRANSLATION_RUNNING → TRANSLATION_REVIEW → DUBBING_RUNNING → AUDIO_REVIEW → RENDER_RUNNING → INTERNAL_QA → CREATOR_REVIEW → PUBLISH_READY → UPLOADED_PRIVATE → PLATFORM_CHECK → PUBLISHED → PERFORMANCE_REVIEW → ARCHIVED`
Plus: `BLOCKED`, `FAILED`, `CANCELLED`, `RIGHTS_REVOKED`

## Key Files to Reference
- `src/oki/rights/models.py` for model pattern
- `src/oki/rights/schemas.py` for schema pattern  
- `src/oki/rights/service.py` for service pattern
- `src/oki/rights/router.py` for router pattern
- `src/oki/jobs/enums.py` for enum pattern
- `src/oki/db/mixins.py` for available mixins
- `src/oki/api/errors.py` for error types
- `src/oki/config.py` for Settings

## S3/Storage Config
- Endpoint: `settings.s3_endpoint_url` (SeaweedFS local)
- Bucket: `settings.s3_bucket`
- Use `boto3` with custom endpoint for S3-compatible operations

## Target MVP Endpoints (from SOW)
Must exist by end of backend MVP:
- `POST /api/creators` ✅
- `GET /api/creators/{creator_id}` ✅
- `POST /api/creators/{creator_id}/agreements` ✅
- `POST /api/agreements/{agreement_id}/approve` ✅
- `POST /api/agreements/{agreement_id}/revoke` ✅
- `POST /api/assets/upload-url` ⬜ Track A
- `POST /api/assets/complete-upload` ⬜ Track A
- `POST /api/assets/{asset_id}/validate-rights` ⬜ Track A
- `POST /api/jobs/analyze` ⬜ Track B
- `POST /api/jobs/translate` ⬜ Track B
- `POST /api/jobs/dub` ⬜ Track C
- `POST /api/jobs/mix` ⬜ Track C
- `POST /api/jobs/render` ⬜ Track C
- `POST /api/jobs/generate-shorts` ⬜ Track D
- `POST /api/jobs/cancel` ⬜ Track D
- `GET /api/reviews/{job_id}` ⬜ Track D
- `POST /api/reviews/{job_id}/approve` ⬜ Track D
- `POST /api/reviews/{job_id}/reject` ⬜ Track D
- `POST /api/youtube/connect` ⬜ Track D
- `POST /api/publications` ⬜ Track D
- `POST /api/publications/{publication_id}/upload-private` ⬜ Track D
- `POST /api/publications/{publication_id}/publish` ⬜ Track D
- `POST /api/publications/{publication_id}/unpublish` ⬜ Track D
- `GET /api/analytics/creators` ⬜ Track D
- `GET /api/analytics/videos` ⬜ Track D
- `GET /api/analytics/languages` ⬜ Track D
- `GET /api/analytics/campaigns` ⬜ Track D
- `GET /api/analytics/oki-conversions` ⬜ Track D
