# Oki Backend Stage 1 Rights and Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Onboard creators, version legal rights, fail closed through a reusable Rights Gate, and ingest immutable validated master media through resumable S3 uploads.

**Architecture:** Creator, agreement, grant, consent, rights evaluation, asset, and upload records live in PostgreSQL. tusd transfers resumable bytes into S3/SeaweedFS; Oki authenticates hooks and alone validates and registers immutable versions. Every processing command calls the same rights evaluator before dispatch or billing.

**Tech Stack:** Stage 0 stack plus tusd, boto3, HTTPX, ffprobe/FFmpeg, ClamAV, python-magic, and authenticated tus HTTP hooks.

**Spec:** `docs/superpowers/specs/2026-08-14-oki-localization-backend-design.md`

## Global Constraints

- Rights Gate decisions are persisted with exact agreement version and reason codes.
- Rights are checked at command, enqueue, worker start, render, private upload, and public release boundaries.
- Rights denial occurs before any billable provider call.
- Agreement and source versions are immutable.
- Creator accounts never cross creator/project scope.
- Every mutation emits an append-only audit event through the transactional outbox.

---

### Task 1: Creator, channel ownership, agreements, grants, and consent

**Files:**
- Create: `src/oki/creators/models.py`
- Create: `src/oki/creators/schemas.py`
- Create: `src/oki/creators/service.py`
- Create: `src/oki/creators/router.py`
- Create: `src/oki/rights/enums.py`
- Create: `src/oki/rights/models.py`
- Create: `src/oki/rights/schemas.py`
- Create: `src/oki/rights/service.py`
- Create: `src/oki/rights/router.py`
- Create: `migrations/versions/0004_creators_rights.py`
- Create: `tests/unit/rights/test_agreement_versions.py`
- Create: `tests/integration/rights/test_agreement_api.py`

**Interfaces:**
- Consumes: `UnitOfWork`, `Principal`, `Authorizer`, `OutboxPublisher`.
- Produces: `CreatorService.create`, `AgreementService.create_version`, `approve`, `revoke`, `record_voice_consent`; SOW creator/agreement endpoints.
- Produces tables: `creators`, `creator_channels`, `channel_ownership_evidence`, `creator_brand_guides`, `creator_restrictions`, `rights_agreements`, `rights_agreement_versions`, `rights_grants`, `voice_consents`, `endorsement_consents`, `agreement_decisions`.

- [ ] **Step 1: Write immutable-version and permission tests**

```python
async def test_approved_agreement_version_cannot_be_edited(agreement_service, approved_version) -> None:
    with pytest.raises(ConflictProblem) as error:
        await agreement_service.update_version(approved_version.id, {"permitted_languages": ["es"]})
    assert error.value.code == "agreement_version_immutable"


async def test_publisher_cannot_approve_agreement(client, publisher_headers, pending_agreement) -> None:
    response = await client.post(f"/api/agreements/{pending_agreement.id}/approve", headers=publisher_headers)
    assert response.status_code == 403
```

- [ ] **Step 2: Run focused rights model/API tests**

Run: `uv run pytest tests/unit/rights/test_agreement_versions.py tests/integration/rights/test_agreement_api.py -q`  
Expected: fail on missing models/routes.

- [ ] **Step 3: Implement versioned rights management**

Store the complete SOW grant dimensions: asset/category, languages, territories, platforms, full/Shorts format, translation, dubbing, edit, metadata, likeness/brand, sponsor removal/replacement mode, endorsement, voice cloning, creator-approval policy, dates, termination, monetization, revenue share, and payout terms. Approval and revocation create decisions rather than mutating history.

- [ ] **Step 4: Apply migration and run tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/rights/test_agreement_versions.py tests/integration/rights/test_agreement_api.py -q`  
Expected: pass.

### Task 2: Central Rights Gate and revocation propagation

**Files:**
- Create: `src/oki/rights/gate.py`
- Create: `src/oki/rights/policy.py`
- Create: `src/oki/rights/revocation.py`
- Create: `tests/unit/rights/test_gate.py`
- Create: `tests/integration/rights/test_revocation.py`

**Interfaces:**
- Produces: `RightsRequest`, `RightsDecision`, `RightsDenialCode`, `RightsGate.evaluate(request, now) -> RightsDecision`, `RightsGate.require(request, now) -> ApprovedRights`, `RevocationService.propagate(agreement_version_id) -> int`.
- Consumes: agreement/grant/consent repositories, localization job state machine, outbox, audit.

- [ ] **Step 1: Write the complete fail-closed matrix**

```python
@pytest.mark.parametrize("case,code", [
    ("no_agreement", "agreement_missing"),
    ("pending", "agreement_not_approved"),
    ("expired", "agreement_expired"),
    ("revoked", "agreement_revoked"),
    ("language", "language_not_permitted"),
    ("platform", "platform_not_permitted"),
    ("shorts", "shorts_not_permitted"),
    ("sponsor", "sponsor_replacement_not_permitted"),
    ("clone", "voice_clone_consent_missing"),
    ("endorsement", "endorsement_not_permitted"),
    ("creator_approval", "creator_approval_missing"),
    ("channel", "channel_not_authorized"),
])
def test_rights_gate_denies(case, code, rights_case_factory, rights_gate) -> None:
    decision = rights_gate.evaluate(rights_case_factory(case))
    assert decision.approved is False
    assert decision.reason_code == code
```

- [ ] **Step 2: Run gate tests**

Run: `uv run pytest tests/unit/rights/test_gate.py tests/integration/rights/test_revocation.py -q`  
Expected: fail on missing evaluator.

- [ ] **Step 3: Implement one pure policy evaluator plus persisted decision service**

The pure evaluator checks every dimension without I/O. The service loads current immutable versions, invokes the policy, persists `rights_evaluations`, audits denial/approval, and exposes an approved token containing agreement-version ID and evaluation ID. Revocation sets active jobs to `RIGHTS_REVOKED`, requests cooperative cancellation, and invalidates publication readiness.

- [ ] **Step 4: Verify gate and revocation behavior**

Run: `uv run pytest tests/unit/rights/test_gate.py tests/integration/rights/test_revocation.py -q`  
Expected: pass, including assertion that denied work creates zero provider-usage rows.

### Task 3: tusd resumable uploads, immutable assets, and checksum deduplication

**Files:**
- Create: `src/oki/storage/protocol.py`
- Create: `src/oki/storage/s3.py`
- Create: `src/oki/assets/tus_hooks.py`
- Create: `src/oki/assets/enums.py`
- Create: `src/oki/assets/models.py`
- Create: `src/oki/assets/schemas.py`
- Create: `src/oki/assets/service.py`
- Create: `src/oki/assets/router.py`
- Create: `migrations/versions/0005_assets_uploads.py`
- Create: `tests/unit/assets/test_storage_keys.py`
- Create: `tests/integration/assets/test_resumable_upload.py`
- Create: `tests/integration/assets/test_deduplication.py`

**Interfaces:**
- Produces: `ObjectStore` protocol; `S3ObjectStore`; `AssetService.create_upload`, `ingest_tus_hook`, `finalize_upload`, `register_stem`; authenticated tus hook and SOW upload status/completion endpoints.
- Produces tables: `source_assets`, `asset_versions`, `asset_uploads`, `upload_events`, `asset_stems`, `media_artifacts`.
- Consumes: approved rights evaluation, organization/creator scope, tus hook authentication, object-store metadata, and settings.

- [ ] **Step 1: Write interrupted upload, immutable key, and duplicate tests**

```python
async def test_replayed_out_of_order_tus_hooks_preserve_monotonic_offset(asset_client, upload) -> None:
    await asset_client.ingest_hook(upload.id, event_id="event-2", offset=20)
    await asset_client.ingest_hook(upload.id, event_id="event-1", offset=10)
    await asset_client.ingest_hook(upload.id, event_id="event-2", offset=20)
    status = await asset_client.get_upload(upload.id)
    assert status.offset == 20
    assert status.event_count == 2


async def test_duplicate_checksum_returns_existing_asset(asset_service, completed_asset) -> None:
    result = await asset_service.finalize_upload(completed_asset.upload_id, completed_asset.sha256)
    assert result.asset_id == completed_asset.asset_id
    assert result.duplicate is True
```

- [ ] **Step 2: Run upload tests against tusd and SeaweedFS S3**

Run: `uv run pytest tests/unit/assets tests/integration/assets/test_resumable_upload.py tests/integration/assets/test_deduplication.py -q`  
Expected: fail on missing object-store and asset service.

- [ ] **Step 3: Integrate tus lifecycle and write-once source policy**

Upload creation validates creator/agreement linkage and returns a tus endpoint plus scoped upload token/metadata. The blocking `pre-create` hook revalidates authorization and chooses a collision-resistant creator/version upload identity. Hook ingestion is authenticated, replay-safe, tenant-bound, and order-independent; it upserts by tus upload/event ID and never decreases the recorded offset. `post-finish` schedules finalization, which verifies S3 object size/SHA-256, ClamAV and media validation, and creator-scoped checksum uniqueness before immutable registration. Keys follow `/creators/{creator_id}/sources/{asset_id}/{version}/`. A replacement creates a new version/key; no source overwrite method exists.

- [ ] **Step 4: Run asset tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/assets tests/integration/assets -q`  
Expected: pass.

### Task 4: Malware scan, ffprobe validation, derivatives, and ingestion workflow

**Files:**
- Create: `src/oki/media/command.py`
- Create: `src/oki/media/ffprobe.py`
- Create: `src/oki/media/ffmpeg.py`
- Create: `src/oki/media/clamav.py`
- Create: `src/oki/assets/validation.py`
- Create: `src/oki/assets/tasks.py`
- Create: `migrations/versions/0006_asset_validation.py`
- Create: `tests/fixtures/media/generate.py`
- Create: `tests/unit/media/test_probe_validation.py`
- Create: `tests/integration/assets/test_ingestion_pipeline.py`

**Interfaces:**
- Produces: `CommandRunner`, `MediaProbe`, `MediaValidationResult`, `AssetValidationService.validate(asset_version_id)`, Hatchet task `validate_source_asset`.
- Produces tables: `media_streams`, `asset_validation_results`.
- Consumes: `ObjectStore`, ClamAV socket, ffprobe/FFmpeg binaries, Rights Gate, workflow transitions.

- [ ] **Step 1: Generate deterministic fixtures and write validation tests**

```python
@pytest.mark.parametrize("fixture,code", [
    ("corrupt.mp4", "media_unreadable"),
    ("video_only.mp4", "audio_stream_missing"),
    ("unsupported.mkv", "codec_not_supported"),
])
async def test_invalid_media_is_rejected(fixture, code, validation_service, media_fixture) -> None:
    result = await validation_service.validate(media_fixture(fixture))
    assert result.accepted is False
    assert code in result.error_codes
```

- [ ] **Step 2: Run media validation tests**

Run: `uv run pytest tests/unit/media/test_probe_validation.py tests/integration/assets/test_ingestion_pipeline.py -q`  
Expected: fail on missing probe/validation pipeline.

- [ ] **Step 3: Implement scan, validation, proxy, thumbnail, and audio extraction**

The task downloads to an isolated work directory, scans before opening, probes streams/duration, validates allowlisted containers/codecs and required audio, calculates local SHA-256, uploads proxy/thumbnail/original-audio artifacts, persists command/version/checksums, rechecks rights, and transitions `SOURCE_UPLOADED` to `SOURCE_VALIDATED` or `BLOCKED` with actionable codes. Unsupported/corrupt input never reaches analysis.

- [ ] **Step 4: Run Stage 1 tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/rights tests/unit/assets tests/unit/media tests/integration/rights tests/integration/assets -q`  
Expected: pass.

## Stage 1 Acceptance

Use the API to create a creator, record channel ownership, submit and legally approve an agreement version, create/resume/complete a master upload, validate media, and receive `SOURCE_VALIDATED`. Repeat with no agreement, expired/revoked agreement, unauthorized language/platform, missing audio, corrupt media, and duplicate checksum; all must return the specified denial without provider usage or source overwrite.
