# Oki Backend Stage 3 Dubbing and Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate permissioned segment-level dubbing, produce reviewed localized mixes, select only authorized active Oki creatives, and render reproducible validated localized masters.

**Architecture:** Voice profiles and consents are independent domain records checked before every TTS call. Audio and render pipelines are manifest-driven, content-addressed, idempotent, and store all intermediates and QA results.

**Tech Stack:** Prior stages plus OpenAI/Azure speech adapters, ElevenLabs SDK/API, optional Qwen3-TTS worker, FFmpeg/ffprobe, Audio Separator, pyloudnorm, NumPy, and S3 artifacts.

**Spec:** `docs/superpowers/specs/2026-08-14-oki-localization-backend-design.md`

## Global Constraints

- Default voice mode is `LICENSED_NEUTRAL_VOICE`.
- Creator cloning requires separate current written consent; fail closed before provider use.
- Every audio attempt records provider, voice, parameters, usage, cost, source text version, and checksum.
- Sponsor replacement requires agreement rights, human segment approval, active creative, and an approved replacement plan.
- Original, separated, working, and final mixes remain separately available.
- Render identity is the canonical manifest hash; retries cannot create a duplicate logical render.

---

### Task 1: Voice library, consent policy, pronunciation, and TTS adapters

**Files:**
- Create: `src/oki/voices/enums.py`
- Create: `src/oki/voices/models.py`
- Create: `src/oki/voices/schemas.py`
- Create: `src/oki/voices/policy.py`
- Create: `src/oki/voices/pronunciation.py`
- Create: `src/oki/voices/router.py`
- Create: `src/oki/providers/tts.py`
- Create: `src/oki/providers/elevenlabs.py`
- Create: `src/oki/providers/qwen3_tts.py`
- Create: `migrations/versions/0010_voice_profiles.py`
- Create: `tests/unit/voices/test_voice_policy.py`
- Create: `tests/unit/voices/test_pronunciation.py`
- Create: `tests/contract/providers/test_tts_contract.py`

**Interfaces:**
- Produces: `VoiceMode`, `VoicePolicy.require(profile, request, agreement, consent, now)`, `PronunciationDictionary.apply`, `TtsProvider.synthesize(...) -> SpeechResult`, and OpenAI/Azure, ElevenLabs, and optional Qwen3-TTS implementations.
- Consumes: rights agreement version, current voice consent, translation segment version, approved model registry, and provider usage.

- [ ] **Step 1: Write fail-closed voice tests**

```python
def test_creator_clone_without_separate_consent_fails_before_provider(voice_service, clone_profile, translated_segment, tts_spy) -> None:
    with pytest.raises(RightsProblem) as error:
        voice_service.synthesize(clone_profile, translated_segment)
    assert error.value.code == "voice_clone_consent_missing"
    assert tts_spy.calls == []


def test_pronunciation_overrides_longest_term_first(dictionary) -> None:
    rendered = dictionary.apply("Oki met Ana García", language="es")
    assert rendered.ssml.count("<phoneme") == 2
```

- [ ] **Step 2: Run voice/provider tests**

Run: `uv run pytest tests/unit/voices tests/contract/providers/test_tts_contract.py -q`  
Expected: fail on missing policy/adapters.

- [ ] **Step 3: Implement licensed profile coverage and adapters**

A profile covers provider, voice ID/model checkpoint, mode, languages, territories, platforms, start/end dates, contract artifact, and allowed uses. Qwen3-TTS neutral/custom checkpoints and clone-capable base checkpoints are configured as distinct provider capabilities; no runtime model download is allowed in production. Clone mode additionally resolves current creator consent at command and worker start. Human-actor mode references recording-use agreement. Pronunciation entries support Oki, creator names, brands, and specialist terms with language-scoped phonetic/SSML forms.

- [ ] **Step 4: Run voice/provider tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/voices tests/contract/providers/test_tts_contract.py -q`  
Expected: pass.

### Task 2: Segment dubbing, timing fit, regeneration, and audio QA

**Files:**
- Create: `src/oki/dubbing/models.py`
- Create: `src/oki/dubbing/schemas.py`
- Create: `src/oki/dubbing/service.py`
- Create: `src/oki/dubbing/timing.py`
- Create: `src/oki/dubbing/qa.py`
- Create: `src/oki/dubbing/router.py`
- Create: `src/oki/dubbing/tasks.py`
- Create: `migrations/versions/0011_dubbing.py`
- Create: `tests/unit/dubbing/test_timing.py`
- Create: `tests/integration/dubbing/test_segment_regeneration.py`
- Create: `tests/integration/dubbing/test_failed_segment_resume.py`

**Interfaces:**
- Produces: `DubbingService.start`, `regenerate_segment`, `submit_review`; `TimingFitter.fit`; `DubbingQa.evaluate`; job task `dub_translation`.
- Consumes: approved translation, voice policy, pronunciation dictionary, TTS provider, object store, workflow state.

- [ ] **Step 1: Write timing and isolated-regeneration tests**

```python
@pytest.mark.parametrize("generated,target,max_ratio", [(900, 1000, 1.12), (1100, 1000, 1.12)])
def test_moderate_stretch_stays_within_limit(generated, target, max_ratio, timing_fitter) -> None:
    plan = timing_fitter.fit(generated_ms=generated, target_ms=target, max_ratio=max_ratio)
    assert plan.applied_ratio <= max_ratio


async def test_regenerating_one_segment_does_not_charge_others(dubbing_service, completed_dub, provider_spy) -> None:
    await dubbing_service.regenerate_segment(completed_dub.segments[2].id)
    assert [call.segment_id for call in provider_spy.calls] == [completed_dub.segments[2].id]
```

- [ ] **Step 2: Run dubbing tests**

Run: `uv run pytest tests/unit/dubbing tests/integration/dubbing -q`  
Expected: fail on missing dubbing service.

- [ ] **Step 3: Implement checkpointed segment pipeline**

Generate each approved translation segment under its own idempotency key, probe duration, optionally request text shortening without meaning loss, apply bounded time stretch, and calculate quality. Persist every attempt and artifact. Resume failed jobs from incomplete segments only. Reviewer checks pronunciation, naturalness/emotion, synchronization/transitions, and sponsor audio before approval.

- [ ] **Step 4: Run dubbing tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/dubbing tests/integration/dubbing -q`  
Expected: pass and critical failures remain in `DUBBING_RUNNING`/`AUDIO_REVIEW` without advancing.

### Task 3: Stem/source separation, mixing, and technical audio checks

**Files:**
- Create: `src/oki/audio/models.py`
- Create: `src/oki/audio/separation.py`
- Create: `src/oki/audio/mixing.py`
- Create: `src/oki/audio/qa.py`
- Create: `src/oki/audio/service.py`
- Create: `src/oki/audio/tasks.py`
- Create: `migrations/versions/0012_audio_mix.py`
- Create: `tests/unit/audio/test_mix_plan.py`
- Create: `tests/unit/audio/test_audio_qa.py`
- Create: `tests/integration/audio/test_stem_and_separation_paths.py`

**Interfaces:**
- Produces: `AudioMixPlan`, `SourceSeparator`, `AudioMixer.mix`, `AudioQa.evaluate`, `AudioService.create_mix`.
- Consumes: source stems or original audio, approved dub segments, FFmpeg runner, versioned `SourceSeparator`, object store.

- [ ] **Step 1: Write stem preference and QA tests**

```python
async def test_supplied_stems_skip_source_separation(audio_service, asset_with_stems, separator_spy) -> None:
    await audio_service.create_mix(asset_with_stems.id)
    assert separator_spy.calls == []


@pytest.mark.parametrize("fixture,code", [("clipped.wav", "clipping"), ("long_silence.wav", "unplanned_silence"), ("cut_word.wav", "possible_cut_word")])
def test_audio_qa_flags_defects(audio_qa, audio_fixture, fixture, code) -> None:
    assert code in audio_qa.evaluate(audio_fixture(fixture)).error_codes
```

- [ ] **Step 2: Run audio tests**

Run: `uv run pytest tests/unit/audio tests/integration/audio -q`  
Expected: fail on missing mix/separation modules.

- [ ] **Step 3: Implement two audio paths and mandatory no-stem review**

Prefer supplied dialogue/music/ambience stems. Otherwise run Audio Separator with an explicitly approved model/checksum and set `human_qa_required=true`. Align localized speech, preserve music/ambience, duck under dialogue, normalize loudness, and check clipping, level jumps, unplanned silence, cut words, segment overflow, and true peak. Persist separator/model versions and upload source/separated/working/final artifacts distinctly.

- [ ] **Step 4: Run audio tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/audio tests/integration/audio -q`  
Expected: pass.

### Task 4: Campaigns, creative versions, attribution, and sponsor replacement plans

**Files:**
- Create: `src/oki/campaigns/enums.py`
- Create: `src/oki/campaigns/models.py`
- Create: `src/oki/campaigns/schemas.py`
- Create: `src/oki/campaigns/service.py`
- Create: `src/oki/campaigns/router.py`
- Create: `src/oki/sponsors/replacement.py`
- Create: `migrations/versions/0013_campaigns_creatives.py`
- Create: `tests/unit/campaigns/test_eligibility.py`
- Create: `tests/integration/campaigns/test_attribution.py`
- Create: `tests/integration/sponsors/test_replacement_plan.py`

**Interfaces:**
- Produces: `CreativeEligibility.evaluate`, `CampaignService`, `AttributionKeyService.issue`, `ReplacementPlanService.approve`.
- Consumes: rights decision, human sponsor decision, campaign dates/countries/languages/audience, endorsement policy.

- [ ] **Step 1: Write expired creative and endorsement tests**

```python
def test_expired_creative_cannot_be_selected(eligibility, expired_creative, request) -> None:
    result = eligibility.evaluate(expired_creative, request)
    assert result.eligible is False
    assert result.reason_code == "creative_expired"


def test_neutral_copy_is_required_without_endorsement(eligibility, creator_voice_copy, rights_without_endorsement) -> None:
    result = eligibility.evaluate(creator_voice_copy, rights_without_endorsement)
    assert result.reason_code == "endorsement_not_permitted"
```

- [ ] **Step 2: Run campaign/replacement tests**

Run: `uv run pytest tests/unit/campaigns tests/integration/campaigns tests/integration/sponsors/test_replacement_plan.py -q`  
Expected: fail on missing eligibility and replacement plan.

- [ ] **Step 3: Implement versioned creative library and four-gate replacement**

Persist all SOW creative types and campaign fields. Issue one unique attribution key per integration. A replacement plan requires agreement permission, human-approved ad segment, eligible creative version, and a separately permissioned plan approval. Store old/new boundaries, media edits, disclosure, copy mode, and obsolete promo-code removal.

- [ ] **Step 4: Run campaign/replacement tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/campaigns tests/integration/campaigns tests/integration/sponsors/test_replacement_plan.py -q`  
Expected: pass.

### Task 5: Reproducible FFmpeg render manifests and automated QA

**Files:**
- Create: `src/oki/renders/models.py`
- Create: `src/oki/renders/schemas.py`
- Create: `src/oki/renders/manifest.py`
- Create: `src/oki/renders/ffmpeg_plan.py`
- Create: `src/oki/renders/qa.py`
- Create: `src/oki/renders/service.py`
- Create: `src/oki/renders/router.py`
- Create: `src/oki/renders/tasks.py`
- Create: `migrations/versions/0014_renders.py`
- Create: `tests/unit/renders/test_manifest_hash.py`
- Create: `tests/unit/renders/test_render_qa.py`
- Create: `tests/integration/renders/test_render_retry.py`

**Interfaces:**
- Produces: canonical `RenderManifest`, `RenderManifest.hash`, `FfmpegPlanBuilder`, `RenderQa`, `RenderService.start`; SOW render endpoint.
- Consumes: immutable source, approved EDL, approved mix, overlays/subtitles, approved replacement/creative, disclosures/cards/tracking, object store.

- [ ] **Step 1: Write reproducibility and retry tests**

```python
def test_same_inputs_produce_same_manifest_hash(manifest_factory) -> None:
    first = manifest_factory(order="normal")
    second = manifest_factory(order="reversed_input_dicts")
    assert first.canonical_hash() == second.canonical_hash()


async def test_duplicate_render_request_returns_existing_render(render_service, approved_manifest) -> None:
    first = await render_service.start(approved_manifest, idempotency_key="render-1")
    second = await render_service.start(approved_manifest, idempotency_key="render-2")
    assert first.render_id == second.render_id
```

- [ ] **Step 2: Run render tests**

Run: `uv run pytest tests/unit/renders tests/integration/renders -q`  
Expected: fail on missing manifest/render modules.

- [ ] **Step 3: Implement canonical manifests, outputs, and validation**

Build FFmpeg commands only from validated manifest types. Persist FFmpeg build and command plan. Emit master MP4, clean audio, SRT/VTT, thumbnail package, metadata JSON, checklist, and approval report. Validate streams/duration, black frames, audio, subtitle safe zones/overlap, disclosure, links/QR payloads, thumbnail localization, removed old promo codes, and checksums. Failures expose actionable codes/log artifact.

- [ ] **Step 4: Run Stage 3 tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/voices tests/unit/dubbing tests/unit/audio tests/unit/campaigns tests/unit/renders tests/contract/providers/test_tts_contract.py tests/integration/dubbing tests/integration/audio tests/integration/campaigns tests/integration/sponsors/test_replacement_plan.py tests/integration/renders -q`  
Expected: pass and produce a reviewable localized master.

## Stage 3 Acceptance

An approved translation is dubbed with a permitted neutral, clone, or human profile; names follow pronunciation overrides; failed segments resume independently; the localized mix passes technical and human QA; only an authorized active attributed Oki creative enters an approved replacement plan; and duplicate render requests resolve to one reproducible validated master and publication package.
