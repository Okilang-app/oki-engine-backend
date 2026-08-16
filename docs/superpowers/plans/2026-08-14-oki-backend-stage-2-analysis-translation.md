# Oki Backend Stage 2 Analysis and Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Analyse validated media into an auditable unified timeline, require human sponsor review, and produce versioned translations that pass the complete linguistic QA gate.

**Architecture:** Provider-neutral analysis and language protocols isolate hosted OpenAI/Azure calls and local worker tools. WhisperX, PySceneDetect, PaddleOCR, FFmpeg, and OpenTimelineIO adapters produce versioned candidates; all outputs and human revisions are persisted in PostgreSQL with artifact references in S3.

**Tech Stack:** Prior stages plus OpenAI Python SDK with Azure/OpenAI configuration, WhisperX, PySceneDetect, PaddleOCR, OpenTimelineIO, FFmpeg filters, and provider contract fixtures.

**Spec:** `docs/superpowers/specs/2026-08-14-oki-localization-backend-design.md`

## Global Constraints

- Every analysis result uses integer millisecond coordinates and a confidence score.
- Model output and human revisions remain separately auditable.
- Sponsor detection never authorizes automatic removal or replacement.
- Translation preserves facts, numbers, names, meaning, and disclosure boundaries.
- Critical glossary, entity/number, or safety failure blocks dubbing.
- Rights are rechecked before each provider call and task replay.

---

### Task 1: Provider-neutral AI operation records and OpenAI/Azure adapters

**Files:**
- Create: `src/oki/providers/types.py`
- Create: `src/oki/providers/usage.py`
- Create: `src/oki/providers/openai_client.py`
- Create: `src/oki/providers/transcription.py`
- Create: `src/oki/providers/language.py`
- Create: `tests/unit/providers/test_openai_configuration.py`
- Create: `tests/contract/providers/test_transcription_contract.py`
- Create: `tests/contract/providers/test_language_contract.py`

**Interfaces:**
- Produces: `ProviderRequestContext`, `ProviderUsageRecord`, `TranscriptionProvider.transcribe(...) -> TranscriptResult`, `LanguageProvider.generate_structured(...) -> T`, `OpenAICompatibleClient` supporting `openai` and `azure_openai` modes.
- Consumes: settings, Rights Gate, provider-usage repository, correlation IDs.

- [ ] **Step 1: Write configuration and contract tests**

```python
def test_azure_configuration_uses_endpoint_deployment_and_api_version(settings_factory) -> None:
    client = OpenAICompatibleClient(settings_factory(provider="azure_openai"))
    assert client.provider_name == "azure_openai"
    assert client.deployment == "oki-language"


async def test_transcription_contract_returns_words_and_speakers(transcription_provider, audio_fixture) -> None:
    result = await transcription_provider.transcribe(audio_fixture)
    assert result.words[0].start_ms < result.words[0].end_ms
    assert result.words[0].speaker_id
    assert 0 <= result.words[0].confidence <= 1
```

- [ ] **Step 2: Run provider contract tests**

Run: `uv run pytest tests/unit/providers tests/contract/providers -q`  
Expected: fail on missing protocols/adapters.

- [ ] **Step 3: Implement adapters and usage persistence**

OpenAI and Azure modes share output parsing and retry classification but configure base URL, deployment/model, API version, and credentials separately. A provider call first records an operation key and estimated ceiling, then persists status, latency, usage, cost, safe request metadata, and output checksum. Authentication, malformed response, rights denial, and budget errors do not retry.

- [ ] **Step 4: Run contract tests**

Run: `uv run pytest tests/unit/providers tests/contract/providers -q`  
Expected: pass against deterministic HTTP contract fixtures; live tests remain marked `external`.

### Task 2: Unified analysis timeline and editable transcript

**Files:**
- Create: `src/oki/analysis/enums.py`
- Create: `src/oki/analysis/models.py`
- Create: `src/oki/analysis/schemas.py`
- Create: `src/oki/analysis/service.py`
- Create: `src/oki/analysis/router.py`
- Create: `src/oki/analysis/tasks.py`
- Create: `src/oki/analysis/scenes.py`
- Create: `src/oki/analysis/ocr.py`
- Create: `src/oki/analysis/audio_map.py`
- Create: `src/oki/analysis/transcription.py`
- Create: `src/oki/analysis/otio.py`
- Create: `migrations/versions/0007_analysis_timeline.py`
- Create: `tests/unit/analysis/test_timeline.py`
- Create: `tests/integration/analysis/test_analysis_job.py`
- Create: `tests/integration/analysis/test_transcript_revision.py`

**Interfaces:**
- Produces: `AnalysisService.start`, `get_timeline`, `revise_transcript_segment`; Hatchet workflow `run_analysis_pipeline`; versioned WhisperX/PySceneDetect/PaddleOCR adapters; OpenTimelineIO export; timeline schemas for transcript, words, speakers, languages, scenes, OCR, entities, safety, music, silence, and sponsor candidates.
- Consumes: validated asset/proxy/audio artifacts, providers, Rights Gate, state machine, object store, and approved model/tool registry.

- [ ] **Step 1: Write timeline and revision tests**

```python
async def test_timeline_orders_cross_domain_items_by_time(analysis_service, analysed_asset) -> None:
    timeline = await analysis_service.get_timeline(analysed_asset.id)
    assert [item.start_ms for item in timeline.items] == sorted(item.start_ms for item in timeline.items)
    assert {"transcript", "scene", "ocr", "music", "silence", "sponsor"} <= {item.kind for item in timeline.items}


async def test_transcript_edit_preserves_model_version(analysis_service, model_segment, analyst) -> None:
    revised = await analysis_service.revise_transcript_segment(model_segment.id, "corrected", analyst)
    assert revised.parent_version_id == model_segment.version_id
    assert revised.original_model_text == model_segment.text
```

- [ ] **Step 2: Run analysis tests**

Run: `uv run pytest tests/unit/analysis tests/integration/analysis -q`  
Expected: fail on missing timeline models/services.

- [ ] **Step 3: Implement parallel analysis fan-out and merge**

After a rights recheck, run WhisperX transcription/alignment/diarization, language-code-switch analysis, PySceneDetect, sampled PaddleOCR, entity/safety classification, and music/silence mapping as idempotent Hatchet child tasks. Merge by asset analysis version. Persist tool/model/checkpoint versions, parameters, input/output checksums, confidence, and documented limitation flags for overlap, diarization, alignment, and multilingual uncertainty. Expose unified timeline reads, permissioned transcript/text/timestamp revisions, and an OTIO interchange export without making OTIO authoritative.

- [ ] **Step 4: Apply migration and run analysis tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/analysis tests/integration/analysis -q`  
Expected: pass and transition `SOURCE_VALIDATED → ANALYSIS_RUNNING → AD_REVIEW_REQUIRED`.

### Task 3: Sponsor candidate detection and mandatory human review

**Files:**
- Create: `src/oki/sponsors/models.py`
- Create: `src/oki/sponsors/schemas.py`
- Create: `src/oki/sponsors/detection.py`
- Create: `src/oki/sponsors/service.py`
- Create: `src/oki/sponsors/router.py`
- Create: `migrations/versions/0008_sponsor_review.py`
- Create: `tests/unit/sponsors/test_detection_evidence.py`
- Create: `tests/integration/sponsors/test_review_gate.py`

**Interfaces:**
- Produces: `SponsorDetectionService.detect`, `SponsorReviewService.adjust`, `approve`, `reject`; `SponsorCandidate`, `SponsorEvidence`, `SponsorDecision`.
- Consumes: full transcript, scenes/OCR, description links, chapters, music/audio map, creator rights.

- [ ] **Step 1: Write evidence and no-auto-replacement tests**

```python
async def test_detected_segment_cannot_enter_render_without_human_decision(render_plan_service, detected_segment) -> None:
    with pytest.raises(ConflictProblem) as error:
        await render_plan_service.add_sponsor_replacement(detected_segment.id, "creative-id")
    assert error.value.code == "sponsor_human_review_required"


def test_candidate_exposes_detection_reasons(candidate_factory) -> None:
    candidate = candidate_factory(words=["thanks to"], promo_code="OKI20", logo=True)
    assert {"sponsor_phrase", "promo_code", "logo"} <= set(candidate.detection_reasons)
```

- [ ] **Step 2: Run sponsor tests**

Run: `uv run pytest tests/unit/sponsors tests/integration/sponsors -q`  
Expected: fail on missing review gate.

- [ ] **Step 3: Implement multi-signal candidates and human decisions**

Combine transcript phrases, codes/discount/CTA/brands, Sponsor chapters, description links, topic change, logos/titles, music changes, and host-read patterns. Persist evidence and confidence. Only a content analyst may correct boundaries/type/brand and approve/reject. Approval still does not bypass agreement replacement rights.

- [ ] **Step 4: Run sponsor tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/sponsors tests/integration/sponsors -q`  
Expected: pass.

### Task 4: Glossary, translation memory, segment versions, and linguistic QA

**Files:**
- Create: `src/oki/translations/enums.py`
- Create: `src/oki/translations/models.py`
- Create: `src/oki/translations/schemas.py`
- Create: `src/oki/translations/context.py`
- Create: `src/oki/translations/service.py`
- Create: `src/oki/translations/qa.py`
- Create: `src/oki/translations/router.py`
- Create: `src/oki/translations/tasks.py`
- Create: `migrations/versions/0009_translation_workspace.py`
- Create: `tests/unit/translations/test_entity_locks.py`
- Create: `tests/unit/translations/test_qa_gate.py`
- Create: `tests/integration/translations/test_translation_workflow.py`

**Interfaces:**
- Produces: `TranslationContextAssembler`, `TranslationService.start`, `revise_segment`, `add_comment`, `submit_review`; `TranslationQaService.evaluate`; translation/glossary/memory APIs.
- Consumes: approved sponsor-review state, transcript and neighbors, glossary, entities, creator style/restrictions, target language/duration, language provider.

- [ ] **Step 1: Write locked-entity and critical-QA tests**

```python
@pytest.mark.parametrize("source,target", [
    ("Oki saved 25% for Ana", "Oki ahorró 20% para Ana"),
    ("Use code OKI20", "Usa el código OKI-20"),
])
def test_number_name_or_code_change_fails(source, target, qa_service) -> None:
    result = qa_service.evaluate(source=source, target=target, locked_entities=["Oki", "Ana", "25%", "OKI20"])
    assert result.named_entities_and_numbers_pass is False
    assert result.critical_failure is True


def test_critical_failure_blocks_dubbing(translation_service, critical_review) -> None:
    with pytest.raises(ConflictProblem):
        translation_service.approve(critical_review.translation_id)
```

- [ ] **Step 2: Run translation tests**

Run: `uv run pytest tests/unit/translations tests/integration/translations -q`  
Expected: fail on missing workspace and QA.

- [ ] **Step 3: Implement context-rich versioned translation**

Each generation request includes full transcript, current and neighboring segments, Oki/creator glossaries, locked names/numbers/codes, prohibited translations, creator style, target language/local rules, and target duration. Persist machine version, human revisions, comments, back-translation, risk/ambiguity flags, assignment, memory candidates, and seven QA dimensions. Approval transitions only when no critical failure remains.

- [ ] **Step 4: Run Stage 2 tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/providers tests/unit/analysis tests/unit/sponsors tests/unit/translations tests/contract/providers tests/integration/analysis tests/integration/sponsors tests/integration/translations -q`  
Expected: pass and one validated source reaches approved `TRANSLATION_REVIEW` without automatic sponsor replacement.

## Stage 2 Acceptance

A source is transcribed with words/speakers/languages, analysed for scenes/OCR/entities/safety/music/silence, shown as one confidence-bearing timeline, manually corrected with history, reviewed for multiple sponsor segments, translated with full context and locks, and approved through all seven QA dimensions. Critical failures return to the assignee; only approved translation can enter dubbing.
