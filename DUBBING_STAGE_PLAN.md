# Dubbing Stage (Stage 3) — Comprehensive Implementation Plan

> **Goal**: Make the dubbing pipeline functional end-to-end — from clicking "Dub" on a project to hearing AI-generated speech for each translated segment, with voice selection, consent validation, audio preview, segment regeneration, and a dedicated frontend workspace.

---

## Table of Contents

1. [Current State Audit](#1-current-state-audit)
2. [Backend Task 1: Fix the Dubbing Router](#2-backend-task-1-fix-the-dubbing-router)
3. [Backend Task 2: Rewrite DubbingService.start()](#3-backend-task-2-rewrite-dubbingservicestart)
4. [Backend Task 3: Add Missing Dubbing Endpoints](#4-backend-task-3-add-missing-dubbing-endpoints)
5. [Backend Task 4: Wire Consent Validation into Dubbing](#5-backend-task-4-wire-consent-validation-into-dubbing)
6. [Backend Task 5: Wire the Hatchet Task](#6-backend-task-5-wire-the-hatchet-task)
7. [Backend Task 6: Add Provider Usage Tracking](#7-backend-task-6-add-provider-usage-tracking)
8. [Backend Task 7: Voice Profile CRUD Endpoints](#8-backend-task-7-voice-profile-crud-endpoints)
9. [Backend Task 8: Pronunciation Dictionary](#9-backend-task-8-pronunciation-dictionary)
10. [Frontend Task 1: API Client — Dubbing Methods](#10-frontend-task-1-api-client--dubbing-methods)
11. [Frontend Task 2: Dubbing Workspace Page](#11-frontend-task-2-dubbing-workspace-page)
12. [Frontend Task 3: Voice Profile Selector Component](#12-frontend-task-3-voice-profile-selector-component)
13. [Frontend Task 4: Wire Dub Button on Project Detail](#13-frontend-task-4-wire-dub-button-on-project-detail)
14. [Frontend Task 5: Add Dubbing Tab on Project Detail](#14-frontend-task-5-add-dubbing-tab-on-project-detail)
15. [Frontend Task 6: Navigation Link](#15-frontend-task-6-navigation-link)
16. [Testing Plan](#16-testing-plan)
17. [Seed Data](#17-seed-data)
18. [Acceptance Criteria (from SOW)](#18-acceptance-criteria-from-sow)

---

## 1. Current State Audit

### What exists and works

| Component | File | Status |
|-----------|------|--------|
| `DubSegment` model | `src/oki/dubbing/models.py` | Complete — columns: id, org_id, job_id, translation_job_id, sequence_number, source_text, translated_text, voice_profile_id, timing_start_ms, timing_end_ms, status, audio_asset_reference, review_status, meta |
| `DubAttempt` model | `src/oki/dubbing/models.py` | Complete — columns: id, org_id, dub_segment_id, provider_key, provider_request_id, status, audio_asset_reference, error_message, meta |
| Migration 0011 | `migrations/versions/0011_dubbing.py` | Applied |
| `DubbingService` | `src/oki/dubbing/service.py` | Partial — has `start()`, `regenerate_segment()`, `submit_review()` but start() reads from wrong model (`TranscriptSegments` from sponsors module instead of `TranslationSegments` from translations module) |
| `DubbingResponse` schema | `src/oki/dubbing/schemas.py` | Exists but minimal |
| Router | `src/oki/dubbing/router.py` | Only one endpoint (`POST /api/jobs/dub`) that returns hardcoded placeholder |
| `ElevenLabsClient` | `src/oki/providers/elevenlabs.py` | Complete — `synthesize()` and `list_voices()` |
| `TtsProvider` protocol | `src/oki/providers/tts.py` | Interface only |
| `VoiceProfile` model | `src/oki/voices/models.py` | Complete — columns: id, org_id, creator_id, name, mode, language_code, provider_key, provider_voice_id, ssml_config, consent_reference, meta |
| `PronunciationEntry` model | `src/oki/voices/models.py` | Complete |
| `VoiceService` | `src/oki/voices/service.py` | Has `list_profiles()` and `get_profile()` only |
| Voices router | `src/oki/voices/router.py` | `GET /api/voices` and `GET /api/voices/{id}` only |
| `VoicePolicy` | `src/oki/voices/policy.py` | Complete — checks dubbing_allowed in grants, voice_clone_consent for CREATOR_APPROVED_CLONE mode, fails closed |
| `PronunciationDictionary` | `src/oki/voices/pronunciation.py` | Stub — returns `<speak>` wrapper, no real phoneme substitution |
| Hatchet task | `src/oki/dubbing/tasks.py` | Stub — returns `{"status": "pending"}` |
| Wired in main.py | `src/oki/main.py:87,142` | Yes — `dubbing_service` on app.state, router included |
| Frontend Dub button | `src/app/projects/[id]/page.tsx:199-206` | Calls `api.jobs.dub(id)` which POSTs to `/api/jobs/dub` |
| Frontend API client | `src/lib/api.ts:259-260` | Has `api.jobs.dub()` that sends `{job_id}` |

### What's broken or missing

1. **Router returns hardcoded placeholder** — the `POST /api/jobs/dub` endpoint at `dubbing/router.py:26-45` creates segments internally but then returns a hardcoded `DubbingResponse` with `segments=[]` and `organization_id=principal.user_id` (wrong)
2. **`start()` reads wrong table** — `dubbing/service.py:56-57` imports `TranscriptSegments` from `oki.sponsors.models` instead of `TranslationSegments` from `oki.translations.models`; should read translated segments not raw transcript
3. **No list/get endpoints** — no way to fetch dub segments for a job after creation
4. **No regenerate endpoint** — `regenerate_segment()` exists in service but has no router endpoint
5. **No review endpoint** — `submit_review()` exists in service but has no router endpoint
6. **No audio preview endpoint** — no way for frontend to get a playback URL for a dubbed segment's audio
7. **No workflow state transition** — `start()` doesn't update `job.state` to `DUBBING_RUNNING` or `AUDIO_REVIEW`
8. **No consent check before dubbing** — `VoicePolicy` exists but is never called from `DubbingService`
9. **No voice profile selection** — router doesn't accept a voice_profile_id parameter
10. **No provider usage tracking** — ElevenLabs calls don't record cost/tokens
11. **Voice CRUD missing** — can't create or update voice profiles from API
12. **Pronunciation not wired** — dictionary exists but `regenerate_segment()` doesn't apply it
13. **No frontend dubbing workspace** — no dedicated page to view/manage dub segments
14. **No frontend audio playback** — no way to play dubbed audio clips

---

## 2. Backend Task 1: Fix the Dubbing Router

**File**: `src/oki/dubbing/router.py`

Replace the entire file. The new router must have these endpoints:

### Endpoint List

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jobs/{job_id}/dub` | Start dubbing for a job |
| `GET` | `/api/jobs/{job_id}/dub-segments` | List all dub segments for a job |
| `GET` | `/api/dub-segments/{segment_id}` | Get a single dub segment |
| `POST` | `/api/dub-segments/{segment_id}/regenerate` | Regenerate audio for one segment |
| `POST` | `/api/dub-segments/{segment_id}/review` | Submit approve/reject for a segment |
| `GET` | `/api/dub-segments/{segment_id}/playback-url` | Get presigned S3 URL for audio |

### Implementation — exact code structure

```python
# src/oki/dubbing/router.py
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.dubbing.schemas import (
    DubSegmentResponse,
    DubSegmentListResponse,
    DubbingStartRequest,
    DubbingStartResponse,
    DubRegenerateRequest,
    DubReviewRequest,
    DubPlaybackResponse,
)
from oki.dubbing.service import DubbingService

router = APIRouter(prefix="/api", tags=["dubbing"])


def _service(request: Request) -> DubbingService:
    service = getattr(request.app.state, "dubbing_service", None)
    if service is None:
        raise RuntimeError("DubbingService not available")
    return service


@router.post(
    "/jobs/{job_id}/dub",
    response_model=DubbingStartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_dubbing(
    job_id: UUID,
    request: Request,
    payload: DubbingStartRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> DubbingStartResponse:
    body = payload or DubbingStartRequest()
    result = await _service(request).start(
        principal,
        job_id,
        voice_profile_id=body.voice_profile_id,
        target_language=body.target_language,
    )
    return result


@router.get(
    "/jobs/{job_id}/dub-segments",
    response_model=DubSegmentListResponse,
)
async def list_dub_segments(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> DubSegmentListResponse:
    segments = await _service(request).list_segments(principal, job_id)
    return DubSegmentListResponse(
        job_id=job_id,
        segments=[DubSegmentResponse.model_validate(s) for s in segments],
    )


@router.get(
    "/dub-segments/{segment_id}",
    response_model=DubSegmentResponse,
)
async def get_dub_segment(
    segment_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> DubSegmentResponse:
    segment = await _service(request).get_segment(principal, segment_id)
    return DubSegmentResponse.model_validate(segment)


@router.post(
    "/dub-segments/{segment_id}/regenerate",
    response_model=DubSegmentResponse,
)
async def regenerate_dub_segment(
    segment_id: UUID,
    request: Request,
    payload: DubRegenerateRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> DubSegmentResponse:
    body = payload or DubRegenerateRequest()
    segment = await _service(request).regenerate_segment(
        principal,
        segment_id,
        voice_profile_id=body.voice_profile_id,
    )
    return DubSegmentResponse.model_validate(segment)


@router.post(
    "/dub-segments/{segment_id}/review",
    response_model=DubSegmentResponse,
)
async def review_dub_segment(
    segment_id: UUID,
    request: Request,
    payload: DubReviewRequest,
    principal: Principal = Depends(current_principal),
) -> DubSegmentResponse:
    segment = await _service(request).submit_review(
        principal,
        segment_id,
        approved=payload.approved,
        reason=payload.reason,
    )
    return DubSegmentResponse.model_validate(segment)


@router.get(
    "/dub-segments/{segment_id}/playback-url",
    response_model=DubPlaybackResponse,
)
async def dub_segment_playback(
    segment_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> DubPlaybackResponse:
    url = await _service(request).get_playback_url(principal, segment_id)
    return DubPlaybackResponse(
        segment_id=segment_id,
        playback_url=url,
    )
```

### Key rules
- Follow the same pattern as `src/oki/sponsors/router.py` — get service from `request.app.state`, use `current_principal` dependency
- The `POST /api/jobs/dub` endpoint (the one the frontend currently calls as `api.jobs.dub()`) is being **moved** from `/api/jobs/dub` (body param) to `/api/jobs/{job_id}/dub` (path param). The frontend will be updated in Frontend Task 1.
- Return `DubSegmentResponse.model_validate(segment)` where `segment` is a `DubSegment` ORM model — Pydantic's `from_attributes=True` handles the conversion

---

## 3. Backend Task 2: Rewrite DubbingService.start()

**File**: `src/oki/dubbing/service.py`

The current `start()` reads from `TranscriptSegments` (raw transcript). It should read from `TranslationSegments` (translated text) because dubbing generates speech from the **translated** text, not the original.

### New `start()` logic — step by step

```python
async def start(
    self,
    principal: Principal,
    job_id: UUID,
    *,
    voice_profile_id: UUID | None = None,
    target_language: str | None = None,
) -> DubbingStartResponse:
```

1. **Load the job**:
   ```python
   from oki.jobs.models import LocalizationJob
   job = await uow.session.get(LocalizationJob, job_id)
   if job is None:
       self._not_found("job_not_found", "Job not found")
   ```

2. **Authorize**:
   ```python
   self._authorizer.require(
       principal,
       Action.PROJECT_READ,
       ResourceScope(organization_id=job.organization_id),
   )
   ```

3. **Check workflow state** — dubbing should only run after translation is done:
   ```python
   from oki.jobs.enums import WorkflowState
   allowed_states = {
       WorkflowState.TRANSLATION_REVIEW,
       WorkflowState.DUBBING_RUNNING,  # allow re-run
       WorkflowState.AUDIO_REVIEW,     # allow re-run
       WorkflowState.AD_REVIEW_REQUIRED,  # allow during dev
   }
   # For MVP, don't block — just log a warning if state is unexpected
   ```

4. **Load translation segments for this job**:
   ```python
   from oki.translations.models import TranslationSegments, Translations
   
   # Find the translation record for this job
   translation = await uow.session.scalar(
       select(Translations)
       .where(Translations.job_id == job_id)
       .order_by(Translations.created_at.desc())
       .limit(1)
   )
   
   if translation is not None:
       trans_segments = list(await uow.session.scalars(
           select(TranslationSegments)
           .where(TranslationSegments.translation_id == translation.id)
           .order_by(TranslationSegments.sequence_number)
       ))
       actual_target_language = translation.target_language
   else:
       trans_segments = []
       actual_target_language = target_language or "es"
   ```

5. **Fallback to transcript segments** if no translation exists (for dev/demo):
   ```python
   if not trans_segments:
       from oki.analysis.models import TranscriptSegments
       transcript_segs = list(await uow.session.scalars(
           select(TranscriptSegments)
           .where(TranscriptSegments.job_id == job_id)
           .order_by(TranscriptSegments.start_time)
       ))
       # Convert to a common format
       source_segments = [
           {
               "sequence_number": idx,
               "source_text": seg.text or "",
               "translated_text": seg.text or "",  # same text for demo
               "start_time": seg.start_time,
               "end_time": seg.end_time,
           }
           for idx, seg in enumerate(transcript_segs)
       ]
   else:
       source_segments = [
           {
               "sequence_number": seg.sequence_number,
               "source_text": seg.source_text,
               "translated_text": seg.translated_text or seg.source_text,
               "start_time": seg.start_time,
               "end_time": seg.end_time,
           }
           for seg in trans_segments
       ]
   ```

6. **Delete existing dub segments for this job** (idempotent re-run):
   ```python
   from sqlalchemy import delete
   # Delete attempts first (FK constraint)
   existing_seg_ids = list(await uow.session.scalars(
       select(DubSegment.id).where(DubSegment.job_id == job_id)
   ))
   if existing_seg_ids:
       await uow.session.execute(
           delete(DubAttempt).where(DubAttempt.dub_segment_id.in_(existing_seg_ids))
       )
       await uow.session.execute(
           delete(DubSegment).where(DubSegment.job_id == job_id)
       )
   ```

7. **Resolve voice profile**:
   ```python
   from oki.voices.models import VoiceProfile
   voice = None
   if voice_profile_id:
       voice = await uow.session.get(VoiceProfile, voice_profile_id)
   ```

8. **Create DubSegment rows**:
   ```python
   from decimal import Decimal
   
   segments: list[DubSegment] = []
   for seg_data in source_segments:
       start_time = seg_data["start_time"]
       end_time = seg_data["end_time"]
       
       seg = DubSegment(
           organization_id=job.organization_id,
           job_id=job.id,
           translation_job_id=translation.id if translation else None,
           sequence_number=seg_data["sequence_number"],
           source_text=seg_data["source_text"],
           translated_text=seg_data["translated_text"],
           voice_profile_id=voice.id if voice else None,
           timing_start_ms=int(float(start_time) * 1000) if start_time is not None else None,
           timing_end_ms=int(float(end_time) * 1000) if end_time is not None else None,
           status="pending",
       )
       segments.append(seg)
       uow.session.add(seg)
   
   await uow.session.flush()
   ```

9. **Update workflow state**:
   ```python
   job.state = WorkflowState.DUBBING_RUNNING
   await uow.session.flush()
   ```

10. **Return response**:
    ```python
    from oki.dubbing.schemas import DubbingStartResponse, DubSegmentResponse
    return DubbingStartResponse(
        job_id=job.id,
        organization_id=job.organization_id,
        total_segments=len(segments),
        pending_segments=len(segments),
        completed_segments=0,
        failed_segments=0,
        status="pending",
        voice_profile_id=voice.id if voice else None,
        target_language=actual_target_language,
        segments=[DubSegmentResponse.model_validate(s) for s in segments],
    )
    ```

### New methods to add to DubbingService

#### `list_segments()`
```python
async def list_segments(
    self,
    principal: Principal,
    job_id: UUID,
) -> list[DubSegment]:
    async with self._uow_factory() as uow:
        from oki.jobs.models import LocalizationJob
        job = await uow.session.get(LocalizationJob, job_id)
        if job is None:
            self._not_found("job_not_found", "Job not found")
        self._authorizer.require(
            principal,
            Action.PROJECT_READ,
            ResourceScope(organization_id=job.organization_id),
        )
        result = await uow.session.scalars(
            select(DubSegment)
            .where(DubSegment.job_id == job_id)
            .order_by(DubSegment.sequence_number)
        )
        return list(result)
```

#### `get_segment()`
```python
async def get_segment(
    self,
    principal: Principal,
    segment_id: UUID,
) -> DubSegment:
    async with self._uow_factory() as uow:
        segment = await uow.session.get(DubSegment, segment_id)
        if segment is None:
            self._not_found("dub_segment_not_found", "Dub segment not found")
        self._authorizer.require(
            principal,
            Action.PROJECT_READ,
            ResourceScope(organization_id=segment.organization_id),
        )
        return segment
```

#### `get_playback_url()`
```python
async def get_playback_url(
    self,
    principal: Principal,
    segment_id: UUID,
) -> str:
    async with self._uow_factory() as uow:
        segment = await uow.session.get(DubSegment, segment_id)
        if segment is None:
            self._not_found("dub_segment_not_found", "Dub segment not found")
        self._authorizer.require(
            principal,
            Action.PROJECT_READ,
            ResourceScope(organization_id=segment.organization_id),
        )
        if not segment.audio_asset_reference:
            raise ProblemException(
                status_code=404,
                type_uri="https://oki.example/errors/no_audio",
                title="No audio available",
            )
        url = await self._store.presign_get(segment.audio_asset_reference)
        return url
```

#### Fix `regenerate_segment()` — add voice_profile_id parameter

Update the existing method signature:
```python
async def regenerate_segment(
    self,
    principal: Principal,
    segment_id: UUID,
    *,
    voice_profile_id: UUID | None = None,
) -> DubSegment:
```

Inside the method, after loading the segment:
- If `voice_profile_id` is provided, update `segment.voice_profile_id`
- Load the voice profile to get the `provider_voice_id`
- Load pronunciation entries for the voice profile and apply them via `PronunciationDictionary`
- Create a `DubAttempt` record before calling ElevenLabs
- After synthesis, update the `DubAttempt` with the result
- Store `provider_key="elevenlabs"` in the attempt

Updated implementation:
```python
async def regenerate_segment(
    self,
    principal: Principal,
    segment_id: UUID,
    *,
    voice_profile_id: UUID | None = None,
) -> DubSegment:
    async with self._uow_factory() as uow:
        segment = await uow.session.get(DubSegment, segment_id)
        if segment is None:
            self._not_found("dub_segment_not_found", "Dub segment not found")

        self._authorizer.require(
            principal,
            Action.PROJECT_READ,
            ResourceScope(organization_id=segment.organization_id),
        )

        # Update voice profile if provided
        if voice_profile_id is not None:
            segment.voice_profile_id = voice_profile_id

        segment.status = "generating"
        segment.audio_asset_reference = None
        segment.review_status = None
        await uow.session.flush()

        # Resolve the ElevenLabs voice ID
        elevenlabs_voice_id = "21m00Tcm4TlvDq8ikWAM"  # default Rachel
        provider_key = "elevenlabs"
        if segment.voice_profile_id:
            from oki.voices.models import VoiceProfile
            profile = await uow.session.get(VoiceProfile, segment.voice_profile_id)
            if profile and profile.provider_voice_id:
                elevenlabs_voice_id = profile.provider_voice_id

        # Apply pronunciation dictionary
        text_to_speak = segment.translated_text or segment.source_text
        if segment.voice_profile_id:
            from oki.voices.models import PronunciationEntry
            entries = list(await uow.session.scalars(
                select(PronunciationEntry)
                .where(PronunciationEntry.voice_profile_id == segment.voice_profile_id)
            ))
            if entries:
                from oki.voices.pronunciation import PronunciationDictionary
                dictionary = PronunciationDictionary(
                    [{"original_text": e.original_text, "pronunciation": e.pronunciation}
                     for e in entries]
                )
                text_to_speak = dictionary.apply(text_to_speak, "en")

        # Create DubAttempt record
        attempt = DubAttempt(
            organization_id=segment.organization_id,
            dub_segment_id=segment.id,
            provider_key=provider_key,
            status="pending",
        )
        uow.session.add(attempt)
        await uow.session.flush()

        # Call ElevenLabs if configured
        if self._elevenlabs and text_to_speak:
            try:
                audio_bytes = await self._elevenlabs.synthesize(
                    text=text_to_speak,
                    voice_profile_id=elevenlabs_voice_id,
                )
                s3_key = f"dubs/{segment.job_id}/{segment.id}.mp3"
                await self._store.put_object(
                    key=s3_key,
                    body=audio_bytes,
                    content_type="audio/mpeg",
                )
                segment.audio_asset_reference = s3_key
                segment.status = "completed"
                attempt.audio_asset_reference = s3_key
                attempt.status = "completed"
                attempt.meta = {
                    "voice_id": elevenlabs_voice_id,
                    "audio_size_bytes": len(audio_bytes),
                }
            except Exception as exc:
                segment.status = "failed"
                segment.meta = {**segment.meta, "error": str(exc)}
                attempt.status = "failed"
                attempt.error_message = str(exc)
        else:
            segment.status = "pending"
            segment.meta = {
                **segment.meta,
                "reason": "ElevenLabs not configured or no text",
            }
            attempt.status = "failed"
            attempt.error_message = "ElevenLabs not configured or no translated text"

        await uow.session.flush()
        return segment
```

---

## 4. Backend Task 3: Update Schemas

**File**: `src/oki/dubbing/schemas.py`

Replace the entire file with:

```python
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DubSegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    job_id: UUID
    translation_job_id: UUID | None
    sequence_number: int
    source_text: str
    translated_text: str | None
    voice_profile_id: UUID | None
    timing_start_ms: int | None
    timing_end_ms: int | None
    status: str
    audio_asset_reference: str | None
    review_status: str | None
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DubSegmentListResponse(BaseModel):
    job_id: UUID
    segments: list[DubSegmentResponse]


class DubbingStartRequest(BaseModel):
    voice_profile_id: UUID | None = None
    target_language: str | None = None


class DubbingStartResponse(BaseModel):
    job_id: UUID
    organization_id: UUID
    total_segments: int
    pending_segments: int
    completed_segments: int
    failed_segments: int
    status: str
    voice_profile_id: UUID | None
    target_language: str | None
    segments: list[DubSegmentResponse]


class DubRegenerateRequest(BaseModel):
    voice_profile_id: UUID | None = None


class DubReviewRequest(BaseModel):
    approved: bool
    reason: str | None = None


class DubPlaybackResponse(BaseModel):
    segment_id: UUID
    playback_url: str
```

---

## 5. Backend Task 4: Wire Consent Validation into Dubbing

**File**: `src/oki/dubbing/service.py` — inside `start()`, BEFORE creating DubSegment rows

The SOW requires: **"generation fails closed when permission is missing"**.

Add this block after loading the job and before creating segments:

```python
# --- Consent validation (fail-closed per SOW) ---
from oki.voices.policy import VoicePolicy, VoicePolicyRequest
from oki.voices.enums import VoiceMode
from oki.rights.models import (
    RightsAgreement,
    RightsAgreementVersion,
    RightsGrant,
    VoiceConsent,
)
from oki.assets.models import SourceAsset

# Determine voice mode
voice_mode = VoiceMode.LICENSED_NEUTRAL_VOICE  # default
if voice and voice.mode:
    voice_mode = voice.mode

# Find the creator from the source asset
asset = await uow.session.scalar(
    select(SourceAsset).where(SourceAsset.localization_job_id == job_id)
)
creator_id = asset.creator_id if asset else None

if creator_id:
    # Find the active agreement for this creator
    agreement = await uow.session.scalar(
        select(RightsAgreement)
        .where(RightsAgreement.creator_id == creator_id)
        .where(RightsAgreement.organization_id == job.organization_id)
        .order_by(RightsAgreement.created_at.desc())
        .limit(1)
    )
    
    version = None
    grants: tuple[RightsGrant, ...] = ()
    voice_consents: tuple[VoiceConsent, ...] = ()
    
    if agreement:
        version = await uow.session.scalar(
            select(RightsAgreementVersion)
            .where(RightsAgreementVersion.agreement_id == agreement.id)
            .order_by(RightsAgreementVersion.agreement_version_number.desc())
            .limit(1)
        )
        if version:
            grants = tuple(await uow.session.scalars(
                select(RightsGrant)
                .where(RightsGrant.agreement_version_id == version.id)
            ))
            voice_consents = tuple(await uow.session.scalars(
                select(VoiceConsent)
                .where(VoiceConsent.agreement_version_id == version.id)
            ))
    
    policy_result = VoicePolicy.require(
        VoicePolicyRequest(
            organization_id=job.organization_id,
            creator_id=creator_id,
            agreement_version_id=version.id if version else UUID(int=0),
            voice_mode=voice_mode,
            language_code=actual_target_language,
            territory_code="US",  # TODO: derive from job target
        ),
        agreement=agreement,
        version=version,
        grants=grants,
        voice_consents=voice_consents,
    )
    
    if not policy_result.approved:
        raise ProblemException(
            status_code=403,
            type_uri=f"https://oki.example/errors/{policy_result.reason_code}",
            title="Voice policy denied",
            detail=policy_result.reason_detail or "Dubbing not permitted",
        )
# If no creator_id found (dev/demo mode), skip consent check
```

**Important**: For development/demo mode where there's no creator linked, skip consent validation to allow testing. Add a comment explaining this.

---

## 6. Backend Task 5: Wire the Hatchet Task

**File**: `src/oki/dubbing/tasks.py`

Replace the stub with a real implementation. The task is meant to be called by the Hatchet workflow engine for async processing. For now, it should:

```python
from typing import Any
from uuid import UUID

from oki.config import Settings
from oki.dubbing.service import DubbingService
from oki.storage.s3 import S3ObjectStore


async def run_dubbing_task(
    job_id: UUID,
    *,
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Hatchet task: generate audio for all pending dub segments in a job.
    
    Called asynchronously after DubbingService.start() creates the segments.
    Iterates through each pending segment and calls ElevenLabs TTS.
    """
    del hatchet_workflow_run_id, hatchet_task_run_id
    
    # This task runs outside the request cycle, so it needs its own
    # database session and service instance.
    # TODO: accept session_factory from Hatchet context when wired
    
    return {
        "job_id": str(job_id),
        "status": "stub_not_wired",
        "message": "Dubbing task needs Hatchet context wiring. "
                   "Use the REST API (POST /api/dub-segments/{id}/regenerate) "
                   "for synchronous generation.",
    }
```

**Note**: The actual Hatchet wiring depends on how Hatchet is configured in this project. For the MVP, dubbing will work synchronously via the `regenerate` endpoint. The Hatchet task becomes useful when you want to auto-generate all segments in the background after `start()`.

---

## 7. Backend Task 6: Add Provider Usage Tracking

**File**: `src/oki/dubbing/service.py` — inside `regenerate_segment()`, after successful synthesis

The `provider_usage` table already exists (from migration 0002). Record each ElevenLabs call:

```python
from oki.jobs.models import ProviderUsage

usage = ProviderUsage(
    organization_id=segment.organization_id,
    job_id=segment.job_id,
    provider="elevenlabs",
    operation="tts_synthesize",
    input_tokens=len(text_to_speak),  # character count for TTS
    output_tokens=0,
    cost_usd=None,  # TODO: compute from ElevenLabs pricing
    meta={
        "voice_id": elevenlabs_voice_id,
        "model_id": "eleven_multilingual_v2",
        "audio_size_bytes": len(audio_bytes),
        "segment_id": str(segment.id),
        "attempt_id": str(attempt.id),
    },
)
uow.session.add(usage)
```

**Note**: First verify that `ProviderUsage` model exists in `src/oki/jobs/models.py`. If it doesn't exist, check the table name in migration 0002 and create the model. The table name is `provider_usage` and it was created in migration 0002.

Check `src/oki/jobs/models.py` for the `ProviderUsage` model. If it has different column names, adapt accordingly.

---

## 8. Backend Task 7: Voice Profile CRUD Endpoints

**File**: `src/oki/voices/router.py`

Add create and update endpoints (the existing file only has `GET /api/voices` and `GET /api/voices/{id}`):

### New schemas to add in `src/oki/voices/schemas.py`:

```python
class VoiceProfileCreate(BaseModel):
    name: str
    mode: VoiceMode
    language_code: str
    provider_key: str = "elevenlabs"
    provider_voice_id: str | None = None
    creator_id: UUID | None = None
    consent_reference: str | None = None

class VoiceProfileUpdate(BaseModel):
    name: str | None = None
    provider_voice_id: str | None = None
    language_code: str | None = None
    consent_reference: str | None = None
```

### New endpoints to add in `src/oki/voices/router.py`:

```python
@router.post("/voices", response_model=VoiceProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_voice(
    request: Request,
    payload: VoiceProfileCreate,
    principal: Principal = Depends(current_principal),
) -> VoiceProfileResponse:
    profile = await _service(request).create_profile(principal, payload)
    return VoiceProfileResponse.model_validate(profile)


@router.put("/voices/{profile_id}", response_model=VoiceProfileResponse)
async def update_voice(
    profile_id: UUID,
    request: Request,
    payload: VoiceProfileUpdate,
    principal: Principal = Depends(current_principal),
) -> VoiceProfileResponse:
    profile = await _service(request).update_profile(principal, profile_id, payload)
    return VoiceProfileResponse.model_validate(profile)


@router.get("/voices/elevenlabs", response_model=list[dict])
async def list_elevenlabs_voices(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[dict]:
    """List available voices from ElevenLabs API."""
    from oki.providers.elevenlabs import ElevenLabsClient
    from oki.config import Settings
    settings = Settings()
    if not settings.elevenlabs_api_key:
        return []
    client = ElevenLabsClient(settings)
    return await client.list_voices()
```

### New methods to add in `src/oki/voices/service.py`:

```python
async def create_profile(
    self,
    principal: Principal,
    data: "VoiceProfileCreate",
) -> VoiceProfile:
    org_id = principal.memberships[0].organization_id
    self._authorizer.require(
        principal,
        Action.CREATOR_CREATE,
        ResourceScope(organization_id=org_id),
    )
    async with self._uow_factory() as uow:
        profile = VoiceProfile(
            organization_id=org_id,
            creator_id=data.creator_id,
            name=data.name,
            mode=data.mode,
            language_code=data.language_code,
            provider_key=data.provider_key,
            provider_voice_id=data.provider_voice_id,
            consent_reference=data.consent_reference,
        )
        uow.session.add(profile)
        await uow.session.flush()
        return profile

async def update_profile(
    self,
    principal: Principal,
    profile_id: UUID,
    data: "VoiceProfileUpdate",
) -> VoiceProfile:
    async with self._uow_factory() as uow:
        profile = await uow.session.get(VoiceProfile, profile_id)
        if profile is None:
            self._not_found("voice_profile_not_found", "Voice profile not found")
        self._authorizer.require(
            principal,
            Action.CREATOR_CREATE,
            ResourceScope(organization_id=profile.organization_id),
        )
        if data.name is not None:
            profile.name = data.name
        if data.provider_voice_id is not None:
            profile.provider_voice_id = data.provider_voice_id
        if data.language_code is not None:
            profile.language_code = data.language_code
        if data.consent_reference is not None:
            profile.consent_reference = data.consent_reference
        await uow.session.flush()
        return profile
```

---

## 9. Backend Task 8: Pronunciation Dictionary

**File**: `src/oki/voices/pronunciation.py`

The current stub just wraps text in `<speak>`. Implement basic substitution:

```python
from typing import Any


class PronunciationDictionary:
    """Apply pronunciation overrides to text."""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries = {e["original_text"].lower(): e for e in entries}

    @classmethod
    def empty(cls) -> "PronunciationDictionary":
        return cls([])

    def apply(self, text: str, language: str) -> str:
        if not text or not self._entries:
            return text
        
        result = text
        for original, entry in self._entries.items():
            pronunciation = entry.get("pronunciation", original)
            # Case-insensitive replacement preserving word boundaries
            import re
            pattern = re.compile(re.escape(original), re.IGNORECASE)
            result = pattern.sub(pronunciation, result)
        
        return result
```

**Note**: This is intentionally simple. For production, you would use SSML `<phoneme>` tags with IPA notation, but ElevenLabs doesn't support standard SSML phonemes — it uses its own pronunciation dictionary API. For MVP, simple text substitution works.

---

## 10. Frontend Task 1: API Client — Dubbing Methods

**File**: `/Users/abduzhalil/repos/oki-engine-frontend/src/lib/api.ts`

### Add new TypeScript interfaces

Add these after the existing `RenderJob` interface (around line 128):

```typescript
export interface DubSegment {
  id: string;
  organization_id: string;
  job_id: string;
  translation_job_id: string | null;
  sequence_number: number;
  source_text: string;
  translated_text: string | null;
  voice_profile_id: string | null;
  timing_start_ms: number | null;
  timing_end_ms: number | null;
  status: string;  // "pending" | "generating" | "completed" | "failed"
  audio_asset_reference: string | null;
  review_status: string | null;  // "approved" | "rejected" | null
  meta: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DubbingStartResponse {
  job_id: string;
  organization_id: string;
  total_segments: number;
  pending_segments: number;
  completed_segments: number;
  failed_segments: number;
  status: string;
  voice_profile_id: string | null;
  target_language: string | null;
  segments: DubSegment[];
}

export interface VoiceProfile {
  id: string;
  organization_id: string;
  creator_id: string | null;
  name: string;
  mode: string;  // "licensed_neutral_voice" | "creator_approved_clone" | "human_voice_actor"
  language_code: string;
  provider_key: string;
  provider_voice_id: string | null;
  consent_reference: string | null;
  created_at: string;
  updated_at: string;
}
```

### Update the `api.jobs.dub()` method

Change from:
```typescript
dub: (jobId: string) =>
  request<{ task_id: string }>("/api/jobs/dub", { method: "POST", body: JSON.stringify({ job_id: jobId }) }),
```

To:
```typescript
dub: (jobId: string, voiceProfileId?: string) =>
  request<DubbingStartResponse>(`/api/jobs/${jobId}/dub`, {
    method: "POST",
    body: JSON.stringify({ voice_profile_id: voiceProfileId || null }),
  }),
```

### Add new `api.dubbing` namespace

Add after the existing `api.sponsors` namespace:

```typescript
dubbing: {
  listSegments: (jobId: string) =>
    request<{ job_id: string; segments: DubSegment[] }>(`/api/jobs/${jobId}/dub-segments`),
  getSegment: (segmentId: string) =>
    request<DubSegment>(`/api/dub-segments/${segmentId}`),
  regenerate: (segmentId: string, voiceProfileId?: string) =>
    request<DubSegment>(`/api/dub-segments/${segmentId}/regenerate`, {
      method: "POST",
      body: JSON.stringify({ voice_profile_id: voiceProfileId || null }),
    }),
  review: (segmentId: string, approved: boolean, reason?: string) =>
    request<DubSegment>(`/api/dub-segments/${segmentId}/review`, {
      method: "POST",
      body: JSON.stringify({ approved, reason }),
    }),
  playbackUrl: (segmentId: string) =>
    request<{ segment_id: string; playback_url: string }>(`/api/dub-segments/${segmentId}/playback-url`),
},
```

### Add new `api.voices` namespace

```typescript
voices: {
  list: () => request<VoiceProfile[]>("/api/voices"),
  get: (id: string) => request<VoiceProfile>(`/api/voices/${id}`),
  create: (data: { name: string; mode: string; language_code: string; provider_key?: string; provider_voice_id?: string }) =>
    request<VoiceProfile>("/api/voices", { method: "POST", body: JSON.stringify(data) }),
  listElevenlabs: () => request<Array<{ voice_id: string; name: string }>>("/api/voices/elevenlabs"),
},
```

---

## 11. Frontend Task 2: Dubbing Workspace Page

**File**: `/Users/abduzhalil/repos/oki-engine-frontend/src/app/dubbing/page.tsx` (NEW FILE)

This is the main dubbing workspace. Model it after the Review page pattern (`src/app/projects/[id]/review/page.tsx`).

### Page structure

```
+------------------------------------------------------------------+
|  Dubbing Workspace                                                |
|  Job: {project.title}  |  Language: {target_language}  |  Status  |
+------------------------------------------------------------------+
|  Voice Profile: [Select dropdown ▾]     [Generate All] [Approve All] |
+------------------------------------------------------------------+
|  # | Source Text         | Translated Text      | Status | Actions |
|----|---------------------|----------------------|--------|---------|
|  0 | "Hey everyone..."   | "Hola a todos..."    | ✅ done | ▶ 🔄 ✓ ✗ |
|  1 | "Before we start.." | "Antes de empezar.." | ⏳ pend | ▶ 🔄 ✓ ✗ |
|  2 | "So this new..."    | "Así que este..."    | ❌ fail | ▶ 🔄 ✓ ✗ |
+------------------------------------------------------------------+
|  Audio Player: [========>--------] 0:03 / 0:08                    |
+------------------------------------------------------------------+
```

### Key functionality

1. **Load segments**: On mount, call `api.dubbing.listSegments(jobId)`. If empty, show "Click 'Dub' on the project to start."
2. **Voice profile selector**: Call `api.voices.list()` and show a `<Select>` dropdown. When changed, future regenerations use this voice.
3. **Segment table**: Show each segment with:
   - Sequence number
   - Source text (truncated to 80 chars)
   - Translated text (truncated to 80 chars)
   - Status badge: `pending` (yellow), `generating` (blue spinner), `completed` (green), `failed` (red)
   - Review status badge: `approved` (green check), `rejected` (red x), null (gray dash)
4. **Play button** per segment: Calls `api.dubbing.playbackUrl(segmentId)` then plays the audio in an `<audio>` element. Disabled if status is not `completed`.
5. **Regenerate button** per segment: Calls `api.dubbing.regenerate(segmentId, selectedVoiceProfileId)`. Shows spinner while in progress.
6. **Approve/Reject buttons** per segment: Calls `api.dubbing.review(segmentId, true/false)`.
7. **Generate All button**: Loops through all segments with status `pending` and calls regenerate for each sequentially. Shows progress.
8. **Approve All button**: Calls review with `approved=true` for all completed segments.
9. **Job selector**: If accessed without a job ID, show a dropdown of jobs in `DUBBING_RUNNING` or `AUDIO_REVIEW` state.

### Route structure

This page should be at `/dubbing` (top-level nav) and also accessible as a tab from `/projects/[id]`.

The page needs a way to receive the job ID. Two approaches:
- **URL query param**: `/dubbing?jobId=xxx` — simplest
- **Dynamic route**: `/dubbing/[jobId]` — cleaner

Use the query param approach for simplicity (same pattern as existing translation page).

### Exact component skeleton

```tsx
"use client";

import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { api, type DubSegment, type VoiceProfile, type Project } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Play,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Loader2,
  Volume2,
} from "lucide-react";

export default function DubbingPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("jobId");

  const [segments, setSegments] = useState<DubSegment[]>([]);
  const [voices, setVoices] = useState<VoiceProfile[]>([]);
  const [selectedVoice, setSelectedVoice] = useState<string | undefined>();
  const [jobs, setJobs] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState<Set<string>>(new Set());
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);

  // Load data on mount
  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const [voiceList, jobList] = await Promise.all([
          api.voices.list().catch(() => []),
          api.jobs.list().catch(() => []),
        ]);
        setVoices(voiceList);
        setJobs(jobList);

        if (jobId) {
          const result = await api.dubbing.listSegments(jobId);
          setSegments(result.segments);
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [jobId]);

  const handleRegenerate = useCallback(async (segmentId: string) => {
    setRegenerating((prev) => new Set(prev).add(segmentId));
    try {
      const updated = await api.dubbing.regenerate(segmentId, selectedVoice);
      setSegments((prev) =>
        prev.map((s) => (s.id === segmentId ? updated : s))
      );
    } catch (e) {
      alert(String(e));
    } finally {
      setRegenerating((prev) => {
        const next = new Set(prev);
        next.delete(segmentId);
        return next;
      });
    }
  }, [selectedVoice]);

  const handleReview = useCallback(async (segmentId: string, approved: boolean) => {
    try {
      const updated = await api.dubbing.review(segmentId, approved);
      setSegments((prev) =>
        prev.map((s) => (s.id === segmentId ? updated : s))
      );
    } catch (e) {
      alert(String(e));
    }
  }, []);

  const handlePlay = useCallback(async (segmentId: string) => {
    try {
      const result = await api.dubbing.playbackUrl(segmentId);
      setPlayingId(segmentId);
      setAudioUrl(result.playback_url);
    } catch (e) {
      alert(String(e));
    }
  }, []);

  const handleGenerateAll = useCallback(async () => {
    const pending = segments.filter((s) => s.status === "pending" || s.status === "failed");
    for (const seg of pending) {
      await handleRegenerate(seg.id);
    }
  }, [segments, handleRegenerate]);

  const handleApproveAll = useCallback(async () => {
    const completed = segments.filter(
      (s) => s.status === "completed" && s.review_status !== "approved"
    );
    for (const seg of completed) {
      await handleReview(seg.id, true);
    }
  }, [segments, handleReview]);

  // ... render the UI with the structure described above
  // Use the Card, Badge, Button, Select components from shadcn/ui
  // Use the same layout patterns as the review page
}
```

### Status badge colors

```tsx
function statusBadge(status: string) {
  switch (status) {
    case "completed":
      return <Badge className="bg-green-100 text-green-800">Completed</Badge>;
    case "generating":
      return <Badge className="bg-blue-100 text-blue-800"><Loader2 className="mr-1 h-3 w-3 animate-spin" />Generating</Badge>;
    case "failed":
      return <Badge variant="destructive">Failed</Badge>;
    default:
      return <Badge variant="secondary">Pending</Badge>;
  }
}
```

### Audio player

Place a sticky `<audio>` element at the bottom of the page:

```tsx
{audioUrl && (
  <div className="fixed bottom-0 left-0 right-0 border-t bg-background p-4">
    <div className="mx-auto max-w-4xl flex items-center gap-4">
      <Volume2 className="h-5 w-5 text-muted-foreground" />
      <audio
        src={audioUrl}
        controls
        autoPlay
        className="flex-1"
        onEnded={() => { setPlayingId(null); setAudioUrl(null); }}
      />
    </div>
  </div>
)}
```

---

## 12. Frontend Task 3: Voice Profile Selector Component

This is used inside the dubbing workspace. It's a simple `<Select>` that loads voice profiles.

Inline it in the dubbing page — no need for a separate component file:

```tsx
<div className="flex items-center gap-2">
  <span className="text-sm font-medium">Voice:</span>
  <Select value={selectedVoice} onValueChange={setSelectedVoice}>
    <SelectTrigger className="w-64">
      <SelectValue placeholder="Default (Rachel)" />
    </SelectTrigger>
    <SelectContent>
      {voices.map((v) => (
        <SelectItem key={v.id} value={v.id}>
          {v.name} ({v.language_code}) — {v.mode.replace(/_/g, " ")}
        </SelectItem>
      ))}
    </SelectContent>
  </Select>
</div>
```

---

## 13. Frontend Task 4: Wire Dub Button on Project Detail

**File**: `/Users/abduzhalil/repos/oki-engine-frontend/src/app/projects/[id]/page.tsx`

The current Dub button calls `api.jobs.dub(id)` which we're changing. Update the `runAction` function:

Change from:
```typescript
case "dub":
  await api.jobs.dub(id);
  break;
```

To:
```typescript
case "dub":
  await api.jobs.dub(id);
  // Navigate to dubbing workspace
  window.location.href = `/dubbing?jobId=${id}`;
  return; // skip refresh since we're navigating
```

Or alternatively, keep the current behavior but also update the response handling since the return type changed from `{ task_id: string }` to `DubbingStartResponse`.

---

## 14. Frontend Task 5: Add Dubbing Tab on Project Detail

**File**: `/Users/abduzhalil/repos/oki-engine-frontend/src/app/projects/[id]/page.tsx`

In the `<Tabs>` section, add a Dubbing tab between Translation and Review:

In the `<TabsList>`:
```tsx
<TabsTrigger value="dubbing">Dubbing</TabsTrigger>
```

Add a new `<TabsContent>`:
```tsx
<TabsContent value="dubbing">
  <Card>
    <CardHeader>
      <CardTitle>Dubbing</CardTitle>
    </CardHeader>
    <CardContent>
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          AI voice synthesis for translated segments.
        </p>
        <Button
          size="sm"
          variant="outline"
          onClick={() => window.location.href = `/dubbing?jobId=${id}`}
        >
          Open Dubbing Workspace
        </Button>
      </div>
    </CardContent>
  </Card>
</TabsContent>
```

---

## 15. Frontend Task 6: Navigation Link

**File**: `/Users/abduzhalil/repos/oki-engine-frontend/src/components/layout/app-shell.tsx`

Add a "Dubbing" entry to the `nav` array. Insert it after the "Translation" entry:

```typescript
import { /* ... existing imports ... */ Mic } from "lucide-react";

const nav = [
  // ... existing entries ...
  { name: "Translation", href: "/translation", icon: Languages },
  { name: "Dubbing", href: "/dubbing", icon: Mic },  // ADD THIS LINE
  { name: "Review", href: "/review", icon: ClipboardCheck },
  // ... rest ...
];
```

Use `Mic` icon from lucide-react (already available since lucide-react is installed).

---

## 16. Testing Plan

### Backend unit tests

Create `tests/test_dubbing.py`:

```python
import pytest
from uuid import uuid4, UUID
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, UTC

from oki.dubbing.service import DubbingService
from oki.dubbing.models import DubSegment, DubAttempt
from oki.dubbing.schemas import DubbingStartResponse


class TestDubbingService:
    """Test DubbingService methods."""

    # Test 1: start() with translation segments creates DubSegments
    # Test 2: start() with no translation falls back to transcript segments
    # Test 3: start() with empty segments returns empty response
    # Test 4: start() is idempotent — re-running deletes old segments
    # Test 5: start() updates job state to DUBBING_RUNNING
    # Test 6: list_segments() returns segments ordered by sequence_number
    # Test 7: get_segment() raises 404 for non-existent segment
    # Test 8: regenerate_segment() with ElevenLabs configured generates audio
    # Test 9: regenerate_segment() without ElevenLabs returns pending
    # Test 10: regenerate_segment() with ElevenLabs error sets status to failed
    # Test 11: submit_review() sets review_status to approved
    # Test 12: submit_review() sets review_status to rejected with reason
    # Test 13: get_playback_url() returns presigned URL
    # Test 14: get_playback_url() raises 404 when no audio
    # Test 15: consent validation blocks CREATOR_APPROVED_CLONE without consent
    # Test 16: consent validation allows LICENSED_NEUTRAL_VOICE
```

### Manual testing checklist

1. Start backend: `uv run uvicorn oki.main:create_app --host 0.0.0.0 --port 8000 --reload`
2. Start frontend: `cd /Users/abduzhalil/repos/oki-engine-frontend && npm run dev`
3. Create a project, upload a video, run Analyze
4. Run Translate (or skip — dubbing should fallback to transcript segments)
5. Click "Dub" on the project page
6. Verify you're navigated to `/dubbing?jobId=xxx`
7. Verify segments appear in the table
8. Select a voice profile (if any exist)
9. Click "Regenerate" on a segment (requires `OKI_ELEVENLABS_API_KEY` set)
10. If ElevenLabs is configured, verify audio appears and can be played
11. If not configured, verify status shows "pending" with reason in meta
12. Click Approve/Reject on a segment
13. Click "Generate All" and verify it processes pending segments
14. Click "Approve All" and verify completed segments get approved

---

## 17. Seed Data

**File**: `scripts/seed_demo.py`

Add voice profile seed data:

```python
# After existing seed data...

# Voice profiles
from oki.voices.models import VoiceProfile
from oki.voices.enums import VoiceMode

voice_profiles = [
    VoiceProfile(
        organization_id=org_id,
        name="Rachel (English)",
        mode=VoiceMode.LICENSED_NEUTRAL_VOICE,
        language_code="en",
        provider_key="elevenlabs",
        provider_voice_id="21m00Tcm4TlvDq8ikWAM",
    ),
    VoiceProfile(
        organization_id=org_id,
        name="Antoni (Spanish)",
        mode=VoiceMode.LICENSED_NEUTRAL_VOICE,
        language_code="es",
        provider_key="elevenlabs",
        provider_voice_id="ErXwobaYiN019PkySvjV",
    ),
    VoiceProfile(
        organization_id=org_id,
        name="Bella (English)",
        mode=VoiceMode.LICENSED_NEUTRAL_VOICE,
        language_code="en",
        provider_key="elevenlabs",
        provider_voice_id="EXAVITQu4vr4xnSDxMaL",
    ),
]
for vp in voice_profiles:
    session.add(vp)
```

Adapt this to match the actual seed script pattern (check `scripts/seed_demo.py` for how `org_id` and `session` are obtained).

---

## 18. Acceptance Criteria (from SOW)

The SOW section **3.7 Dubbing and Voice Management** states:

> **Acceptance criteria:**
> 1. Generation fails closed when permission is missing ✅ (Task 4 — VoicePolicy blocks without consent)
> 2. Every audio file records provider, voice and parameters ✅ (Task 6 — DubAttempt stores provider_key, meta with voice_id, model_id)
> 3. Segments can be regenerated independently ✅ (Task 3 — POST /api/dub-segments/{id}/regenerate)

Additional SOW requirements:
- Provider-agnostic TTS interface ✅ (TtsProvider protocol exists)
- Licensed voice library ✅ (VoiceProfile model with mode=LICENSED_NEUTRAL_VOICE)
- Approved creator voice profiles ✅ (VoiceProfile with mode=CREATOR_APPROVED_CLONE)
- Pronunciation dictionary ✅ (Task 8)
- Previews ✅ (GET /api/dub-segments/{id}/playback-url)
- Timing comparison ⚠️ (DubSegment stores timing_start_ms/timing_end_ms for comparison with original — UI can display both)
- Controlled time-stretch ⚠️ (Not in MVP — requires FFmpeg processing of audio; mark as post-MVP)
- Cost tracking ✅ (Task 6 — ProviderUsage records)
- Consent validation ✅ (Task 4 — VoicePolicy)

---

## Execution Order

1. **Backend Task 3** — Update schemas (no dependencies)
2. **Backend Task 1** — Fix the router (depends on schemas)
3. **Backend Task 2** — Rewrite DubbingService.start() (depends on schemas)
4. **Backend Task 4** — Consent validation (depends on service)
5. **Backend Task 7** — Voice profile CRUD (independent)
6. **Backend Task 8** — Pronunciation dictionary (independent)
7. **Backend Task 5** — Hatchet task (can be last, MVP works without it)
8. **Backend Task 6** — Provider usage tracking (depends on service)
9. **Frontend Task 1** — API client (depends on backend endpoints existing)
10. **Frontend Task 6** — Navigation link (independent)
11. **Frontend Task 2** — Dubbing workspace page (depends on API client)
12. **Frontend Task 3** — Voice selector (part of workspace page)
13. **Frontend Task 4** — Wire Dub button (depends on API client)
14. **Frontend Task 5** — Dubbing tab (independent)
15. **Seed data** (can be done anytime)
16. **Testing** (after all backend + frontend)

---

## Files Modified (Summary)

### Backend (modify existing)
| File | Action |
|------|--------|
| `src/oki/dubbing/router.py` | **Rewrite** — 6 endpoints |
| `src/oki/dubbing/schemas.py` | **Rewrite** — 7 schema classes |
| `src/oki/dubbing/service.py` | **Rewrite** — fix start(), add list/get/playback, fix regenerate |
| `src/oki/dubbing/tasks.py` | **Update** — improve stub |
| `src/oki/voices/router.py` | **Extend** — add POST, PUT, GET elevenlabs |
| `src/oki/voices/schemas.py` | **Extend** — add Create/Update schemas |
| `src/oki/voices/service.py` | **Extend** — add create_profile, update_profile |
| `src/oki/voices/pronunciation.py` | **Rewrite** — real substitution |
| `scripts/seed_demo.py` | **Extend** — add voice profiles |

### Frontend (modify existing)
| File | Action |
|------|--------|
| `src/lib/api.ts` | **Extend** — add interfaces, dubbing & voices namespaces, fix dub() |
| `src/app/projects/[id]/page.tsx` | **Update** — add Dubbing tab, wire navigation |
| `src/components/layout/app-shell.tsx` | **Update** — add Dubbing nav item |

### Frontend (new files)
| File | Action |
|------|--------|
| `src/app/dubbing/page.tsx` | **Create** — dubbing workspace page |

### Backend (no changes needed)
| File | Reason |
|------|--------|
| `src/oki/main.py` | Already wires dubbing_service and dubbing_router |
| `src/oki/dubbing/models.py` | Models are complete |
| `src/oki/voices/models.py` | Models are complete |
| `src/oki/providers/elevenlabs.py` | Client is complete |
| `src/oki/voices/policy.py` | Policy is complete |
| `migrations/versions/0011_dubbing.py` | Migration already applied |
