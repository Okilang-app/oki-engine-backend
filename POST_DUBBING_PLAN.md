# Post-Dubbing Implementation Plan (Stages 4–6)

> **Starting point**: Dubbing pipeline (Stage 3) is complete. All DB models, migrations, and
> scaffolded services exist. The remaining work is implementing the logic that's currently
> stubbed with `NotImplementedError` or missing entirely.

---

## Table of Contents

1. [Current State Summary](#1-current-state-summary)
2. [Stage 4 — Creator Portal & Publishing](#2-stage-4--creator-portal--publishing)
   - [4A: Review Package — Missing Endpoints](#4a-review-package--missing-endpoints)
   - [4B: YouTube OAuth — Real Token Exchange](#4b-youtube-oauth--real-token-exchange)
   - [4C: YouTube Client — Upload & Publish](#4c-youtube-client--upload--publish)
   - [4D: Publication Tasks — Wire to YouTube](#4d-publication-tasks--wire-to-youtube)
   - [4E: Platform Checks — Disclosure & Metadata Validators](#4e-platform-checks--disclosure--metadata-validators)
   - [4F: Campaign & Creative CRUD](#4f-campaign--creative-crud)
   - [4G: Audio Mixing Endpoints](#4g-audio-mixing-endpoints)
3. [Stage 5 — Shorts & Analytics](#3-stage-5--shorts--analytics)
   - [5A: Shorts Candidate Detection](#5a-shorts-candidate-detection)
   - [5B: Shorts — Missing CRUD & Publish Endpoints](#5b-shorts--missing-crud--publish-endpoints)
   - [5C: Shorts — Vertical Crop & Subtitle Generation](#5c-shorts--vertical-crop--subtitle-generation)
   - [5D: YouTube Analytics Ingestion](#5d-youtube-analytics-ingestion)
   - [5E: Oki Conversion Event Pipeline](#5e-oki-conversion-event-pipeline)
   - [5F: Reports — Daily & Weekly](#5f-reports--daily--weekly)
   - [5G: Analytics CSV Export](#5g-analytics-csv-export)
   - [5H: Finance — Revenue Share from Agreement & Export File](#5h-finance--revenue-share-from-agreement--export-file)
4. [Stage 6 — Production Hardening](#4-stage-6--production-hardening)
   - [6A: Notifications System](#6a-notifications-system)
   - [6B: OpenTelemetry & Sentry](#6b-opentelemetry--sentry)
   - [6C: Automated Tests](#6c-automated-tests)
   - [6D: Security Hardening](#6d-security-hardening)
   - [6E: Cost Controls & Provider Limits](#6e-cost-controls--provider-limits)
   - [6F: Backup & Restore](#6f-backup--restore)
   - [6G: Deployment & Documentation](#6g-deployment--documentation)
5. [Execution Order & Dependencies](#5-execution-order--dependencies)
6. [Files Changed Summary](#6-files-changed-summary)

---

## 1. Current State Summary

### What is complete (no work needed)

| Module | Status |
|--------|--------|
| Identity / RBAC / Keycloak | Complete |
| Creator profiles & Rights agreements | Complete |
| Asset ingestion (upload, checksum, ClamAV) | Complete |
| Analysis (transcription, speaker diarization, scene detection) | Complete |
| Sponsor detection & human review | Complete |
| Translations & glossary | Complete |
| Dubbing (DubSegment, DubAttempt, ElevenLabs, consent) | Complete |
| Voices (profiles, policy, pronunciation) | Complete |
| Renders (FFmpeg pipeline, EDL, manifest, QA) | Complete |
| Workflow state machine (24 states, all guards) | Complete |
| DB models for reviews, publications, shorts, analytics, finance | Complete |
| Attribution resolution | Complete |
| Finance calculator (payout bps) | Complete |

### What is scaffolded but not implemented (the actual work)

| Module | Gap |
|--------|-----|
| `reviews/router.py` | Only 3 endpoints — missing create-package, comment, list-versions |
| `youtube/oauth.py` | Stub — returns fake tokens, fake channel info |
| `youtube/client.py` | All 3 methods raise `NotImplementedError` |
| `publications/tasks.py` | Stubs — don't call YouTube |
| `publications/checks.py` | Stub — raises `NotImplementedError` |
| `campaigns/router.py` | Read-only — no create/update/delete |
| `shorts/service.py` | Creates empty candidate, no scoring or clip detection |
| `shorts/scoring.py` | Returns all zeros |
| `shorts/crop.py` | Returns dummy crop params |
| `shorts/router.py` | Only 1 endpoint (generate) |
| `analytics/youtube.py` | Both methods raise `NotImplementedError` |
| `analytics/oki_events.py` | `record_conversion()` raises `NotImplementedError` |
| `analytics/reports.py` | Both builders return empty structures |
| `finance/service.py` | Uses hardcoded `share_bps=10000`; export creates record with `file_url=None` |
| Audio mixing | No router (mixing not exposed as API) |

---

## 2. Stage 4 — Creator Portal & Publishing

### Acceptance gate (SOW): An approved video can be uploaded privately and published to an authorized channel.

---

### 4A: Review Package — Missing Endpoints

**Files**: `src/oki/reviews/router.py`, `src/oki/reviews/schemas.py`

The service has `create_package()`, `comment()`, `decide()`, and `invalidate_for_change()` fully
implemented. The router only exposes `GET /reviews/{job_id}`, `POST /reviews/{job_id}/approve`,
and `POST /reviews/{job_id}/reject`. The following endpoints need to be added to the router.

#### Endpoints to add

| Method | Path | Service method | Auth action |
|--------|------|----------------|-------------|
| `POST` | `/api/reviews/{job_id}/create-package` | `create_package(job_id, principal, correlation_id)` | `CREATOR_REVIEW_SUBMIT` |
| `POST` | `/api/reviews/{package_id}/comment` | `comment(package_id, text, principal, correlation_id, line_reference?)` | `CREATOR_REVIEW_SUBMIT` |
| `GET` | `/api/reviews/{job_id}/versions` | query `ReviewPackageVersions` by package | `CREATOR_REVIEW_SUBMIT` |
| `POST` | `/api/reviews/{version_id}/invalidate` | `invalidate_for_change(version_id, principal, correlation_id)` | `CREATOR_REVIEW_SUBMIT` |
| `POST` | `/api/reviews/{job_id}/request-changes` | `reject_job()` with `decision=REQUEST_CHANGES` | `CREATOR_REVIEW_SUBMIT` |

#### Schemas to add in `src/oki/reviews/schemas.py`

```python
class CreateReviewPackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    job_id: UUID
    organization_id: UUID
    status: str
    correlation_id: UUID
    created_at: datetime

class CommentRequest(BaseModel):
    text: str
    line_reference: str | None = None

class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    package_version_id: UUID
    author_user_id: UUID
    text: str
    line_reference: str | None
    created_at: datetime

class PackageVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    package_id: UUID
    version_number: int
    canonical_hash: str
    material_changed: bool
    invalidated_at: datetime | None
    created_at: datetime
```

#### Implementation notes

- `POST /api/reviews/{job_id}/create-package`: check if a package already exists for the job;
  if it does, return it instead of creating a duplicate (idempotent).
- `GET /api/reviews/{job_id}/versions`: load the package for the job, then return all
  `ReviewPackageVersions` ordered by `version_number desc`.
- The `request-changes` endpoint is cosmetically separate from `reject` but maps to the same
  service call with `decision=REQUEST_CHANGES` (add this value to `ReviewDecisionType` enum if
  it doesn't exist; otherwise map it to `REJECTED` with a `reason`).

#### Creator-facing portal note

The SOW requires a "secure review link or login" for creators. This is a separate concern from
the internal review endpoints above. The simplest implementation:

1. Add a `POST /api/reviews/{job_id}/creator-link` endpoint that generates a signed JWT with
   `sub=creator_id`, `scope=review`, `jti=review_package_id`, `exp=7 days`.
2. Add a `GET /api/reviews/creator/{token}` endpoint that validates the JWT and returns the
   review package without requiring a Keycloak session.
3. The frontend (creator portal page) accepts the token from the URL, calls
   `/api/reviews/creator/{token}` to fetch the package, and posts decisions back via
   `POST /api/reviews/creator/{token}/decide`.

For the JWT signing: use `python-jose` (already likely available) or `cryptography`. Store the
signing key in `Settings` as `review_link_secret`. Never expose it in logs.

---

### 4B: YouTube OAuth — Real Token Exchange

**File**: `src/oki/youtube/oauth.py`

Both `start()` and `callback()` contain clear `TODO` comments. The structure (PKCE, DB models,
cipher) is all correct — only the Google API calls are missing.

#### `start()` — what to fix

Replace:
```python
f"&code_challenge={code_verifier}"
f"&code_challenge_method=plain"
```
With a proper PKCE implementation:
```python
import hashlib, base64, secrets

code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
code_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(code_verifier.encode()).digest()
).rstrip(b"=").decode()
```
Use `S256` as the method, not `plain`. Store `code_verifier` in the DB (already a column).

Also replace the hardcoded `CLIENT_ID` placeholder:
```python
from oki.config import Settings
settings = Settings()
# ...
f"&client_id={settings.youtube_client_id}"
```
Add `youtube_client_id: str = ""` and `youtube_client_secret: str = ""` to `Settings`.

#### `callback()` — what to fix

Replace the stub token exchange with a real HTTP call to Google's token endpoint:

```python
import httpx

async with httpx.AsyncClient() as http:
    resp = await http.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings.youtube_client_id,
            "client_secret": settings.youtube_client_secret,
            "redirect_uri": callback_url,
            "grant_type": "authorization_code",
            "code_verifier": connection.code_verifier,
        },
    )
    resp.raise_for_status()
    token_data = resp.json()

access_token = token_data["access_token"]
refresh_token = token_data.get("refresh_token", "")
expires_in = token_data.get("expires_in", 3600)
```

Then replace the stub channel fetch:
```python
async with httpx.AsyncClient() as http:
    resp = await http.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "snippet", "mine": "true"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])

if not items:
    raise ProblemException(
        status_code=400,
        code="no_youtube_channel",
        title="No YouTube channel found",
        detail="The authorized account has no YouTube channel.",
    )

channel_data = items[0]
platform_channel_id = channel_data["id"]
channel_title = channel_data["snippet"]["title"]
```

#### Token refresh helper

Add a `_refresh_token()` method to `YoutubeOAuthService`:

```python
async def get_valid_access_token(self, connection_id: UUID) -> str:
    """Return a valid access token, refreshing if necessary."""
    async with self._uow_factory() as uow:
        conn = await uow.session.get(OAuthConnection, connection_id)
        if conn is None:
            raise ProblemException(status_code=404, code="connection_not_found",
                                   title="OAuth connection not found",
                                   detail="Connection not found.")
        if conn.token_expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            return self._cipher.decrypt(conn.access_token_encrypted).decode()

        # Refresh
        refresh_token = self._cipher.decrypt(conn.refresh_token_encrypted).decode()
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.youtube_client_id,
                    "client_secret": settings.youtube_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            new_tokens = resp.json()

        conn.access_token_encrypted = self._cipher.encrypt(
            new_tokens["access_token"].encode()
        )
        conn.token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=new_tokens.get("expires_in", 3600)
        )
        uow.session.add(conn)
        return new_tokens["access_token"]
```

#### Settings additions

Add to `src/oki/config.py` (or wherever `Settings` is defined):
```python
youtube_client_id: str = ""
youtube_client_secret: str = ""
youtube_oauth_callback_url: str = "http://localhost:8000/api/youtube/callback"
review_link_secret: str = ""
```

---

### 4C: YouTube Client — Upload & Publish

**File**: `src/oki/youtube/client.py`

The client needs `YoutubeOAuthService` (or just the access token getter) injected. Restructure
it to accept either a token string or the OAuth service:

```python
class YoutubeClient:
    def __init__(self, oauth_service: YoutubeOAuthService) -> None:
        self._oauth = oauth_service
```

#### `upload_video()` — resumable upload

YouTube uses a two-step resumable upload:
1. POST to `https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable` with
   metadata JSON. Response header `Location` contains the upload URI.
2. PUT the video bytes to the upload URI (with `Content-Type: video/*`).

Full implementation:

```python
async def upload_video(
    self,
    connection_id: UUID,
    file_path: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    access_token = await self._oauth.get_valid_access_token(connection_id)
    file_size = os.path.getsize(file_path)

    # Step 1: initiate resumable upload
    async with httpx.AsyncClient() as http:
        init_resp = await http.post(
            "https://www.googleapis.com/upload/youtube/v3/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(file_size),
            },
            json=metadata,
        )
        init_resp.raise_for_status()
        upload_url = init_resp.headers["Location"]

    # Step 2: upload file bytes
    async with httpx.AsyncClient(timeout=600.0) as http:
        with open(file_path, "rb") as f:
            upload_resp = await http.put(
                upload_url,
                content=f.read(),
                headers={"Content-Type": "video/mp4"},
            )
        upload_resp.raise_for_status()

    return upload_resp.json()
```

**Important**: For large files, implement chunked upload (8 MB chunks) instead of reading the
whole file into memory. The YouTube resumable upload API supports `Content-Range` headers.

#### `publish_video()` — make public

```python
async def publish_video(
    self,
    connection_id: UUID,
    video_id: str,
) -> dict[str, Any]:
    access_token = await self._oauth.get_valid_access_token(connection_id)
    async with httpx.AsyncClient() as http:
        resp = await http.put(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "status"},
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "id": video_id,
                "status": {"privacyStatus": "public"},
            },
        )
        resp.raise_for_status()
        return resp.json()
```

#### `update_metadata()` — title/description/tags

```python
async def update_metadata(
    self,
    connection_id: UUID,
    video_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    access_token = await self._oauth.get_valid_access_token(connection_id)
    async with httpx.AsyncClient() as http:
        resp = await http.put(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "snippet"},
            headers={"Authorization": f"Bearer {access_token}"},
            json={"id": video_id, "snippet": metadata},
        )
        resp.raise_for_status()
        return resp.json()
```

#### Additional methods needed

```python
async def upload_caption(
    self,
    connection_id: UUID,
    video_id: str,
    caption_path: str,
    language: str,
    name: str = "Localized subtitles",
) -> dict[str, Any]:
    """Upload SRT/VTT captions to an existing video."""
    # Uses the YouTube Captions API

async def poll_processing_status(
    self,
    connection_id: UUID,
    video_id: str,
) -> str:
    """Return 'processing', 'succeeded', 'failed', or 'terminated'."""
    # Uses videos.list?part=processingDetails
```

---

### 4D: Publication Tasks — Wire to YouTube

**File**: `src/oki/publications/tasks.py`

Both `upload_to_platform_task` and `publish_task` are stubs. They need to:
1. Load the publication and its associated job/render output/channel
2. Download the rendered video from S3 to a temp file
3. Call `YoutubeClient.upload_video()` / `publish_video()`
4. Update `publication.private_video_id` / `publication.video_id` in DB
5. Update `publication.status` via the service
6. On failure: log to `PublicationAttempts.error_message`, set `publication.status = FAILED`

#### `upload_to_platform_task()` — full logic

```python
async def upload_to_platform_task(
    publication_id: UUID,
    *,
    correlation_id: UUID | None = None,
) -> dict[str, Any]:
    async with uow_factory() as uow:
        publication = await uow.session.get(Publications, publication_id)
        if publication is None:
            return {"error": "publication_not_found"}

        # Load the render output to get the video file key
        from oki.renders.models import RenderOutput
        render_output = await uow.session.scalar(
            select(RenderOutput)
            .join(RenderJob, RenderJob.id == RenderOutput.render_job_id)
            .where(RenderJob.localization_job_id == publication.job_id)
            .order_by(RenderOutput.created_at.desc())
            .limit(1)
        )
        if render_output is None:
            publication.status = PublicationStatus.FAILED
            return {"error": "no_render_output"}

        # Load the authorized channel
        channel = await uow.session.get(AuthorizedChannel, publication.channel_id)
        if channel is None:
            publication.status = PublicationStatus.FAILED
            return {"error": "no_channel"}

        # Download video from S3 to temp file
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            await store.download_file(render_output.output_s3_key, tmp_path)

            # Build YouTube metadata
            job = await uow.session.get(LocalizationJob, publication.job_id)
            yt_metadata = {
                "snippet": {
                    "title": f"{job.title or 'Localized Video'} [{job.target_language}]",
                    "description": "Localized content. Original by [creator].",
                    "tags": [job.target_language],
                    "defaultLanguage": job.target_language,
                },
                "status": {
                    "privacyStatus": "private",  # always upload private first
                    "selfDeclaredMadeForKids": False,
                },
            }

            # Upload
            result = await youtube_client.upload_video(
                channel.connection_id,
                tmp_path,
                yt_metadata,
            )
            video_id = result["id"]

            publication.private_video_id = video_id
            publication.status = PublicationStatus.PRIVATE_UPLOADED

            # Record attempt
            attempt = PublicationAttempts(
                organization_id=publication.organization_id,
                publication_id=publication_id,
                attempt_number=1,
                action="upload_private",
                platform_response=result,
            )
            uow.session.add(attempt)

        except Exception as exc:
            publication.status = PublicationStatus.FAILED
            attempt = PublicationAttempts(
                organization_id=publication.organization_id,
                publication_id=publication_id,
                attempt_number=1,
                action="upload_private",
                error_message=str(exc),
            )
            uow.session.add(attempt)
            raise
        finally:
            os.unlink(tmp_path)

        return {"video_id": video_id, "status": "private_uploaded"}
```

#### `publish_task()` — make public after approval

```python
async def publish_task(publication_id: UUID) -> dict[str, Any]:
    async with uow_factory() as uow:
        publication = await uow.session.get(Publications, publication_id)

        # Verify approval exists (belt-and-suspenders — service already checks)
        approval = await uow.session.scalar(
            select(PublishApprovals)
            .where(PublishApprovals.publication_id == publication_id)
            .where(
                (PublishApprovals.expires_at.is_(None))
                | (PublishApprovals.expires_at > datetime.now(UTC))
            )
            .order_by(PublishApprovals.approved_at.desc())
            .limit(1)
        )
        if approval is None:
            return {"error": "no_valid_approval"}

        channel = await uow.session.get(AuthorizedChannel, publication.channel_id)

        # Run platform checks first
        checks_svc = PlatformCheckService()
        await checks_svc.validate_disclosure(publication_id)
        await checks_svc.validate_metadata(publication_id)

        # Publish
        result = await youtube_client.publish_video(
            channel.connection_id,
            publication.private_video_id,
        )

        publication.video_id = publication.private_video_id
        publication.status = PublicationStatus.PUBLISHED
        publication.published_at = datetime.now(UTC)

        return {"video_id": publication.video_id, "status": "published"}
```

#### Service wiring

The tasks need access to `uow_factory`, `store`, and `youtube_client`. These are typically
injected at app startup via `app.state`. Add them to task context or pass them as parameters
from the router/service that triggers the task.

---

### 4E: Platform Checks — Disclosure & Metadata Validators

**File**: `src/oki/publications/checks.py`

#### `validate_disclosure()`

```python
async def validate_disclosure(self, publication_id: UUID) -> None:
    async with self._uow_factory() as uow:
        publication = await uow.session.get(Publications, publication_id)
        job = await uow.session.get(LocalizationJob, publication.job_id)

        # Load the render to check if an Oki creative was inserted
        render_job = await uow.session.scalar(
            select(RenderJob)
            .where(RenderJob.localization_job_id == publication.job_id)
            .order_by(RenderJob.created_at.desc())
            .limit(1)
        )

        has_oki_integration = render_job is not None and render_job.ad_segment_id is not None

        if has_oki_integration:
            # Verify the job's render manifest includes a disclosure card
            manifest = await uow.session.scalar(
                select(RenderManifest).where(
                    RenderManifest.render_job_id == render_job.id
                )
            )
            if manifest is None or not manifest.includes_disclosure_card:
                # Record a failed check
                check = PlatformChecks(
                    organization_id=publication.organization_id,
                    publication_id=publication_id,
                    check_type="disclosure",
                    passed=False,
                    details={"reason": "Oki integration present but disclosure card missing"},
                )
                uow.session.add(check)
                raise ProblemException(
                    status_code=422,
                    code="disclosure_missing",
                    title="Disclosure missing",
                    detail="Video contains Oki integration but no disclosure card was found.",
                )

        check = PlatformChecks(
            organization_id=publication.organization_id,
            publication_id=publication_id,
            check_type="disclosure",
            passed=True,
            details={"has_oki_integration": has_oki_integration},
        )
        uow.session.add(check)
```

#### `validate_metadata()`

```python
async def validate_metadata(self, publication_id: UUID) -> None:
    async with self._uow_factory() as uow:
        publication = await uow.session.get(Publications, publication_id)
        job = await uow.session.get(LocalizationJob, publication.job_id)

        issues = []

        # Check title is not empty and not the default placeholder
        if not job.title or job.title.strip() == "":
            issues.append("title is empty")

        # Check description doesn't contain old promo codes from original
        # (simple heuristic: check for raw discount patterns like "USE CODE X")
        # Real implementation would check the creative's prohibited_claims list
        if job.target_language and job.target_language not in (job.title or ""):
            pass  # Language tag optional but recommended

        passed = len(issues) == 0
        check = PlatformChecks(
            organization_id=publication.organization_id,
            publication_id=publication_id,
            check_type="metadata",
            passed=passed,
            details={"issues": issues},
        )
        uow.session.add(check)

        if not passed:
            raise ProblemException(
                status_code=422,
                code="metadata_invalid",
                title="Metadata validation failed",
                detail=f"Issues found: {', '.join(issues)}",
            )
```

**Note**: The `checks.py` file needs `uow_factory` injected. Update the constructor:
`def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None`.
Update the router/task to pass it when constructing `PlatformCheckService`.

---

### 4F: Campaign & Creative CRUD

**File**: `src/oki/campaigns/router.py`, `src/oki/campaigns/service.py`, `src/oki/campaigns/schemas.py`

The SOW section 3.9 requires full campaign and creative management. Currently only list endpoints exist.

#### Endpoints to add

| Method | Path | Action |
|--------|------|--------|
| `POST` | `/api/campaigns` | Create campaign |
| `PUT` | `/api/campaigns/{id}` | Update campaign (active dates, status) |
| `POST` | `/api/campaigns/{id}/creatives` | Upload creative |
| `PUT` | `/api/campaigns/{id}/creatives/{cid}` | Update creative (approved copy, prohibited claims, CTA) |
| `DELETE` | `/api/campaigns/{id}/creatives/{cid}` | Deactivate creative |

#### Schemas to add in `src/oki/campaigns/schemas.py`

```python
class CampaignCreate(BaseModel):
    name: str
    target_language: str
    target_country: str
    audience_description: str | None = None
    active_from: datetime
    active_until: datetime
    disclosure_text: str | None = None

class CampaignUpdate(BaseModel):
    name: str | None = None
    active_from: datetime | None = None
    active_until: datetime | None = None
    is_active: bool | None = None

class CreativeCreate(BaseModel):
    name: str
    duration_seconds: int
    cta_text: str
    promo_code: str | None = None
    tracking_url: str | None = None
    approved_claims: list[str] = []
    prohibited_claims: list[str] = []
    audio_s3_key: str | None = None
    video_s3_key: str | None = None

class CreativeUpdate(BaseModel):
    cta_text: str | None = None
    promo_code: str | None = None
    tracking_url: str | None = None
    approved_claims: list[str] | None = None
    prohibited_claims: list[str] | None = None
    is_active: bool | None = None
```

#### Business rules to enforce in service

- Expired creatives (`active_until < now`) cannot be selected for new renders. Add a
  `get_active_creatives(campaign_id)` method that filters by `active_until > now`.
- Every creative must have a `tracking_url` or `promo_code` before it can be used in a render
  (SOW: "every integration receives a unique attribution key").
- Deactivating a creative does not delete it — set `is_active = False` and record in audit log.

---

### 4G: Audio Mixing Endpoints

**File**: `src/oki/audio/` — no router exists

The SOW section 3.8 requires: "reviewers can inspect transitions; localized and original mixes
remain separately available." Currently there's no API to trigger or review audio mixing.

#### Minimal endpoints to add

Create `src/oki/audio/router.py`:

| Method | Path | Action |
|--------|------|--------|
| `POST` | `/api/jobs/{job_id}/mix` | Trigger audio mixing for a job |
| `GET` | `/api/jobs/{job_id}/mix` | Get mix status and QA results |
| `GET` | `/api/jobs/{job_id}/mix/playback-url` | Get presigned URL for mixed audio |

The `audio/service.py` has `AudioMixVersion` and `AudioQaResult` models; the mixing logic in
`audio/mixing.py` and `audio/separation.py` needs to be wired. The existing `tasks.py` is a stub.

#### `mix()` service method

```python
async def mix(
    self,
    job_id: UUID,
    principal: Principal,
) -> AudioMixVersion:
    # 1. Load the job and verify state (must be AUDIO_REVIEW or DUBBING_RUNNING)
    # 2. Find the source asset to get the original audio
    # 3. Find the dub segments to get dubbed audio files from S3
    # 4. If stems available: replace speech track, keep music/ambience
    # 5. If no stems: run source separation (audio/separation.py) then mix
    # 6. Run AudioQaChecks (clipping, loudness, silence detection)
    # 7. Upload result to S3 at projects/{job_id}/audio/{language}/mixed.wav
    # 8. Create AudioMixVersion record
    # 9. Create AudioQaResult records for each check
    # 10. Transition workflow state to AUDIO_REVIEW
```

The actual FFmpeg commands for mixing are standard:
- Source separation: `demucs` or `spleeter` (add as optional dependency)
- Mixing speech over music: `ffmpeg -i music.wav -i dub.wav -filter_complex amix`
- Loudness normalization: `ffmpeg -af loudnorm=I=-16:TP=-1.5:LRA=11`

---

## 3. Stage 5 — Shorts & Analytics

### Acceptance gate (SOW): Licensed Shorts can be produced and Oki conversions attributed.

---

### 5A: Shorts Candidate Detection

**Files**: `src/oki/shorts/service.py`, `src/oki/shorts/scoring.py`, `src/oki/shorts/tasks.py`

The SOW specifies generating 10–30 candidate clips based on:
hook strength, completeness of thought, emotion, surprising fact, conflict, question, punchline,
visual activity, information density.

#### Algorithm approach (pragmatic, no ML required for MVP)

Use the existing `TranscriptSegments` to score candidates. The data already available:
- `segment.text` — the spoken words
- `segment.start_time`, `segment.end_time` — timing
- `segment.segment_type` — type classification (question, statement, etc.)
- `SceneDetection` results if available
- Named entities (already extracted in analysis)

#### Implementation in `scoring.py`

```python
import re
from oki.analysis.models import TranscriptSegments

class ShortScorer:
    QUESTION_PATTERNS = re.compile(r'\?|why|how|what|when|who|did you|have you', re.I)
    HOOK_WORDS = re.compile(
        r'\b(never|always|shocking|surprising|secret|truth|wrong|actually|mistake|'
        r'first|only|best|worst|most|least|incredible|amazing)\b', re.I
    )
    CONFLICT_WORDS = re.compile(r'\b(but|however|unfortunately|problem|issue|wrong|fail)\b', re.I)
    NUMBER_PATTERN = re.compile(r'\b\d+\b')

    @classmethod
    def score_segment(cls, segment: TranscriptSegments) -> dict:
        text = segment.text or ""
        duration = (segment.end_time or 0) - (segment.start_time or 0)

        hook_strength = min(1.0, len(cls.HOOK_WORDS.findall(text)) * 0.25)
        question_score = 0.8 if cls.QUESTION_PATTERNS.search(text) else 0.0
        conflict_score = min(1.0, len(cls.CONFLICT_WORDS.findall(text)) * 0.3)
        density_score = min(1.0, len(text.split()) / max(duration, 1) / 3.0)
        number_score = min(0.5, len(cls.NUMBER_PATTERN.findall(text)) * 0.1)

        # Duration fit: prefer 15-60 seconds for Shorts
        if 15 <= duration <= 60:
            duration_fit = 1.0
        elif duration < 15:
            duration_fit = duration / 15.0
        else:
            duration_fit = max(0.0, 1.0 - (duration - 60) / 60.0)

        total = (
            hook_strength * 0.25 +
            question_score * 0.20 +
            conflict_score * 0.15 +
            density_score * 0.15 +
            number_score * 0.05 +
            duration_fit * 0.20
        )

        return {
            "hook_strength": round(hook_strength, 3),
            "pacing": round(density_score, 3),
            "audio_clarity": 0.7,       # default — would require audio analysis
            "visual_engagement": 0.5,   # default — would require scene scoring
            "brand_safety": 1.0,        # default — profanity classifier already exists
            "language_clarity": 0.8,    # default
            "cultural_resonance": 0.5,  # default
            "platform_fit": round(duration_fit, 3),
            "monetization_potential": round(total, 3),
            "total": round(total, 3),
        }
```

#### `generate()` service method — full rewrite

```python
async def generate(
    self,
    job_id: UUID,
    principal: Principal,
    correlation_id: UUID,
    *,
    max_candidates: int = 20,
) -> list[ShortCandidates]:
    async with self._uow_factory() as uow:
        job = await uow.session.get(LocalizationJob, job_id)
        if job is None:
            self._not_found("job_not_found", "Job not found")

        self._authorizer.require(
            principal, Action.PROJECT_READ, self._scope(job.organization_id)
        )

        # Load transcript segments
        segments = list(await uow.session.scalars(
            select(TranscriptSegments)
            .where(TranscriptSegments.job_id == job_id)
            .order_by(TranscriptSegments.start_time)
        ))

        # Score each segment
        scorer = ShortScorer()
        scored = [
            (seg, scorer.score_segment(seg))
            for seg in segments
            if (seg.end_time or 0) - (seg.start_time or 0) >= 10
        ]

        # Sort by total score descending, take top N
        scored.sort(key=lambda x: x[1]["total"], reverse=True)
        top = scored[:max_candidates]

        candidates = []
        for seg, scores in top:
            candidate = ShortCandidates(
                organization_id=job.organization_id,
                job_id=job_id,
                status=ShortStatus.CANDIDATE,
                source_timestamps=[seg.start_time, seg.end_time],
                detected_hooks={
                    "segment_id": str(seg.id),
                    "text_preview": (seg.text or "")[:100],
                },
                raw_score=scores["total"],
                created_by_user_id=principal.user_id,
            )
            uow.session.add(candidate)
            await uow.session.flush()

            # Create score record
            score_record = ShortScores(
                organization_id=job.organization_id,
                candidate_id=candidate.id,
                **scores,
            )
            uow.session.add(score_record)
            candidates.append(candidate)

        return candidates
```

---

### 5B: Shorts — Missing CRUD & Publish Endpoints

**File**: `src/oki/shorts/router.py`

Currently only `POST /api/jobs/generate-shorts` exists.

#### Endpoints to add

| Method | Path | Service | Description |
|--------|------|---------|-------------|
| `GET` | `/api/jobs/{job_id}/shorts` | `list_candidates(job_id)` | List candidates for a job |
| `GET` | `/api/shorts/{id}` | `get_candidate(id)` | Get single candidate |
| `POST` | `/api/shorts/{id}/revise` | `revise(id)` | Create new revision |
| `POST` | `/api/shorts/{id}/approve` | `approve(id)` | Approve for publication |
| `POST` | `/api/shorts/{id}/publish` | `publish(id, channel_id)` | Publish to platform |
| `GET` | `/api/shorts/{id}/playback-url` | `get_playback_url(id)` | Get preview URL |

#### `list_candidates()` service method

```python
async def list_candidates(
    self,
    job_id: UUID,
    principal: Principal,
) -> list[ShortCandidates]:
    async with self._uow_factory() as uow:
        job = await uow.session.get(LocalizationJob, job_id)
        if job is None:
            self._not_found("job_not_found", "Job not found")
        self._authorizer.require(
            principal, Action.PROJECT_READ, self._scope(job.organization_id)
        )
        result = await uow.session.scalars(
            select(ShortCandidates)
            .where(ShortCandidates.job_id == job_id)
            .order_by(ShortCandidates.raw_score.desc().nullslast())
        )
        return list(result)
```

#### `publish()` service method

```python
async def publish(
    self,
    short_id: UUID,
    channel_id: UUID,
    principal: Principal,
    correlation_id: UUID,
) -> ShortPublications:
    async with self._uow_factory() as uow:
        candidate = await uow.session.get(ShortCandidates, short_id)
        if candidate is None:
            self._not_found("short_not_found", "Short not found")

        # Must be approved before publishing
        approval = await uow.session.scalar(
            select(ShortApprovals).where(ShortApprovals.short_id == short_id)
        )
        if approval is None:
            raise ProblemException(
                status_code=409,
                code="short_not_approved",
                title="Short not approved",
                detail="Human approval required before publishing a Short.",
            )

        publication = ShortPublications(
            organization_id=candidate.organization_id,
            short_id=short_id,
            channel_id=channel_id,
            platform="youtube",
            status="pending",
            created_by_user_id=principal.user_id,
        )
        uow.session.add(publication)
        candidate.status = ShortStatus.PUBLISHED
        await uow.session.flush()
        return publication
```

---

### 5C: Shorts — Vertical Crop & Subtitle Generation

**File**: `src/oki/shorts/crop.py`, new `src/oki/shorts/renderer.py`

#### Vertical crop — `CropTracker` implementation

For MVP, implement static center-crop (no face tracking):

```python
class CropTracker:
    TARGET_ASPECT = 9 / 16  # vertical

    def track(
        self,
        source_video_path: str,
        timestamps: list[tuple[float, float]],
    ) -> dict:
        import subprocess, json

        # Get video dimensions via ffprobe
        result = subprocess.run([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", source_video_path,
        ], capture_output=True, text=True)
        data = json.loads(result.stdout)
        video_stream = next(
            (s for s in data["streams"] if s["codec_type"] == "video"), None
        )
        if video_stream is None:
            return {"x": 0, "y": 0, "width": 1080, "height": 1920, "timestamps": timestamps}

        w = int(video_stream["width"])
        h = int(video_stream["height"])

        # Center crop to 9:16
        target_w = min(w, int(h * self.TARGET_ASPECT))
        target_h = min(h, int(w / self.TARGET_ASPECT))
        x = (w - target_w) // 2
        y = (h - target_h) // 2

        return {
            "x": x, "y": y,
            "width": target_w, "height": target_h,
            "timestamps": timestamps,
            "source_width": w, "source_height": h,
        }
```

For face tracking (production), integrate `mediapipe` or `opencv` face detection to reposition
the crop box around the speaker's face. Keep this as a post-MVP enhancement.

#### Shorts renderer — `src/oki/shorts/renderer.py`

```python
class ShortsRenderer:
    """Extract a vertical clip from a rendered video using FFmpeg."""

    async def render_short(
        self,
        source_video_key: str,
        output_key: str,
        start_sec: float,
        end_sec: float,
        crop: dict,
        store: ObjectStore,
    ) -> str:
        import tempfile, os, subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, "source.mp4")
            out_path = os.path.join(tmpdir, "short.mp4")

            await store.download_file(source_video_key, in_path)

            x, y, w, h = crop["x"], crop["y"], crop["width"], crop["height"]
            duration = end_sec - start_sec

            cmd = [
                "ffmpeg", "-ss", str(start_sec), "-i", in_path,
                "-t", str(duration),
                "-vf", f"crop={w}:{h}:{x}:{y},scale=1080:1920:force_original_aspect_ratio=decrease",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                out_path, "-y",
            ]
            subprocess.run(cmd, check=True, capture_output=True)

            await store.upload_file(out_path, output_key)
            return output_key
```

#### Subtitle safe-zone validation

After cropping, verify subtitles (if any) fall within the YouTube Shorts safe zone:
- Top: first 14% of height (reserved for UI)
- Bottom: last 20% of height (reserved for captions/CTA)
- Sides: 5% margin on each side

The `render_short` method should accept a `subtitle_path` parameter and burn them in using
`ffmpeg -vf "subtitles=path:force_style='..."`.

---

### 5D: YouTube Analytics Ingestion

**File**: `src/oki/analytics/youtube.py`

#### `YoutubeAnalyticsIngestor.ingest()` implementation

```python
async def ingest(
    self,
    channel_id: str,
    date_range: tuple[str, str],
    *,
    access_token: str,
) -> dict[str, Any]:
    """Pull metrics from YouTube Analytics API and store them."""
    import httpx

    metrics = "views,estimatedMinutesWatched,likes,subscribersGained"
    dimensions = "day"
    start_date, end_date = date_range

    async with httpx.AsyncClient() as http:
        resp = await http.get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            params={
                "ids": f"channel=={channel_id}",
                "startDate": start_date,
                "endDate": end_date,
                "metrics": metrics,
                "dimensions": dimensions,
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()

    return data
```

#### `ingest_video_metrics()` implementation

```python
async def ingest_video_metrics(
    self,
    video_id: str,
    *,
    access_token: str,
    date_range: tuple[str, str] | None = None,
) -> dict[str, Any]:
    import httpx
    from datetime import date, timedelta

    if date_range is None:
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=28)).isoformat()
        date_range = (start, end)

    async with httpx.AsyncClient() as http:
        resp = await http.get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            params={
                "ids": "channel==MINE",
                "startDate": date_range[0],
                "endDate": date_range[1],
                "metrics": "views,estimatedMinutesWatched,likes",
                "dimensions": "day",
                "filters": f"video=={video_id}",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()
```

#### Ingestion worker / scheduled task

Add `src/oki/analytics/tasks.py` with a Hatchet-compatible task:

```python
async def ingest_youtube_analytics_task(
    organization_id: UUID,
    *,
    date_range: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """Pull analytics for all published videos in an organization."""
    # 1. Load all OAuthConnections for the org
    # 2. Load all Publications with status=PUBLISHED and video_id set
    # 3. For each, call ingest_video_metrics()
    # 4. Upsert into YoutubeMetricPoints (use (video_id, metric_type, captured_at) as unique key)
    # 5. Create a MetricIngestionRuns record
```

Add an endpoint to trigger ingestion manually:
`POST /api/analytics/ingest` — fires the task, returns a `MetricIngestionRuns` record.

---

### 5E: Oki Conversion Event Pipeline

**File**: `src/oki/analytics/oki_events.py`

The SOW requires tracking clicks, installs, registrations, trial starts, purchases. Each event
arrives with a `link_token` from the attribution URL embedded in the video.

#### `OkiEventIngestor.record_conversion()` implementation

```python
async def record_conversion(
    self,
    event_data: dict[str, Any],
    *,
    uow_factory: Callable[[], UnitOfWork],
) -> dict[str, Any]:
    """Store a conversion event and resolve attribution."""
    async with uow_factory() as uow:
        # Resolve attribution from link_token
        link_token = event_data.get("link_token", "")
        organization_id = event_data.get("organization_id")

        attribution_link = None
        if link_token:
            attribution_link = await uow.session.scalar(
                select(AttributionLinks)
                .where(AttributionLinks.link_token == link_token)
            )

        # Build the event
        event = OkiConversionEvents(
            organization_id=organization_id,
            event_type=event_data["event_type"],  # "install", "registration", "purchase", etc.
            attributed_creator_id=attribution_link.creator_id if attribution_link else None,
            attributed_job_id=attribution_link.job_id if attribution_link else None,
            attributed_language=event_data.get("language"),
            attributed_campaign_id=event_data.get("campaign_id"),
            value=event_data.get("value"),
            currency=event_data.get("currency", "USD"),
            event_metadata=event_data,
            occurred_at=datetime.fromisoformat(
                event_data.get("occurred_at", datetime.now(UTC).isoformat())
            ),
        )
        uow.session.add(event)
        await uow.session.flush()

        if attribution_link:
            link = AttributionLinks(
                organization_id=organization_id,
                event_id=event.id,
                source=attribution_link.source,
                link_token=link_token,
                landing_url=attribution_link.landing_url,
            )
            uow.session.add(link)

        return {"event_id": str(event.id), "attributed": attribution_link is not None}
```

#### Attribution link generation

Add `POST /api/analytics/attribution-link` endpoint that creates a unique `AttributionLink`
with a `link_token` for a given `(job_id, campaign_id, placement)`. The token is a
`secrets.token_urlsafe(16)` string. This link is embedded as the CTA URL in renders.

Add `POST /api/analytics/conversions` as the incoming webhook endpoint that calls
`record_conversion()`. This endpoint should be public (no auth) but verify an HMAC signature
from the Oki app.

---

### 5F: Reports — Daily & Weekly

**File**: `src/oki/analytics/reports.py`

Both builders currently return empty structures. Fill them with real DB queries.

#### `DailyProductionReport.build()` implementation

```python
def build(
    self,
    report_date: date,
    *,
    uow: UnitOfWork,
    organization_id: UUID,
) -> dict[str, Any]:
    from sqlalchemy import func

    # Jobs completed today
    completed_jobs = uow.session.execute(
        select(func.count(LocalizationJob.id))
        .where(
            LocalizationJob.organization_id == organization_id,
            func.date(LocalizationJob.updated_at) == report_date,
            LocalizationJob.state == WorkflowState.PUBLISHED,
        )
    ).scalar()

    # Costs today (from cost ledger)
    total_cost = uow.session.execute(
        select(func.sum(CostLedgerEntries.amount))
        .where(
            CostLedgerEntries.organization_id == organization_id,
            func.date(CostLedgerEntries.incurred_at) == report_date,
        )
    ).scalar() or Decimal("0.00")

    # Oki installs today
    installs = uow.session.execute(
        select(func.count(OkiConversionEvents.id))
        .where(
            OkiConversionEvents.organization_id == organization_id,
            OkiConversionEvents.event_type == "install",
            func.date(OkiConversionEvents.occurred_at) == report_date,
        )
    ).scalar()

    return {
        "report_type": "daily_production",
        "date": report_date.isoformat(),
        "jobs_completed": {"count": completed_jobs or 0},
        "costs": {"total": str(total_cost), "currency": "USD"},
        "oki_installs": installs or 0,
    }
```

Make the method `async` since it needs a real DB session. Convert the report builders to accept
a `uow` parameter.

Add endpoints:
- `GET /api/analytics/reports/daily?date=YYYY-MM-DD`
- `GET /api/analytics/reports/weekly?week_start=YYYY-MM-DD`

---

### 5G: Analytics CSV Export

**File**: `src/oki/analytics/router.py`

Add `GET /api/analytics/export` that generates a CSV and returns it as a file download:

```python
@router.get("/analytics/export")
async def export_analytics(
    request: Request,
    org_id: UUID,
    start_date: str,
    end_date: str,
    principal: Principal = Depends(current_principal),
) -> StreamingResponse:
    import csv, io

    rows = await _service(request).get_video_metrics(principal, org_id)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys() if rows else [])
    writer.writeheader()
    writer.writerows(rows)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=analytics_{start_date}_{end_date}.csv"},
    )
```

---

### 5H: Finance — Revenue Share from Agreement & Export File

**File**: `src/oki/finance/service.py`, `src/oki/finance/calculator.py`

Two gaps:

#### 1. Read revenue share from agreement (not hardcoded 10000 bps)

Replace the `TODO` in `create_run()`:

```python
# Instead of: share_bps=10000
# Do:
from oki.rights.models import RightsAgreement, RightsAgreementVersion
agreement = await uow.session.scalar(
    select(RightsAgreement)
    .where(
        RightsAgreement.creator_id == item.creator_id,
        RightsAgreement.organization_id == payload.organization_id,
    )
    .order_by(RightsAgreement.created_at.desc())
    .limit(1)
)
version = None
if agreement:
    version = await uow.session.scalar(
        select(RightsAgreementVersion)
        .where(RightsAgreementVersion.agreement_id == agreement.id)
        .order_by(RightsAgreementVersion.agreement_version_number.desc())
        .limit(1)
    )

# revenue_share_bps is a column on RightsAgreementVersion (check the model)
share_bps = version.revenue_share_bps if version and version.revenue_share_bps else 5000
```

Verify the column name in `src/oki/rights/models.py` — it may be called `revenue_share_bps`,
`revenue_share`, or similar.

#### 2. Generate actual export file

Replace the `TODO` in `export()`:

```python
import csv, io, boto3

rows = await uow.session.execute(
    select(CreatorPayouts)
    .where(CreatorPayouts.run_id == run_id)
).scalars()

if export_type == "csv":
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["creator_id", "calculated_amount", "currency", "status"])
    for row in rows:
        writer.writerow([
            str(row.creator_id),
            str(row.calculated_amount),
            row.currency,
            row.status,
        ])
    content = output.getvalue().encode()
    s3_key = f"finance/exports/{run_id}/{export_type}.csv"
    await store.put_object(s3_key, content, content_type="text/csv")
    file_url = await store.presign_get(s3_key)
    checksum = hashlib.sha256(content).hexdigest()
    export_record.file_url = file_url
    export_record.file_sha256 = checksum
```

---

## 4. Stage 6 — Production Hardening

### Acceptance gate (SOW): All critical tests pass, monitoring configured, runbook complete.

---

### 6A: Notifications System

**SOW section 3.15**: rights expiration, failed jobs, review tasks, creator approval, publication
errors, platform claims, campaign expiration, payout approval.
Delivery: email, Telegram, in-app.

#### Recommended architecture

Add a new `src/oki/notifications/` module:

```
src/oki/notifications/
    __init__.py
    models.py      — NotificationEvent, NotificationDelivery
    service.py     — create notification, mark read
    channels/
        email.py   — SendGrid or SMTP
        telegram.py — Telegram Bot API
    router.py      — GET /api/notifications, PATCH /api/notifications/{id}/read
    tasks.py       — dispatch_notification_task (Hatchet)
```

#### Models

```python
class NotificationEvent(TimestampMixin, Base):
    __tablename__ = "notification_events"
    id: UUID (PK)
    organization_id: UUID
    event_type: str  # "rights_expiring", "job_failed", "review_required", etc.
    entity_type: str  # "rights_agreement", "localization_job", "publication"
    entity_id: UUID
    payload: JSONB   # human-readable details
    severity: str    # "info", "warning", "critical"
    created_at: datetime

class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id: UUID
    event_id: UUID (FK)
    channel: str      # "email", "telegram", "in_app"
    recipient: str    # email, chat_id, user_id
    delivered_at: datetime | None
    read_at: datetime | None
    error: str | None
```

#### Migration

Add migration `0022_notifications.py`.

#### Trigger points

Hook notification creation into existing services via post-commit callbacks:

| Event | Trigger location |
|-------|-----------------|
| `rights_expiring_soon` | Scheduled task, daily, checks `expiration_date < now() + 14 days` |
| `job_failed` | `jobs/service.py` when transitioning to `FAILED` state |
| `review_required` | `reviews/service.py` in `create_package()` |
| `publication_failed` | `publications/tasks.py` on exception |
| `platform_claim` | `publications/tasks.py` when YouTube returns a claim |
| `campaign_expiring` | Scheduled task, daily, checks `active_until < now() + 7 days` |
| `payout_pending` | `finance/service.py` in `create_run()` |

#### Email channel (`channels/email.py`)

```python
import smtplib
from email.mime.text import MIMEText

class EmailChannel:
    def __init__(self, settings: Settings) -> None:
        self._smtp_host = settings.smtp_host
        self._smtp_port = settings.smtp_port
        self._smtp_user = settings.smtp_user
        self._smtp_password = settings.smtp_password
        self._from_address = settings.notification_from_email

    async def send(self, recipient: str, subject: str, body: str) -> None:
        msg = MIMEText(body, "html")
        msg["Subject"] = subject
        msg["From"] = self._from_address
        msg["To"] = recipient
        # Use asyncio to avoid blocking: run in executor
        import asyncio
        await asyncio.get_event_loop().run_in_executor(
            None, self._send_sync, msg
        )
```

#### Settings additions

```python
smtp_host: str = ""
smtp_port: int = 587
smtp_user: str = ""
smtp_password: str = ""
notification_from_email: str = "noreply@oki.example"
telegram_bot_token: str = ""
```

---

### 6B: OpenTelemetry & Sentry

**SOW section 4.4**: structured logs, job-level tracing, API latency metrics, worker failure
metrics, provider cost metrics, storage usage, queue depth, alerting.

#### Add OpenTelemetry to `src/oki/main.py`

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

def setup_telemetry(app: FastAPI, settings: Settings) -> None:
    if not settings.otel_exporter_endpoint:
        return

    provider = TracerProvider()
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
```

#### Add Sentry

```python
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

def setup_sentry(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        traces_sample_rate=0.1,
    )
```

#### Settings additions

```python
otel_exporter_endpoint: str = ""
sentry_dsn: str = ""
environment: str = "development"
```

#### Provider cost metrics

In each provider call (ElevenLabs, OpenAI transcription, OpenAI translation), record to
`CostLedgerEntries`. A Prometheus counter can be added:

```python
from prometheus_client import Counter, Histogram

provider_cost_counter = Counter(
    "oki_provider_cost_usd_total",
    "Total provider cost in USD",
    ["provider", "operation"],
)
job_duration_histogram = Histogram(
    "oki_job_duration_seconds",
    "Job processing duration",
    ["stage"],
)
```

Add `prometheus_client` to dependencies. Expose `/metrics` endpoint (behind internal auth).

---

### 6C: Automated Tests

**SOW section 6**: rights tests, media tests, translation/dubbing tests, rendering/publishing tests.

#### Test structure

```
tests/
    conftest.py         — pytest fixtures: test DB, seeded org, principal factories
    test_rights.py      — 6 rights gate scenarios
    test_media.py       — 6 media ingestion scenarios
    test_dubbing.py     — 16 dubbing tests (from DUBBING_STAGE_PLAN.md)
    test_publications.py — 8 publishing scenarios
    test_analytics.py   — attribution and conversion tests
    test_workflow.py    — state machine transition tests
    test_finance.py     — payout calculation tests
```

#### Critical rights tests (`tests/test_rights.py`)

```python
@pytest.mark.asyncio
async def test_no_agreement_blocks_translation(db, principal):
    """Translation job cannot start when no rights agreement exists."""
    asset = await create_asset(db)
    with pytest.raises(ProblemException) as exc:
        await translation_service.start(asset.id, "es", principal)
    assert exc.value.status_code == 403
    assert "rights" in exc.value.code

@pytest.mark.asyncio
async def test_expired_agreement_blocks_publication(db, principal):
    """Publication is blocked when rights agreement is expired."""
    ...

@pytest.mark.asyncio
async def test_voice_clone_requires_consent(db, principal):
    """Voice clone mode blocked without explicit VoiceConsent record."""
    ...

@pytest.mark.asyncio
async def test_sponsor_replacement_requires_authorization(db, principal):
    """Sponsor segment replacement blocked without SPONSOR_REPLACEMENT_APPROVED."""
    ...
```

#### State machine tests (`tests/test_workflow.py`)

```python
def test_all_primary_transitions():
    """Every primary transition in the SOW state diagram is reachable."""
    sm = WorkflowStateMachine()
    # Walk the happy path from CREATOR_LEAD to ARCHIVED
    ...

def test_publish_approved_requires_employee_actor():
    """PUBLISH_APPROVED event rejected for non-employee actors."""
    ...

def test_block_and_resume():
    """BLOCK saves resumable_state; RESUME restores it."""
    ...
```

#### Conftest fixtures

```python
@pytest.fixture
async def db():
    """In-memory or test Postgres with all migrations applied."""
    # Use pytest-asyncio + SQLAlchemy async engine against test DB
    ...

@pytest.fixture
def employee_principal() -> Principal:
    return Principal(
        user_id=uuid4(),
        actor_type="employee",
        memberships=[Membership(organization_id=TEST_ORG_ID, actions=[Action.PUBLICATION_RELEASE_PUBLIC, ...])],
    )
```

---

### 6D: Security Hardening

**SOW section 4.1**: encryption, rate limiting, malware scanning, dependency scanning,
security-event logging.

#### Items to add

1. **Rate limiting**: Add `slowapi` to dependencies.
   ```python
   from slowapi import Limiter, _rate_limit_exceeded_handler
   from slowapi.util import get_remote_address
   limiter = Limiter(key_func=get_remote_address)
   app.state.limiter = limiter
   app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
   ```
   Apply `@limiter.limit("100/minute")` on upload, publish, and OAuth endpoints.

2. **Security headers**: Add `starlette-middleware-security` or manually add:
   ```python
   app.add_middleware(
       TrustedHostMiddleware,
       allowed_hosts=settings.allowed_hosts.split(","),
   )
   ```

3. **Dependency scanning**: Add `pip-audit` to CI workflow:
   ```yaml
   - name: Dependency audit
     run: pip-audit
   ```

4. **Security event logging**: Ensure all `add_mutation_evidence()` calls cover:
   - Rights agreement approval/revocation
   - Voice consent creation
   - Sponsor replacement authorization
   - Publication (upload and publish)
   - OAuth token grant/revocation
   - Creator approval decision

5. **Token revocation check**: Before any YouTube API call, verify the `OAuthConnection.is_active`
   flag and handle `401` responses by revoking the local token and notifying the user.

6. **Secrets audit**: Run `trufflesec` or `detect-secrets` in CI to prevent secrets in code.

---

### 6E: Cost Controls & Provider Limits

**SOW section 4.2**: provider cost limits, graceful provider failure.

#### Add to `Settings`

```python
elevenlabs_monthly_limit_usd: float = 100.0
openai_monthly_limit_usd: float = 200.0
cost_alert_threshold_pct: float = 0.80  # alert at 80% of limit
```

#### Cost guard in providers

Add a `CostGuard` class:

```python
class CostGuard:
    def __init__(self, uow_factory, settings: Settings) -> None:
        self._uow_factory = uow_factory
        self._settings = settings

    async def check_budget(
        self,
        provider: str,
        organization_id: UUID,
    ) -> None:
        """Raise if monthly spend exceeds the configured limit."""
        from datetime import date
        start_of_month = date.today().replace(day=1)
        async with self._uow_factory() as uow:
            spent = await uow.session.scalar(
                select(func.sum(CostLedgerEntries.amount))
                .where(
                    CostLedgerEntries.organization_id == organization_id,
                    CostLedgerEntries.cost_category == provider,
                    CostLedgerEntries.incurred_at >= start_of_month,
                )
            ) or Decimal("0")

        limit = getattr(
            self._settings,
            f"{provider}_monthly_limit_usd",
            None,
        )
        if limit and float(spent) >= limit:
            raise ProblemException(
                status_code=429,
                code="provider_budget_exceeded",
                title="Provider budget exceeded",
                detail=f"Monthly {provider} budget of ${limit} exceeded.",
            )
```

Call `CostGuard.check_budget("elevenlabs", org_id)` before any `ElevenLabsClient.synthesize()`
call and before any OpenAI call.

---

### 6F: Backup & Restore

#### PostgreSQL backup

Add `scripts/backup_db.sh`:
```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
pg_dump $DATABASE_URL | gzip > backups/oki_backup_$DATE.sql.gz
aws s3 cp backups/oki_backup_$DATE.sql.gz s3://$BACKUP_BUCKET/db/
```

Schedule via cron (or add a Hatchet scheduled workflow that runs daily).

#### S3 backup

Enable versioning on the production S3 bucket. Add a lifecycle rule to move versions older than
90 days to Glacier.

#### Restore procedure (document in runbook)

```bash
# 1. Download backup
aws s3 cp s3://$BACKUP_BUCKET/db/oki_backup_TIMESTAMP.sql.gz .
gunzip oki_backup_TIMESTAMP.sql.gz

# 2. Restore
psql $DATABASE_URL < oki_backup_TIMESTAMP.sql

# 3. Verify migrations
alembic current

# 4. Validate data
psql $DATABASE_URL -c "SELECT count(*) FROM localization_jobs;"
```

---

### 6G: Deployment & Documentation

#### Environment variable template (`.env.example`)

```bash
# Database
DATABASE_URL=postgresql+asyncpg://oki:oki@localhost:5432/oki

# Redis
REDIS_URL=redis://localhost:6379/0

# S3 / SeaweedFS
S3_ENDPOINT_URL=http://localhost:8333
S3_ACCESS_KEY_ID=admin
S3_SECRET_ACCESS_KEY=admin
S3_BUCKET=oki

# Auth
KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_REALM=oki
KEYCLOAK_CLIENT_ID=oki-backend
KEYCLOAK_CLIENT_SECRET=

# YouTube
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_OAUTH_CALLBACK_URL=http://localhost:8000/api/youtube/callback

# Providers
ELEVENLABS_API_KEY=
OPENAI_API_KEY=

# Review links
REVIEW_LINK_SECRET=change-this-to-a-random-secret

# Notifications
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
NOTIFICATION_FROM_EMAIL=noreply@oki.example
TELEGRAM_BOT_TOKEN=

# Observability
SENTRY_DSN=
OTEL_EXPORTER_ENDPOINT=

# Cost controls
ELEVENLABS_MONTHLY_LIMIT_USD=100
OPENAI_MONTHLY_LIMIT_USD=200

# Security
ALLOWED_HOSTS=localhost,oki.example
ENVIRONMENT=development
```

#### Docker Compose for production

Add `compose.prod.yaml` with:
- No port exposure (internal network only)
- Health checks on all services
- Restart policies
- Volume mounts for persistent data
- Environment loaded from `.env`

#### Runbook (`RUNBOOK.md`)

Key sections:
1. Starting / stopping the stack
2. Running database migrations
3. Seeding demo data
4. Resetting a stuck workflow job (SQL)
5. Re-triggering a failed publish
6. Revoking a creator's agreement
7. Rotating API keys
8. Checking provider costs
9. Backing up and restoring data
10. Incident response (who to contact, what to check first)

---

## 5. Execution Order & Dependencies

### Stage 4 (do these in order within stage)

| Step | Task | Depends on |
|------|------|------------|
| 4.1 | Settings: add `youtube_client_id`, `youtube_client_secret`, `review_link_secret` | nothing |
| 4.2 | YouTube OAuth — real token exchange (4B) | 4.1 |
| 4.3 | YouTube client — upload/publish methods (4C) | 4.2 |
| 4.4 | Campaign CRUD — schemas + endpoints (4F) | nothing |
| 4.5 | Platform checks — disclosure + metadata validators (4E) | nothing |
| 4.6 | Publication tasks — wire to YouTube (4D) | 4.3, 4.5 |
| 4.7 | Review endpoints — create-package, comment, versions (4A) | nothing |
| 4.8 | Creator-facing review portal — signed JWT + endpoints (4A) | 4.1 |
| 4.9 | Audio mixing router (4G) | nothing |

### Stage 5 (many can run in parallel)

| Step | Task | Depends on |
|------|------|------------|
| 5.1 | Shorts scoring implementation (5A) | nothing |
| 5.2 | Shorts generate() service rewrite (5A) | 5.1 |
| 5.3 | Shorts CRUD + publish endpoints (5B) | 5.2 |
| 5.4 | Shorts vertical crop (5C) | nothing |
| 5.5 | YouTube Analytics ingestion (5D) | Stage 4 YouTube client |
| 5.6 | Oki conversion event pipeline (5E) | nothing |
| 5.7 | Attribution link generation endpoint (5E) | 5.6 |
| 5.8 | Reports — daily + weekly (5F) | 5.5, 5.6 |
| 5.9 | Analytics CSV export (5G) | nothing |
| 5.10 | Finance — read agreement revenue share (5H) | nothing |
| 5.11 | Finance — export file generation (5H) | nothing |

### Stage 6 (can overlap with Stage 5)

| Step | Task |
|------|------|
| 6.1 | Notifications system (models + migration + channels) |
| 6.2 | Wire notification triggers in existing services |
| 6.3 | OpenTelemetry + Sentry setup |
| 6.4 | Cost guards in providers |
| 6.5 | Rate limiting |
| 6.6 | Automated tests (write alongside each feature) |
| 6.7 | `.env.example` + compose.prod.yaml |
| 6.8 | RUNBOOK.md |

---

## 6. Files Changed Summary

### Stage 4

| File | Change |
|------|--------|
| `src/oki/config.py` | Add YouTube, review_link_secret, SMTP, Sentry, OTEL settings |
| `src/oki/youtube/oauth.py` | Implement real PKCE, real token exchange, real channel fetch, token refresh |
| `src/oki/youtube/client.py` | Implement upload_video, publish_video, update_metadata, upload_caption, poll_processing_status |
| `src/oki/publications/tasks.py` | Implement upload_to_platform_task, publish_task |
| `src/oki/publications/checks.py` | Implement validate_disclosure, validate_metadata; add uow_factory |
| `src/oki/reviews/router.py` | Add create-package, comment, list-versions, invalidate, creator-portal endpoints |
| `src/oki/reviews/schemas.py` | Add CreateReviewPackageResponse, CommentRequest/Response, PackageVersionResponse |
| `src/oki/campaigns/router.py` | Add POST /campaigns, PUT /campaigns/{id}, POST/PUT/DELETE creatives |
| `src/oki/campaigns/schemas.py` | Add CampaignCreate, CampaignUpdate, CreativeCreate, CreativeUpdate |
| `src/oki/campaigns/service.py` | Add create_campaign, update_campaign, create_creative, update_creative, deactivate_creative |
| `src/oki/audio/router.py` | NEW — POST/GET /api/jobs/{id}/mix |

### Stage 5

| File | Change |
|------|--------|
| `src/oki/shorts/service.py` | Rewrite generate() with real scoring; add list_candidates, get_candidate, publish |
| `src/oki/shorts/scoring.py` | Implement ShortScorer with real heuristics |
| `src/oki/shorts/crop.py` | Implement CropTracker with ffprobe-based center crop |
| `src/oki/shorts/router.py` | Add GET list, GET single, POST revise, POST approve, POST publish, GET playback-url |
| `src/oki/shorts/renderer.py` | NEW — ShortsRenderer FFmpeg extraction |
| `src/oki/analytics/youtube.py` | Implement ingest() and ingest_video_metrics() with real HTTP calls |
| `src/oki/analytics/oki_events.py` | Implement record_conversion() with real DB writes and attribution |
| `src/oki/analytics/reports.py` | Implement build() with real DB queries; make async |
| `src/oki/analytics/router.py` | Add POST /analytics/ingest, POST /analytics/conversions, GET /analytics/export, GET /analytics/reports/daily, GET /analytics/reports/weekly, POST /analytics/attribution-link |
| `src/oki/analytics/tasks.py` | NEW — ingest_youtube_analytics_task |
| `src/oki/finance/service.py` | Replace hardcoded share_bps with agreement lookup; implement export file generation |

### Stage 6

| File | Change |
|------|--------|
| `src/oki/notifications/` | NEW module (models, service, router, channels, tasks) |
| `migrations/versions/0022_notifications.py` | NEW migration |
| `src/oki/main.py` | Add OpenTelemetry, Sentry, rate limiter, notification service setup |
| `src/oki/providers/elevenlabs.py` | Add CostGuard call before synthesize() |
| `tests/conftest.py` | NEW — test fixtures |
| `tests/test_rights.py` | NEW |
| `tests/test_media.py` | NEW |
| `tests/test_publications.py` | NEW |
| `tests/test_workflow.py` | NEW |
| `tests/test_analytics.py` | NEW |
| `tests/test_finance.py` | NEW |
| `.env.example` | NEW |
| `compose.prod.yaml` | NEW |
| `scripts/backup_db.sh` | NEW |
| `RUNBOOK.md` | NEW |
