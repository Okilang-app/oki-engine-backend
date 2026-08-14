# Oki Backend Stage 4 Approval and Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind internal and creator approval to exact package versions, connect authorized YouTube channels securely, and enforce private-first upload plus separate human public release.

**Architecture:** Review decisions bind to a canonical package-version hash and are invalidated by material changes. YouTube tokens are encrypted application data; publication uses a guarded state machine and idempotent platform operations.

**Tech Stack:** Prior stages plus cryptography envelope encryption, Google OAuth 2, YouTube Data API resumable uploads, HTTPX/Google client contract tests.

**Spec:** `docs/superpowers/specs/2026-08-14-oki-localization-backend-design.md`

## Global Constraints

- A material package change invalidates every approval bound to the prior version.
- Creator approval is mandatory when the agreement says so.
- Upload occurs only to a channel allowed by agreement and OAuth connection.
- Initial visibility is always private.
- Platform, disclosure, and metadata checks precede separate employee public-release approval.
- No automatic disputes, counter-notices, circumvention, or re-upload after takedown.

---

### Task 1: Internal and creator review packages, comments, and version decisions

**Files:**
- Create: `src/oki/reviews/enums.py`
- Create: `src/oki/reviews/models.py`
- Create: `src/oki/reviews/schemas.py`
- Create: `src/oki/reviews/versioning.py`
- Create: `src/oki/reviews/service.py`
- Create: `src/oki/reviews/router.py`
- Create: `migrations/versions/0015_reviews.py`
- Create: `tests/unit/reviews/test_package_hash.py`
- Create: `tests/integration/reviews/test_approval_invalidation.py`
- Create: `tests/integration/reviews/test_creator_scope.py`

**Interfaces:**
- Produces: `ReviewPackageVersion.canonical_hash`, `ReviewService.create_package`, `comment`, `decide`, `invalidate_for_change`; SOW review read/approve/reject endpoints.
- Consumes: render/publication package, Principal, Rights Gate, audit/outbox.

- [ ] **Step 1: Write approval binding and scope tests**

```python
async def test_material_change_invalidates_creator_approval(review_service, approved_package) -> None:
    changed = await review_service.create_next_version(approved_package.id, description="changed title")
    prior = await review_service.get_decision(approved_package.version_id)
    assert changed.version_id != approved_package.version_id
    assert prior.valid is False
    assert prior.invalidated_reason == "package_version_changed"


async def test_creator_only_reads_own_review(client, creator_headers, foreign_review) -> None:
    response = await client.get(f"/api/reviews/{foreign_review.job_id}", headers=creator_headers)
    assert response.status_code == 404
```

- [ ] **Step 2: Run review tests**

Run: `uv run pytest tests/unit/reviews tests/integration/reviews -q`  
Expected: fail on missing review modules.

- [ ] **Step 3: Implement canonical packages and four decision types**

Package fields include original/localized preview references, changed segments, sponsor plan, transcript, subtitles, title, description, thumbnail, render manifest, and comments. Decisions are `APPROVED`, `APPROVED_WITH_COMMENTS`, `CHANGES_REQUESTED`, and `REJECTED`; actor, role, timestamp, package hash, and comments are immutable. Presets influence future approval policy but never create rights.

- [ ] **Step 4: Run review tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/reviews tests/integration/reviews -q`  
Expected: pass.

### Task 2: Encrypted YouTube OAuth connections and channel allowlist

**Files:**
- Create: `src/oki/crypto/envelope.py`
- Create: `src/oki/youtube/models.py`
- Create: `src/oki/youtube/schemas.py`
- Create: `src/oki/youtube/oauth.py`
- Create: `src/oki/youtube/client.py`
- Create: `src/oki/youtube/router.py`
- Create: `migrations/versions/0016_youtube_connections.py`
- Create: `tests/unit/crypto/test_envelope.py`
- Create: `tests/unit/youtube/test_channel_authorization.py`
- Create: `tests/contract/youtube/test_oauth_flow.py`

**Interfaces:**
- Produces: `EnvelopeCipher.encrypt/decrypt`, `YoutubeOAuthService.start/callback/revoke`, `YoutubeClient`, `AuthorizedChannelService.require`.
- Consumes: settings/key material, current Principal, creator channels/ownership, agreement grants, audit.

- [ ] **Step 1: Write token and channel tests**

```python
def test_refresh_token_is_not_stored_as_plaintext(cipher, token_repository) -> None:
    token_repository.save_refresh_token("refresh-secret", cipher)
    raw = token_repository.raw_value()
    assert b"refresh-secret" not in raw
    assert cipher.decrypt(raw) == b"refresh-secret"


def test_oauth_channel_not_in_agreement_is_rejected(channel_service, connection, foreign_channel, rights) -> None:
    with pytest.raises(RightsProblem) as error:
        channel_service.require(connection, foreign_channel.id, rights)
    assert error.value.code == "channel_not_authorized"
```

- [ ] **Step 2: Run OAuth/channel tests**

Run: `uv run pytest tests/unit/crypto tests/unit/youtube tests/contract/youtube/test_oauth_flow.py -q`  
Expected: fail on missing cipher/OAuth services.

- [ ] **Step 3: Implement PKCE/state OAuth and encrypted rotation-aware token storage**

Bind state and PKCE verifier to user/session with expiration and single use. Request least scopes. Fetch channel identity and store allowed channel only after ownership/rights checks. Encrypt access/refresh tokens with key ID and rotation metadata. Revocation calls Google when possible and always invalidates local use.

- [ ] **Step 4: Run OAuth/channel tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/crypto tests/unit/youtube tests/contract/youtube/test_oauth_flow.py -q`  
Expected: pass.

### Task 3: Private-first resumable upload, checks, scheduling, and public release

**Files:**
- Create: `src/oki/publications/enums.py`
- Create: `src/oki/publications/models.py`
- Create: `src/oki/publications/schemas.py`
- Create: `src/oki/publications/service.py`
- Create: `src/oki/publications/checks.py`
- Create: `src/oki/publications/router.py`
- Create: `src/oki/publications/tasks.py`
- Create: `migrations/versions/0017_publications.py`
- Create: `tests/unit/publications/test_publish_guards.py`
- Create: `tests/integration/publications/test_duplicate_upload.py`
- Create: `tests/contract/youtube/test_private_upload.py`
- Create: `tests/contract/youtube/test_processing_poll.py`

**Interfaces:**
- Produces: `PublicationService.create`, `upload_private`, `approve_release`, `publish`, `unpublish`; `PlatformCheckService`; SOW publication endpoints.
- Consumes: Rights Gate, valid review version, authorized channel, publication package, YouTube client, audit/outbox.

- [ ] **Step 1: Write private-first, duplicate, and fresh-rights tests**

```python
async def test_upload_forces_private_even_if_request_says_public(publication_service, ready_publication, youtube_spy) -> None:
    await publication_service.upload_private(ready_publication.id, requested_visibility="public")
    assert youtube_spy.uploads[0].privacy_status == "private"


async def test_revoked_rights_block_release_before_youtube_call(publication_service, checked_publication, revoke, youtube_spy) -> None:
    await revoke(checked_publication.agreement_version_id)
    with pytest.raises(RightsProblem):
        await publication_service.publish(checked_publication.id)
    assert youtube_spy.visibility_updates == []
```

- [ ] **Step 2: Run publication tests**

Run: `uv run pytest tests/unit/publications tests/integration/publications tests/contract/youtube/test_private_upload.py tests/contract/youtube/test_processing_poll.py -q`  
Expected: fail on missing publication service.

- [ ] **Step 3: Implement guarded publication sequence**

Create explicit business/publication modes `CREATOR_CHANNEL_LOCALIZATION`, `LICENSED_REGIONAL_CHANNEL`, and `ORIGINAL_LOCAL_ADAPTATION`; the latter two require licensed creator identity/likeness use, while creator-channel localization prefers the original channel's localized audio/metadata capabilities when supported. Create uniqueness on localization job, channel, publication mode, and render version. Resumable upload persists platform session/offset and external video ID. Always send private privacy. Upload captions, metadata, localized audio where supported, and supported thumbnail. Poll processing and capture copyright/platform warnings. Run disclosure, metadata, links, and rights checks. A publisher with `PUBLICATION_RELEASE` records a separate approval before public/scheduled visibility update.

- [ ] **Step 4: Implement failure policy and unpublish**

Classify expired/revoked tokens, quota, upload interruption, processing failure, claim/warning, invalid metadata, and permanent platform rejection. Retry safe resumable operations only. Claim/warning moves to `BLOCKED` and notifies humans; it never disputes. Unpublish is permissioned/audited and does not trigger re-upload.

- [ ] **Step 5: Run Stage 4 tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/reviews tests/unit/crypto tests/unit/youtube tests/unit/publications tests/integration/reviews tests/integration/publications tests/contract/youtube -q`  
Expected: pass.

## Stage 4 Acceptance

An internal reviewer and required creator approve the exact package version; a later change invalidates it. OAuth connects an agreement-authorized channel with encrypted revocable tokens. The approved package uploads privately once, captures external ID, passes processing/platform/disclosure/metadata checks, and changes public/scheduled visibility only after a distinct employee approval and fresh rights evaluation.
