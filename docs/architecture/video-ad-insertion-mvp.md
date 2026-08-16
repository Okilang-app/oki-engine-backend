# Video Ad Insertion MVP — Execution Plan

## Goal (2–3 week deliverable)

Authorized creator master → rights gate → resumable upload → media validation → choose ad cut window → insert approved Oki creative → FFmpeg render → validated ad-integrated master.

Out of MVP scope: translation/dubbing/Shorts/publication/analytics/translation-memory/neural-TTS/exploration. These stay in the backlog and are not printed now.

## Sequence (no skipped dependencies)

### Stage 1: Rights and Intake (1 week)

Sequential. Each task gates the next.

**Task 1: Creator, channel ownership, agreements, grants, consent — IN PROGRESS**
- Scope: `src/oki/creators/*`, `src/oki/rights/enums.py schemas.py models.py service.py router.py`, `migrations/versions/0004_creators_rights.py`, `RightsEvaluation` pre-provisioned, tests.
- Precondition: Stage 0 Task 4 identity reviewed and fix round applied.
- Consuming: Principal, Authorizer, UnitOfWork, OutboxPublisher.

**Task 2: Rights Gate and revocation**
- Scope: `src/oki/rights/gate.py policy.py revocation.py`, tests, Stage 0 `GuardEvaluator` boundary adapter.
- Precondition: Task 1 immutable agreement tables exist.
- Consuming: agreement/grant/consent repositories, state machine, outbox.

**Task 3: tusd resumable upload and immutable asset registration**
- Scope: ObjectStore/S3 protocol, tusd hooks, asset models/routes, 0005, ClamAV scan stub, tests.
- Precondition: Task 2 RightsGate.require callable for upload creation, pre-create, and finalization.
- No YouTube scraping. Creator master bytes only.

**Task 4: Media validation (ffprobe) and SOURCE_VALIDATED**
- Scope: `src/oki/media/command.py ffprobe.py ffmpeg.py`, validation service, Hatchet `validate_source_asset` task, 0006.
- Postcondition: `SOURCE_VALIDATED` with proxy/thumbnail/audio derivatives, immutable source key.

### Stage 2: Analysis and Ad Review (3–4 days)

**Task 2 (partial): Sponsor candidate detection and mandatory human review**
- Scope: `src/oki/sponsors/models.py detection.py service.py router.py`, `migrations/versions/0008_sponsor_review.py`, tests.
- No full timeline merge or OTIO export for MVP. Only sponsor candidate extraction from transcript + OCR + branding evidence.
- Human content analyst approves/rejects each candidate boundary.
- Approval does NOT bypass agreement replacement rights.

**Task 3: Sponsor review gate (human workflow)**
- Scope: Review task assignment, human approve/reject with persisted decision, audit trail.
- Consuming: sponsor candidates, state machine, transition to AD_REVIEW_REQUIRED.

### Stage 3: Campaign, Creative, and Render (3–4 days)

**Task 4: Campaign creative library and replacement plan**
- Scope: `src/oki/campaigns/*`, `src/oki/sponsors/replacement.py`, 0013.
- Four-gate approval: agreement allows replacement + human-approved ad segment boundary + eligible creative version + separately permissioned replacement plan approval.
- Store replacement boundaries, old promo-code removal, disclosure, media edits.

**Task 5 (partial): FFmpeg render manifest and ad-insertion executor**
- Scope: `src/oki/renders/manifest.py ffmpeg_plan.py qa.py service.py tasks.py`, 0014.
- No dubbing/audio mixing for MVP. Only FFmpeg command generation from:
  - Immutable source proxy
  - Approved creative with exact start/duration
  - Approved replacement boundaries (cut old ad, insert new creative)
  - Required output: ad-integrated MP4, media manifest, checksum, QA report.
- Idempotent render: same inputs produce same render_id without duplicate computation.

## API contracts for MVP

- `POST /api/creators` — onboard creator
- `POST /api/creators/{id}/agreements` — submit agreement version
- `POST /api/agreements/{id}/approve` — legal approval (employee only)
- `POST /api/uploads` — start resumable upload with rights evaluation
- `POST /api/assets/{id}/finalize` — validate and register immutable source
- `GET /api/sponsors/candidates?asset_id=...` — list detected candidates
- `POST /api/sponsors/candidates/{id}/approve` — human approve boundary
- `GET /api/campaigns/creatives` — list eligible creatives for context
- `POST /api/renders` — submit render manifest, get render_id
- `GET /api/renders/{id}` — get status, output package

## Workstream assignment

- **Track A** (rights + intake): Stage 1 Tasks 1–4. The team already owns this in progress.
- **Track B** (analysis + ad review): Stage 2 Tasks 2–3. Starts when Track A reaches SOURCE_VALIDATED.
- **Track C** (creative + render): Stage 3 Tasks 4–5. Starts when Track B produces approved ad boundaries.
- **Track D** (identity hardening): Stage 0 Task 4 fix round. Runs parallel, no consumer dependency.

## Database migration renumbering

The full plan uses 0004–0021 for all SOW stages. MVP uses only:
- `0004_creators_rights.py` — already in progress
- `0005_assets_uploads.py`
- `0006_asset_validation.py`
- `0007_analysis_timeline.py` — minimal sponsor timeline only
- `0008_sponsor_review.py`
- `0013_campaigns_creatives.py` — renumbered from 0013 to `0010_campaigns_creatives.py` because MVP skips dubbing/audio/shorts
- `0014_renders.py` — renumbered to `0011_renders.py`

Renumbering is acceptable because no production migration history exists yet. All migrations must run sequentially from 0001 head with no gaps.

## External dependencies

- Keycloak 26.3 (identity — provided by Stage 0)
- PostgreSQL 18 (database — provided by Stage 0)
- Hatchet 1.37.2 (workflow — provided by Stage 0)
- SeaweedFS/S3 (object storage — provided by Stage 0)
- Valkey (cache — provided by Stage 0)
- ClamAV (scan — provided by Stage 0)
- FFmpeg in worker image (validate/render — must add to worker.Dockerfile)
- tusd (resumable upload — add as sidecar in Compose)

## Rollback and risk

- No dubbing means no neural-TTS/translation cost risk.
- No Shorts means no vertical-crop complexity.
- The biggest risk is FFmpeg render reliability; mitigated by deterministic manifests, content-addressed inputs, reproducible commands, and out-of-band QA.
- If sponsor detection accuracy is poor, the human review step covers the gap.

## Exit criteria

- Creator can onboard, submit agreement, get legal approval.
- Creator can upload source master through resumable endpoint.
- System validates source media and produces proxy/thumbnail.
- Content analyst can detect and approve ad cut boundaries.
- Campaign manager can choose eligible creative and approve replacement plan.
- System renders ad-integrated localized master with deterministic checksum.
- Full audit trail exists for every mutation.
