# Oki Creator Localization Engine — Backend Design

Date: 2026-08-14  
Status: Approved in-chat design; awaiting implementation-plan approval  
Source of truth: `graphify-out/corpus/Oki Creator Localization Engine — Technical Playbook & SOW.pdf`

## 1. Purpose

Build the backend and media-worker platform for licensed localization of creator videos. The system manages creator rights, source ingestion, analysis, translation, dubbing, sponsorship review and insertion, rendering, creator approval, authorized private-first YouTube publication, Shorts, attribution, analytics, creator payouts, and a complete audit trail.

The controlling invariants are:

1. Rights before processing.
2. Human approval before publication.
3. No hidden modifications.
4. No voice cloning without separate explicit consent.
5. No sponsor replacement without separate explicit permission and human confirmation.
6. Every public asset is traceable to exact rights, content, review, and render versions.
7. External providers are replaceable.
8. Expensive work is idempotent.
9. Original masters are immutable.
10. Platform compliance has priority over upload volume.

## 2. Scope

### 2.1 Included

- Backend APIs, database schema, migrations, workers, orchestration, storage integration, external-provider adapters, monitoring configuration, deployment configuration, tests, and backend/operations documentation.
- Backend support for employee dashboards and the creator approval portal: authorization, data, review packages, secure review access, decisions, comments, and notifications.
- Real production adapters for OpenAI-compatible OpenAI and Azure OpenAI deployments, ElevenLabs, S3-compatible storage, Keycloak OIDC, YouTube OAuth/Data API, email, and Telegram.
- Local deterministic media processing through FFmpeg/ffprobe, PySceneDetect, Tesseract, Demucs, and OpenCV where applicable.
- Portable Docker deployment with PostgreSQL 18, Redis, MinIO, Keycloak, ClamAV, API, scheduler, worker pools, and observability services.

### 2.2 Not included in this backend repository

- Employee dashboard and creator portal frontend source. Their complete backend contracts are included.
- Content scraping, unauthorized download or publication, Content ID/fingerprint circumvention, automatic disputes/counter-notices, takedown evasion, deceptive impersonation, unauthorized voice cloning, fabricated approvals, watermark removal, or sponsor replacement without explicit authorization.
- A guarantee of YouTube Partner Program acceptance or monetization.

## 3. Architectural Decisions

### 3.1 Deployment shape

Use a modular FastAPI control plane with independently deployable Celery worker pools. PostgreSQL 18 is the authoritative system of record. Redis is a disposable broker, cache, rate-limit store, and short-lived coordination layer. S3-compatible object storage holds contracts and media artifacts.

The API and workers share versioned domain packages and one relational model. This avoids distributed rights and audit state while allowing expensive workloads to scale by queue.

### 3.2 Identity

Keycloak provides OIDC login, MFA, password recovery, account/session lifecycle, and token issuance for employee and creator accounts. FastAPI validates OIDC tokens and applies Oki-specific RBAC plus object-level authorization.

YouTube OAuth is separate from application identity. It grants channel-specific publication access and is stored as an encrypted, revocable connection owned by an Oki user or creator organization.

### 3.3 Workflow orchestration

PostgreSQL stores the explicit workflow state machine, transitions, attempts, checkpoints, costs, cancellation flags, dead-letter entries, and idempotency records. Celery executes stateless or checkpointed activities. Workers never infer permission from queue placement; they re-evaluate current rights and approvals before protected or billable work.

### 3.4 AI and media providers

- One OpenAI-compatible adapter supports OpenAI and Azure OpenAI for model-based transcription, language analysis, translation, QA, sponsor detection, clip scoring, and licensed neutral speech where configured.
- ElevenLabs supports licensed neutral speech and creator-cloned voice only when a valid, separate creator consent covers the requested use.
- Provider selection is configuration and persisted per operation. Every call records provider, model/deployment, parameters, latency, token/audio usage, cost, request correlation, and output artifact.
- Local media tools handle deterministic extraction, validation, scene detection, OCR, source separation, mixing, rendering, crop tracking, and automated technical QA.

## 4. Runtime Topology

| Component | Responsibility | Scale unit |
|---|---|---|
| FastAPI API | REST API, authorization, validation, presigned URLs, reviews, workflow commands, reporting | HTTP replicas |
| Celery scheduler | Scheduled rights-expiry, campaign-expiry, analytics, notification, and recovery tasks | Singleton with lease |
| Analysis workers | ffprobe, proxy, audio extraction, transcription, diarization, language, scenes, OCR, entities, safety, music/silence, sponsor candidates | Queue replicas |
| Translation workers | Machine translation, context assembly, back-translation, automated QA | Queue replicas |
| Dubbing workers | TTS, pronunciation, timing, per-segment regeneration, audio QA | Queue replicas |
| Audio workers | Stems/source separation, ducking, alignment, normalization, mix QA | CPU/GPU replicas |
| Render workers | EDL application, overlays, subtitles, sponsorship, cards, thumbnails, validation | CPU/GPU replicas |
| Shorts workers | Candidate scoring, clips, crop/face tracking, subtitle styling, safe-zone checks | CPU/GPU replicas |
| Publishing workers | YouTube private upload, captions/thumbnail, polling, scheduling, public release | Low-concurrency replicas |
| Analytics workers | YouTube/Oki ingestion, attribution, metrics, reports, payouts | Queue replicas |
| Notification workers | Email, Telegram, in-app events | Queue replicas |
| PostgreSQL 18 | Authoritative relational and workflow state | HA database |
| Redis | Celery broker/result transport, rate limits, cache, locks with bounded TTL | HA Redis |
| S3/MinIO | Versioned contracts and media artifacts | Object storage |
| Keycloak | OIDC, MFA, sessions, recovery | HA identity service |
| ClamAV | Upload malware scanning | Scanner replicas |
| OpenTelemetry/Sentry | Traces, metrics, structured errors and alerts | Collector/service |

## 5. Domain Modules

### 5.1 Identity and permissions

Stores the local subject mapping for Keycloak identities, organizations, roles, creator scopes, and action permissions. Roles include administrator, legal reviewer, creator manager, content analyst, translator, linguistic reviewer, dubbing reviewer, video editor, publisher, finance reviewer, creator, and read-only auditor.

Authorization combines:

- Role/action permission.
- Creator/project ownership or assignment.
- Agreement and approval state.
- Channel authorization.
- Environment restrictions for sensitive production actions.

Creator accounts can only access their creator organization and explicitly shared projects. Legal approval, sponsor replacement, voice consent, payout approval, private upload, and public release are distinct permissions.

### 5.2 Creators and rights

Manages legal/public identity, channel data and ownership evidence, contact/manager, brand guide, restrictions, voice preference, creator status, agreements, agreement versions, allowed videos/categories, languages, territories, platforms, full-video rights, Shorts rights, translation/dubbing/edit/metadata rights, likeness/brand rights, sponsor-removal/replacement modes, endorsement language, voice-clone consent, publication approval policy, license term, revocation, termination, revenue share, and payout terms.

An agreement version is immutable after submission. Approval, revocation, expiration, and supersession are separate events. Rights evaluation returns a decision with stable reason codes and the exact agreement version used.

### 5.3 Assets

Provides signed multipart upload creation, resumable completion, checksum verification, deduplication, malware scan, immutable master registration, optional stem upload, metadata and thumbnail extraction, proxy generation, audio extraction, and media validation.

An asset is always linked to a creator and agreement. Originals are write-once. Corrections create a new asset version; they never overwrite the prior object.

### 5.4 Workflows and jobs

Owns the project state machine, localization jobs, task attempts, dependencies, idempotency, artifacts, costs, cancellation, recovery, priority, logs, and dead letters. Dashboard reads never start heavy work; heavy work begins only through explicit command endpoints.

### 5.5 Analysis

Persists transcript segments and words, speaker identities, language/code-switch spans, scenes, OCR spans, named entities, profanity/safety labels, music/silence spans, sponsor candidates, confidence scores, model outputs, and human revisions. All timeline items share millisecond coordinates and are queryable together.

### 5.6 Sponsorship review

Sponsor candidates include start/end, detected brand, confidence, evidence, links/description evidence, chapters, visual/logo evidence, music/topic-change evidence, and model reasoning. Detection never authorizes removal. A human adjusts boundaries and brand/type, approves or rejects the candidate, and selects an allowed replacement creative. The replacement plan is versioned.

### 5.7 Translation

Provides full-transcript and neighboring-segment context, Oki glossary, creator glossary/style, entity/number locks, prohibited translations, target duration, translation memory, model output, manual editing, comments, back-translation, ambiguity/risk flags, history, assignment, and approval.

QA stores Meaning Accuracy, Naturalness, Timing Fit, Terminology, Named Entities and Numbers, Brand Safety, and Creator Voice Match. Any critical terminology, entity/number, or safety failure blocks dubbing.

### 5.8 Voice and dubbing

Voice modes are `LICENSED_NEUTRAL_VOICE`, `CREATOR_APPROVED_CLONE`, and `HUMAN_VOICE_ACTOR`. The default is licensed neutral voice. The selected profile must cover provider, language, territory, platform, dates, and use type. Clone mode additionally requires a current separate written consent.

Dubbing is segment-addressable. Each result records text version, voice profile, provider, voice ID, parameters, pronunciation overrides, generated duration, stretch, cost, quality, and object version. Failed or revised segments regenerate independently.

### 5.9 Audio processing

Uses supplied stems when available. Otherwise it performs source separation and forces human QA. The mix pipeline aligns speech, preserves music/ambience, ducks appropriately, normalizes loudness, and checks clipping, intelligibility proxies, level jumps, unplanned silence, cut words, timing overflow, and true peak. Source, separated, working, and final mixes remain distinct.

### 5.10 Campaigns and creative library

Campaign and creative versions store language, country, audience, CTA, landing page, promo code, unique attribution key, approved/prohibited claims, active dates, duration, disclosure requirements, media objects, and allowed insertion modes: 10-second bumper, 15-second neutral ad, 30-second demo, 45-second educational integration, visual-only, voice-only, creator-recorded, and local-language UGC.

Inactive or expired creatives cannot enter a render or publication package. Personal endorsement language is forbidden unless the agreement grants separate endorsement approval. Otherwise the neutral Oki support disclosure is used.

### 5.11 Rendering

A render manifest identifies source object version, approved EDL, localized audio version, localized graphics, subtitles, sponsor replacement plan and creative version, disclosure, end card, tracking key, thumbnail package, metadata version, FFmpeg build, command plan, and output preset. The manifest hash is the render idempotency key and reproducibility record.

Outputs are master MP4, clean localized audio, SRT, VTT, thumbnail package, metadata JSON, publication checklist, and approval report. Automated validation checks streams/codecs/duration, black frames, audio, subtitle safe zones, disclosure, links/QR data, thumbnail localization, removed obsolete promo codes, and artifact checksums.

### 5.12 Reviews

Internal and creator review packages include original/localized preview references, changed segments, sponsor plan, transcript, subtitles, title, description, thumbnail, render manifest, and comments. Decisions are `APPROVED`, `APPROVED_WITH_COMMENTS`, `CHANGES_REQUESTED`, or `REJECTED`.

Every decision binds to a package version hash. A material change creates a new package version and invalidates the prior approval. Creator presets can define future approval policy but cannot grant rights absent from an agreement.

### 5.13 YouTube publication

Stores encrypted OAuth tokens, scopes, expiry, revocation, authorized channels, and ownership evidence. Publication mode is either an additional localized audio/metadata package for the creator channel or upload to an official licensed regional channel, subject to API capabilities and rights.

The mandatory sequence is private upload, processing polling, copyright/platform checks, disclosure check, metadata/link check, human publish approval, then public or scheduled release. Duplicate publication is prevented by localization job, channel, publication mode, and render version. The system never auto-disputes, counter-notices, circumvents, or re-uploads after takedown.

### 5.14 Shorts

Produces 10–30 candidate clips scored by hook strength, thought completeness, emotionality, surprising fact, conflict, question, punchline, visual activity, and information density. Each candidate carries source timestamps, vertical crop, face track, subtitles, title, caption, cover, CTA, safe-zone result, and source-video link. A Short inherits source rights and requires separate format rights plus human approval.

### 5.15 Analytics, attribution, and finance

Ingests YouTube views/watch time/subscribers/revenue and Oki clicks/installs/registrations/trials/purchases/revenue. Every Oki event links to creator, source asset, localization job, language, campaign, creative, and attribution key. Data freshness and ingestion source are visible.

Versioned payout runs store input metric snapshots, agreement version, formula, revenue share, adjustments, reviewer decision, result, and export. Reports cover creator, Oki, production, daily production, and weekly management metrics. North-star metric: Oki contribution margin per licensed localized video.

### 5.16 Notifications and audit

Notifications cover rights/campaign expiration, missing files, failed jobs, review assignment, creator approval, publication errors/claims, and payout approval through email, Telegram, and in-app records.

Audit events are append-only and capture actor, subject, organization, entity, action, previous/new values, reason, correlation, request metadata, and timestamp. Agreements, permissions, consents, sponsor decisions, review decisions, deletions, OAuth/channel actions, upload, and publication are mandatory audit categories.

## 6. Core Data Model

All mutable business tables include UUID primary key, organization scope, creation/update timestamps, optimistic `version`, and actor metadata where relevant. Money uses fixed-precision decimal and ISO currency. Times are UTC; media coordinates are integer milliseconds.

| Area | Principal tables |
|---|---|
| Identity | `users`, `organizations`, `memberships`, `roles`, `permissions`, `role_permissions`, `creator_account_scopes` |
| Creators | `creators`, `creator_channels`, `channel_ownership_evidence`, `creator_brand_guides`, `creator_restrictions` |
| Rights | `rights_agreements`, `rights_agreement_versions`, `rights_grants`, `voice_consents`, `endorsement_consents`, `agreement_decisions`, `rights_evaluations` |
| Assets | `source_assets`, `asset_versions`, `asset_uploads`, `upload_parts`, `media_streams`, `asset_stems`, `asset_validation_results`, `media_artifacts` |
| Workflow | `projects`, `localization_jobs`, `workflow_transitions`, `task_runs`, `task_checkpoints`, `idempotency_records`, `dead_letters`, `outbox_events`, `provider_usage` |
| Analysis | `speakers`, `transcript_segments`, `transcript_words`, `scenes`, `ocr_spans`, `named_entities`, `safety_labels`, `audio_regions`, `analysis_revisions` |
| Sponsors | `ad_segments`, `ad_segment_evidence`, `ad_segment_reviews`, `replacement_plans` |
| Translation | `glossaries`, `glossary_terms`, `translation_memories`, `translations`, `translation_segments`, `translation_revisions`, `translation_comments`, `translation_qa_reviews` |
| Voice/audio | `voice_profiles`, `pronunciation_entries`, `dub_segments`, `dub_attempts`, `audio_mix_versions`, `audio_qa_results` |
| Campaigns | `campaigns`, `campaign_versions`, `creatives`, `creative_versions`, `attribution_keys` |
| Render | `edit_decision_lists`, `render_manifests`, `render_attempts`, `render_outputs`, `render_validation_results`, `publication_packages` |
| Review | `review_packages`, `review_package_versions`, `review_assignments`, `review_comments`, `review_decisions`, `creator_approval_presets` |
| Publishing | `oauth_connections`, `authorized_channels`, `publications`, `publication_attempts`, `platform_checks`, `publish_approvals` |
| Shorts | `short_candidates`, `short_versions`, `short_scores`, `short_approvals`, `short_publications` |
| Analytics | `youtube_metric_points`, `oki_conversion_events`, `attribution_links`, `metric_ingestion_runs`, `cost_ledger_entries` |
| Finance | `payout_runs`, `payout_inputs`, `creator_payouts`, `payout_approvals`, `finance_exports` |
| Operations | `notifications`, `notification_deliveries`, `audit_events`, `security_events` |

Foreign keys ensure every source asset references a creator and agreement version, every localization job references an asset and rights evaluation, and every publication resolves to a localization job, publication package, approvals, authorized channel, and active agreement.

## 7. Rights Gate

The gate accepts creator, asset/category, agreement version, language, territory, platform, format, operation, voice mode, sponsorship action, requested publication channel, and current time.

It denies with stable reason codes when:

- No agreement exists or channel ownership is unverified.
- Agreement is draft, pending, expired, revoked, terminated, or superseded without a valid successor.
- Asset/video/category is outside the grant.
- Language, territory, platform, full-video, or Shorts right is absent.
- Translation, dubbing, editing, metadata, likeness, or creator-brand use is absent for the operation.
- Sponsor removal/replacement mode is absent or narrower than the requested edit.
- Clone voice is requested without a current separate consent.
- Creator approval is required and the bound package version is not approved.
- Endorsement-style language is requested without separate endorsement approval.
- OAuth channel is not authorized by both agreement and connection allowlist.

The gate runs at command acceptance, before queue enqueue, at worker start, before render, before private upload, and before public release. A denial is audited and occurs before billable provider work. Revocation marks affected active projects `RIGHTS_REVOKED`, requests task cancellation, invalidates pending approvals where necessary, and blocks all new publication.

## 8. Workflow State Machine

Primary states:

`CREATOR_LEAD → RIGHTS_PENDING → RIGHTS_APPROVED → SOURCE_REQUESTED → SOURCE_UPLOADED → SOURCE_VALIDATED → ANALYSIS_RUNNING → AD_REVIEW_REQUIRED → TRANSLATION_RUNNING → TRANSLATION_REVIEW → DUBBING_RUNNING → AUDIO_REVIEW → RENDER_RUNNING → INTERNAL_QA → CREATOR_REVIEW → PUBLISH_READY → UPLOADED_PRIVATE → PLATFORM_CHECK → PUBLISHED → PERFORMANCE_REVIEW → ARCHIVED`

Exceptional states: `BLOCKED`, `FAILED`, `CANCELLED`, `RIGHTS_REVOKED`.

Transitions are explicit rows with actor/system identity, from/to, guard result, reason, correlation, and timestamp. Resume from `BLOCKED` or retry from `FAILED` returns only to the recorded resumable state after guards are re-evaluated. `CANCELLED` and `RIGHTS_REVOKED` do not resume without a new job/version. Public release is a distinct employee-authorized transition from successful `PLATFORM_CHECK`.

## 9. Storage Layout and Policies

```text
/creators/{creator_id}/contracts/{agreement_id}/{version}/
/creators/{creator_id}/sources/{asset_id}/{version}/
/projects/{project_id}/transcripts/{analysis_version}/
/projects/{project_id}/translations/{language}/{translation_version}/
/projects/{project_id}/audio/{language}/{audio_version}/
/projects/{project_id}/renders/{language}/{render_manifest_hash}/
/projects/{project_id}/shorts/{language}/{short_version}/
/projects/{project_id}/approvals/{review_package_version}/
/projects/{project_id}/publication-packages/{publication_package_version}/
/projects/{project_id}/finance/{payout_run_id}/
```

Contracts, source masters, working artifacts, final renders, approvals, and finance exports use separate bucket prefixes/policies. Source master keys are immutable and bucket versioning is enabled. Database rows store object version, checksum, size, MIME, encryption, retention, and producer task.

## 10. API Surface

The SOW endpoints are preserved:

- `POST /api/creators`
- `GET /api/creators/{creator_id}`
- `POST /api/creators/{creator_id}/agreements`
- `POST /api/agreements/{agreement_id}/approve`
- `POST /api/agreements/{agreement_id}/revoke`
- `POST /api/assets/upload-url`
- `POST /api/assets/complete-upload`
- `POST /api/assets/{asset_id}/validate-rights`
- `POST /api/jobs/analyze`
- `POST /api/jobs/translate`
- `POST /api/jobs/dub`
- `POST /api/jobs/mix`
- `POST /api/jobs/render`
- `POST /api/jobs/generate-shorts`
- `POST /api/jobs/cancel`
- `GET /api/reviews/{job_id}`
- `POST /api/reviews/{job_id}/approve`
- `POST /api/reviews/{job_id}/reject`
- `POST /api/youtube/connect`
- `POST /api/publications`
- `POST /api/publications/{publication_id}/upload-private`
- `POST /api/publications/{publication_id}/publish`
- `POST /api/publications/{publication_id}/unpublish`
- `GET /api/analytics/creators`
- `GET /api/analytics/videos`
- `GET /api/analytics/languages`
- `GET /api/analytics/campaigns`
- `GET /api/analytics/oki-conversions`

Additional CRUD, version, timeline, glossary, voice, campaign, creative, review-comment, Shorts-review, payout, notification, audit, OAuth callback/revoke, job status/retry, health, readiness, and metrics endpoints are grouped under the same `/api` prefix and generated into OpenAPI.

Command endpoints require `Idempotency-Key`. Long-running commands return `202 Accepted` with job/task links. API errors use RFC 9457 problem details with stable error code, correlation ID, field errors, retryability, and safe detail.

## 11. Reliability and Cost Controls

- Database uniqueness on idempotency scope/key, source checksum/creator, render manifest hash, publication job/channel/mode/render, provider operation key, conversion source/event id, and payout run inputs.
- Transactional outbox publishes queue events only after domain commits.
- Workers claim task runs atomically, heartbeat, checkpoint, and use bounded leases.
- Retry only transient failures with bounded exponential backoff and jitter. Rights, authorization, validation, consent, approval, unsupported media, and cost-limit errors are permanent.
- Exhausted tasks create dead-letter records. Replay is permissioned, audited, and rights-gated.
- Cancellation is cooperative between segments and FFmpeg stages; process groups receive graceful termination before forced termination.
- Provider circuit breakers, concurrency limits, per-operation timeout, per-job/creator daily cost ceilings, and pre-call cost estimates prevent runaway use.
- Database backups, object versioning, restoration procedure, and recovery drill are required before production.

## 12. Security and Compliance

- TLS in transit; PostgreSQL, object storage, and token encryption at rest.
- Secrets through environment/secret files in local deployment and an external secret manager in production; no secret values in source or logs.
- Keycloak MFA, short access-token lifetime, session revocation, role and action permissions.
- Creator/project ABAC on every protected query and object URL.
- Encrypted YouTube refresh tokens with key rotation metadata and immediate revocation support.
- Short-lived signed object URLs and least-privilege bucket policies.
- Redis-backed rate limiting, Pydantic validation, content length limits, filename/key normalization, MIME plus magic-byte and codec validation.
- ClamAV scan before uploaded media becomes available to workers.
- Structured security events, dependency/container scanning, staging/production separation.
- Append-only audit enforcement through application permissions and a database role that cannot update/delete audit rows.

## 13. Observability

- JSON logs with timestamp, service, environment, correlation, actor, creator/project/job/task, provider, and error code; sensitive text/tokens are redacted.
- OpenTelemetry spans from API command through outbox, Celery task, provider call, artifact, review, and publication.
- Metrics: API latency/error rate, task duration/failure/retry, queue depth/age, worker utilization, provider latency/usage/cost, storage usage, render throughput, rights denials, approval time, publication status, analytics freshness.
- Sentry aggregates API/worker failures with release and trace identifiers.
- Alerts cover rights/publication anomalies, queue backlog, repeated worker/provider failures, cost limits, backup failure, storage pressure, OAuth expiry/revocation, platform claims, and stale analytics.

## 14. Verification Plan

### 14.1 Rights

Test no agreement; pending, expired, revoked, terminated, and superseded agreements; unauthorized asset/category/language/territory/platform/format; missing sponsor rights; too-narrow replacement mode; missing clone consent; missing endorsement approval; creator approval required; approval invalidated or revoked before publication; unauthorized channel; revocation during active work; and provider not called after denial.

### 14.2 Media

Test resumable multipart interruption; part retry; corrupt content; malware; duplicate checksum; unsupported codec; missing audio; long video; multiple speakers; music; multiple sponsors; immutable original; proxy/thumbnail/audio extraction; stems and no-stems paths; and actionable ffprobe/FFmpeg errors.

### 14.3 Analysis, translation, and dubbing

Test word timestamps; timeline confidence; transcript/timestamp edits and history; sponsor evidence and mandatory human decision; names, numbers, acronyms, glossary locks, jokes, slang, code switching, overlapping speakers, unclear speech, Oki terminology, ambiguity flags, back-translation, QA critical failure, audio shorter/longer than source, failed TTS segment, isolated regeneration, pronunciation override, consent expiry, and provider usage/cost persistence.

### 14.4 Render and publishing

Test missing/inactive/expired creative; unapproved sponsor segment; missing disclosure; subtitle overlap/safe zone; black frames; audio validation; worker restart; duplicate render; reproducibility; immutable original; approval-version invalidation; expired/revoked OAuth; unauthorized channel; duplicate upload; processing failure; platform claim/warning; private default; final human release; and blocked automatic dispute/re-upload behavior.

### 14.5 Shorts, analytics, and finance

Test 10–30 candidates, score factors, source-right inheritance, missing Shorts rights, safe zones, human approval, source linking, unique attribution, event deduplication, freshness, reproducible payout snapshots/formulas, finance approval, CSV export, and contribution-margin calculation.

### 14.6 End-to-end demonstration

Onboard a creator, record ownership, approve a versioned agreement, upload a master, validate rights, analyse and edit the timeline, approve sponsor handling, translate and approve, generate permitted dubbed audio, mix and review, select an active attributed Oki creative, render and validate, obtain creator approval, create a private authorized publication, pass platform/disclosure/metadata checks, approve public release, create and approve a licensed Short, ingest YouTube/Oki events, calculate payout/margin, and trace every decision through audit.

Local CI verifies control-plane, storage, media, and provider HTTP contracts. Live OpenAI/Azure OpenAI, ElevenLabs, and YouTube checks are opt-in and require user-owned credentials and an authorized test channel. Their absence does not change connector implementation, but a real billable call or public platform action cannot be claimed as exercised without them.

## 15. Documentation and Graph Context

The delivered repository includes:

- Architecture and runtime topology.
- ER/database schema and migration guide.
- Workflow state/guard reference.
- Permissions matrix.
- API/OpenAPI usage.
- Provider adapter and credential configuration.
- Storage and retention policy.
- Local development and deployment procedures.
- Monitoring and alert reference.
- Backup, restoration, and recovery drill.
- Operational runbook and employee SOP mapping.
- Security model and prohibited operations.
- Test strategy and SOW requirements traceability.
- Developer handover and common extension paths.
- Environment template with names and descriptions but no secrets.

A project-level agent context file directs future sessions to query `graphify-out/graph.json` before broad source reads. Graphify is rebuilt over source plus documentation after implementation, producing `graph.html`, `graph.json`, and `GRAPH_REPORT.md`. The current graph covers the source SOW and contains 137 nodes, 203 edges, and 9 communities.

## 16. Delivery Mapping

| SOW stage | Backend acceptance |
|---|---|
| Stage 0 | This design, ER model, workflow, permissions, API, storage, provider contracts, and traceability are approved. |
| Stage 1 | Identity, creators, rights, Rights Gate, uploads, validation, audit; licensed proceeds and unlicensed blocks. |
| Stage 2 | Analysis, timeline data, sponsor review, transcript editing, translation, glossary, QA; one source reaches approved translation. |
| Stage 3 | Voice consent, TTS, mixing, campaigns, sponsor replacement, rendering, automated QA; reviewable localized master exists. |
| Stage 4 | Creator review, approval versioning, YouTube OAuth, private upload, captions/metadata, release approval; authorized private-first flow succeeds. |
| Stage 5 | Shorts, attribution, analytics, and payout; licensed Short and attributable conversion flow succeed. |
| Stage 6 | Security, recovery, monitoring, backups, cost controls, documentation, and critical tests pass. |

## 17. Definition of Done

- All backend modules, workers, migrations, infrastructure configuration, deployment scripts, monitoring, and documentation in scope are implemented.
- Automated tests and the local end-to-end smoke flow pass.
- Every SOW backend acceptance criterion is linked to an implementation and verification result.
- Permissions and creator isolation are tested.
- Relevant actions appear in append-only audit events.
- No critical security issue remains in the implemented scope.
- The portable Docker environment starts from documented commands.
- Graphify outputs reflect the delivered source and documentation.
- Live external-provider actions are reported only when actually exercised with supplied credentials.

## 18. Resolved Decisions and External Prerequisites

- Database: PostgreSQL 18.
- Orchestration: Celery with Redis; PostgreSQL is the workflow source of truth.
- Identity: Keycloak OIDC.
- Object storage: S3-compatible; MinIO for local portable deployment.
- AI: OpenAI-compatible abstraction supporting OpenAI and Azure OpenAI; ElevenLabs for appropriately licensed voice profiles.
- Publication: YouTube OAuth/Data API with encrypted tokens and private-first behavior.
- Deployment: portable Docker baseline.
- Required for live external acceptance: OpenAI or Azure OpenAI credentials/deployment names, ElevenLabs credentials and permitted voice IDs where used, S3 credentials outside local MinIO, Keycloak production settings, YouTube OAuth client credentials and an authorized test channel, email/Telegram credentials if those channels are enabled, and Oki attribution-event source credentials/schema.
