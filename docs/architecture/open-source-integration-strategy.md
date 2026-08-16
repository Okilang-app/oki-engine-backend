# Open-source integration strategy

Date: 2026-08-14
Status: Approved implementation direction
Scope: Oki Creator Localization Engine backend

## Decision summary

Oki remains the authoritative business system for rights, consent, immutable asset versions, approvals, publication guards, attribution, finance, and append-only audit. Open-source projects are integrated behind Oki-owned adapters or as isolated sidecars; none may bypass the Rights Gate or become the source of truth for a legal, approval, publication, or payout decision.

Adopt these projects:

| Capability | Project | License | Integration boundary | Adoption stage |
|---|---|---:|---|---:|
| Durable workflows and task operations | [Hatchet](https://github.com/hatchet-dev/hatchet) | MIT | Self-hosted control plane plus Python SDK. Oki persists domain state, guards, idempotency records, checkpoints, usage, and audit; Hatchet schedules and observes worker execution. | 0 |
| Disposable cache and rate limits | [Valkey](https://github.com/valkey-io/valkey) | BSD-3-Clause | Redis-protocol client. Never authoritative and never the only copy of a job, approval, or lock. | 0 |
| S3-compatible development/object storage | [SeaweedFS](https://github.com/seaweedfs/seaweedfs) | Apache-2.0 | S3 gateway through the Oki `ObjectStore` protocol. Production may use AWS S3, GCS interoperability, or another S3-compatible service without domain changes. | 0/1 |
| Resumable creator uploads | [tusd](https://github.com/tus/tusd) | MIT | Sidecar with SeaweedFS/S3 storage. Oki authorizes `pre-create`; idempotent HTTP hooks register progress and completion; Oki alone validates checksum, malware, media, rights, and immutable source registration. | 1 |
| Word timestamps, alignment, diarization | [WhisperX](https://github.com/m-bain/whisperX) | BSD-2-Clause | Version-pinned analysis worker image. Persist model/alignment/VAD/diarization versions and raw result checksum. Human correction remains mandatory where confidence is insufficient. | 2 |
| Scene boundaries | [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | BSD-3-Clause | Python API in analysis workers, versioned parameters and output. | 2 |
| Multilingual scene OCR | [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | Apache-2.0 | Isolated CPU/GPU worker image or serving endpoint. Persist model identifier, coordinates, confidence, and sampled frame hashes. | 2 |
| Editorial timeline interchange | [OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) | Modified Apache-2.0 | Export/import adapter for NLE handoff. PostgreSQL timeline records remain authoritative; OTIO is an interchange artifact, not a media container or database. | 2/3 |
| Stem separation | [Audio Separator](https://github.com/nomadkaraoke/python-audio-separator) | MIT | Isolated worker image using explicitly pinned model weights and checksums. Mark every separated mix for human QA. | 3 |
| Local neutral/consented-clone TTS | [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | Apache-2.0 code and published checkpoints | Optional provider adapter. Neutral/custom voices are allowed by policy; clone endpoints require active creator consent and an allowed purpose at command and worker start. ElevenLabs/Azure remain supported alternatives. | 3 |
| Multi-channel delivery | [Apprise](https://github.com/caronc/apprise) | BSD-2-Clause | In-process delivery adapter for email, Telegram, and future channels. Oki outbox, preferences, delivery idempotency, and audit stay authoritative. | 6 |
| Authentication | [Keycloak](https://github.com/keycloak/keycloak) | Apache-2.0 | OIDC identity, MFA, recovery, and sessions. Oki owns organizations, memberships, resource scopes, and action permissions. | 0 |
| Media probing/rendering | [FFmpeg](https://ffmpeg.org/) / ffprobe | LGPL/GPL depending build | Version-pinned worker images and deterministic command manifests. Build provenance must state enabled codecs and resulting license. | 1/3/5 |
| Malware scanning | [ClamAV](https://github.com/Cisco-Talos/clamav) | GPL-2.0 | Network scanner sidecar. Scan result and signature version are persisted before asset validation. | 0/1 |

## Why these replace the original infrastructure choices

### Hatchet replaces Celery as the workflow executor

Hatchet provides durable tasks, retries, DAGs, durable event waits, scheduling, priorities, dynamic rate limits, concurrency controls, worker slots, a monitoring UI, OpenTelemetry, and Prometheus support. Its self-hosted control plane uses PostgreSQL and can use PostgreSQL rather than RabbitMQ for its internal message queue. This removes the need to build operational replay, queue inspection, workflow waiting, and worker concurrency tooling around Celery.

Hatchet does **not** replace Oki's workflow state machine. A task being queued or successful is not proof that rights, consent, a sponsor plan, creator approval, or publication approval exists. Oki evaluates those guards before dispatch and again in the worker, and writes the resulting business transition and audit event in its own PostgreSQL transaction.

Development uses Hatchet Lite against a separate `hatchet` database on PostgreSQL 18. Production uses Hatchet's multi-container or Kubernetes deployment with pinned image digests. The Hatchet dashboard is an internal operations surface; creator and employee product authentication remains Keycloak.

Sources: [Hatchet README](https://github.com/hatchet-dev/hatchet), [self-hosting](https://docs.hatchet.run/self-hosting), [Hatchet Lite](https://docs.hatchet.run/self-hosting/hatchet-lite).

### Valkey replaces Redis

Oki only needs a disposable Redis-compatible cache/rate-limit backend after Hatchet replaces Celery. Valkey is active, Linux Foundation governed, BSD-3-Clause, and protocol-compatible for this use. No correctness path may depend on cache survival.

Source: [Valkey repository](https://github.com/valkey-io/valkey).

### SeaweedFS replaces MinIO in the portable stack

The MinIO community repository is archived and AGPL-3.0 as of this decision. SeaweedFS is active, Apache-2.0, and exposes an S3-compatible object API. Oki continues to program against a narrow S3 `ObjectStore` protocol, so production object storage remains replaceable.

Sources: [MinIO repository status](https://github.com/minio/minio), [SeaweedFS repository](https://github.com/seaweedfs/seaweedfs).

### tusd replaces custom multipart-upload protocol code

`tusd` is the reference server for the tus resumable-upload protocol and supports arbitrary-size uploads plus S3-compatible storage. Its blocking `pre-create` hook can call Oki authorization and rights validation; `post-create`, `post-receive`, `post-finish`, and termination hooks feed idempotent Oki endpoints. Hook ordering is not guaranteed, so hook ingestion must upsert by tus upload ID and monotonic offset rather than assume event order.

`tusd` completion means all bytes arrived. It does not mean the file is trusted or registered: Oki still checks expected size, SHA-256, object metadata, ClamAV result, ffprobe/media constraints, agreement linkage, creator scope, and immutable destination policy.

Sources: [tusd README](https://github.com/tus/tusd), [tusd hooks](https://tus.github.io/tusd/advanced-topics/hooks/).

## Media pipeline boundaries

### Analysis

1. FFmpeg/ffprobe creates deterministic proxy/audio artifacts and media metadata.
2. WhisperX provides transcript text, word timing, VAD/alignment data, and optional speaker labels. Its documented limitations—poor overlapping-speech handling, imperfect diarization, language-specific alignment models, and unaligned symbols/numbers—map directly to confidence flags and human correction.
3. PySceneDetect produces configurable cut/fade boundaries.
4. PaddleOCR performs multilingual natural-scene text detection/recognition and returns text coordinates and confidence.
5. Oki merges these outputs with entity, safety, sponsor, music, and silence results into its versioned millisecond timeline.
6. OpenTimelineIO exports the approved timeline/editorial decisions to NLE tools. It references external media and is not used as storage.

### Dubbing and rendering

1. The `TtsProvider` interface supports Qwen3-TTS, Azure, OpenAI-compatible TTS, ElevenLabs, and contracted human audio.
2. Qwen3-TTS published 0.6B/1.7B checkpoints cover Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish, and Italian. Neutral/custom voices are distinct from clone-capable base models in configuration.
3. Clone-capable model loading and inference are impossible unless Oki supplies an active consent decision and permitted purpose. Consent revocation blocks new generation before dispatch and at worker start; it never deletes legal/audit records.
4. Audio Separator replaces a direct dependency on the archived Demucs repository. It supports pinned MDX, MDXC, VR, and Demucs-family models from one Python/CLI boundary. Every separated result has `human_qa_required=true`.
5. FFmpeg performs mixing, loudness normalization, subtitle/overlay composition, deterministic rendering, validation, and Shorts operations.

Sources: [WhisperX](https://github.com/m-bain/whisperX), [PySceneDetect](https://github.com/Breakthrough/PySceneDetect), [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR), [OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO), [Audio Separator](https://github.com/nomadkaraoke/python-audio-separator), [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), [Qwen3-TTS 0.6B Base model card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base).

## Projects evaluated but not made core dependencies

| Project | Decision | Reason |
|---|---|---|
| [VideoLingo](https://github.com/Huanshere/VideoLingo) | Reference implementation only | Useful Apache-2.0 ideas for subtitle segmentation, terminology, timing, and provider adapters, but it is a Streamlit/file-workflow application. Its documented limitations include one-main-language retention and unreliable multi-character separation; its progress files cannot satisfy Oki's tenant, rights, audit, and immutable-version requirements. |
| [Tolgee](https://github.com/tolgee/tolgee-platform) | Optional future translation workbench pilot | Apache-2.0 core with separately licensed enterprise directories. Strong string localization UI/API, but timestamped transcript segments, neighboring audiovisual context, creator voice, seven QA dimensions, and exact package approval do not map without a synchronization layer. Oki translation data remains authoritative. |
| [Weblate](https://github.com/WeblateOrg/weblate) | Do not adopt now | Mature REST-enabled localization platform, but GPL-3.0 and optimized for file/string localization. It would introduce another state model without removing Oki-specific review and QA work. |
| [Kitsu](https://github.com/cgwire/kitsu) | Do not adopt | Useful production review concepts and API, but AGPL-3.0 and asset/task vocabulary do not enforce agreement versions, consent, sponsor replacement, exact creator approvals, or publication gates. |
| [AYON](https://github.com/ynput/ayon-backend) | Reject | FSL-1.1-ALv2 restricts competing use until the future-license date. This is unsuitable for a commercial creator production platform without legal negotiation. |
| [Novu](https://github.com/novuhq/novu) | Do not self-host initially | Broad notification workflow/UI capabilities, but a much heavier service and mixed MIT/enterprise licensing. Apprise plus Oki's outbox satisfies required email/Telegram/in-app delivery with less operational and licensing surface. Re-evaluate if embeddable notification inbox/preferences become product scope. |
| [PostHog](https://github.com/PostHog/posthog) | Optional event export only | MIT core with separately licensed enterprise code. Useful for product telemetry; it cannot be authoritative for YouTube/Oki attribution, freshness, immutable finance inputs, payout, or contribution-margin calculations. |
| [Temporal](https://github.com/temporalio/temporal) | Good alternative, not selected | Mature durable execution, but Hatchet has a smaller Python/PostgreSQL-oriented deployment and built-in rate/concurrency controls that map directly to media/provider workers. Do not run both. |
| [Demucs](https://github.com/facebookresearch/demucs) | Do not depend on repository directly | MIT but archived. Audio Separator provides a maintained boundary that can still run explicitly pinned Demucs models when selected. |
| [MinIO](https://github.com/minio/minio) | Replace | Repository is archived and AGPL-3.0. SeaweedFS provides the local S3-compatible boundary under Apache-2.0. |

## Ownership matrix

| Concern | Open-source component may do | Oki must own |
|---|---|---|
| Workflow | Execute, retry, wait, schedule, rate-limit, expose task telemetry | Business state, allowed transitions, guards, idempotency result, rights recheck, audit, costs, dead-letter disposition |
| Upload | Transfer/resume bytes, report offset/storage key | Authorization, creator/agreement binding, checksum, malware/media validation, immutable registration, deletion policy |
| Identity | Authenticate, MFA, recover sessions, issue tokens | Organization membership, creator/project isolation, resource/action authorization, audit |
| Speech/OCR/scenes | Produce versioned candidate analysis | Unified timeline, confidence policy, revisions, approvals, sponsor and safety decisions |
| Translation/TTS | Generate candidates | Glossary/locks, context, QA, assignments, consent, clone policy, version approval |
| Rendering | Execute deterministic tools | Approved inputs, campaign/creative policy, manifest, final validation, package identity |
| Notifications | Deliver to channels | Recipients, preferences, templates, deduplication, escalation, audit |
| Analytics | Collect/export events | Attribution model, source freshness, immutable inputs, payouts, margin, reports |
| Publication | YouTube API transfers and status | Authorized channel, private-first policy, rights/approval/disclosure checks, public-release approval, unpublish policy |

## Supply-chain and operations rules

- Pin Python packages in `uv.lock`; pin service and worker images by immutable digest in production deployment manifests.
- Record tool, model, checkpoint, and container versions on every generated artifact. Model weights require a recorded source URL, license, checksum, and internal approval before production use.
- Separate heavy ML dependencies into queue-specific worker images; never install WhisperX, PaddleOCR, Qwen3-TTS, or Audio Separator in the FastAPI image.
- Scan containers and Python dependencies in CI; generate an SBOM and third-party notice inventory.
- No automatic runtime model download in production. Build or warm approved model snapshots before workers accept traffic.
- External service callbacks and hooks are authenticated, replay-safe, idempotent, and tenant-bound.
- Open-source defaults do not override Oki policies. Rights denial, missing consent, invalid approval, inactive sponsor creative, budget ceiling, and public-release guards fail before billable or public side effects.

## Implementation changes to the approved plans

- Stage 0 Task 2 provisions PostgreSQL 18, Valkey, SeaweedFS S3, Keycloak, and ClamAV. MinIO and Redis image names are removed.
- Stage 0 Task 3 integrates Hatchet and preserves the Oki state machine, transactional outbox, idempotency, checkpoints, provider usage, dead letters, and worker-start guards. Celery-specific files and queue canvas terminology are removed.
- Stage 1 Task 3 uses tusd plus authenticated Oki hooks instead of implementing an upload transport protocol. The Oki asset service still owns validation and immutable registration.
- Stage 2 analysis workers integrate WhisperX, PySceneDetect, PaddleOCR, and OTIO export.
- Stage 3 uses Audio Separator and adds Qwen3-TTS as an optional provider under existing consent policy.
- Stage 6 notification adapters use Apprise behind Oki's outbox and delivery records.
