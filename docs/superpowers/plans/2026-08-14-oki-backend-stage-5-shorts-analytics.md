# Oki Backend Stage 5 Shorts and Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate human-approved licensed vertical clips, attribute Oki conversions, ingest YouTube/Oki performance, and calculate reproducible creator payouts and contribution margin.

**Architecture:** Shorts inherit immutable source/right references and use manifest-driven renders. Analytics keeps raw deduplicated source events plus derived snapshots; payout runs bind exact metric and agreement versions.

**Tech Stack:** Prior stages plus OpenCV tracking, FFmpeg crops/subtitles, YouTube Analytics API adapter, Oki attribution ingestion, PostgreSQL materialized reporting queries, CSV export.

**Spec:** `docs/superpowers/specs/2026-08-14-oki-localization-backend-design.md`

## Global Constraints

- Generate 10–30 candidates using every SOW scoring factor.
- No clip is published without Shorts rights and human approval.
- Every clip links to source asset, agreement version, source timestamps, language, and source video.
- Attribution keys are unique and every Oki event links to creator/video/language/campaign.
- Payout inputs, formula, agreement, decision, and result are immutable/versioned.
- Data freshness is visible in every analytics response.

---

### Task 1: Candidate scoring, crop/face tracking, vertical render, and approval

**Files:**
- Create: `src/oki/shorts/enums.py`
- Create: `src/oki/shorts/models.py`
- Create: `src/oki/shorts/schemas.py`
- Create: `src/oki/shorts/scoring.py`
- Create: `src/oki/shorts/crop.py`
- Create: `src/oki/shorts/service.py`
- Create: `src/oki/shorts/router.py`
- Create: `src/oki/shorts/tasks.py`
- Create: `migrations/versions/0018_shorts.py`
- Create: `tests/unit/shorts/test_scoring.py`
- Create: `tests/unit/shorts/test_safe_zone.py`
- Create: `tests/integration/shorts/test_rights_and_approval.py`

**Interfaces:**
- Produces: `ShortScorer.score`, `CandidateGenerator.generate(count_range=(10, 30))`, `CropTracker`, `ShortService.generate`, `revise`, `approve`; SOW generate-Shorts command.
- Consumes: transcript/scenes/entities/audio activity, source asset/agreement, render tools, review/audit.

- [ ] **Step 1: Write score, count, rights, and human-gate tests**

```python
def test_candidate_score_includes_all_required_factors(short_scorer, candidate) -> None:
    result = short_scorer.score(candidate)
    assert set(result.factors) == {"hook_strength", "thought_completeness", "emotionality", "surprising_fact", "conflict", "question", "punchline", "visual_activity", "information_density"}


async def test_missing_shorts_rights_blocks_generation(short_service, full_video_only_job) -> None:
    with pytest.raises(RightsProblem) as error:
        await short_service.generate(full_video_only_job.id)
    assert error.value.code == "shorts_not_permitted"


async def test_unapproved_short_cannot_publish(short_service, rendered_candidate) -> None:
    with pytest.raises(ConflictProblem):
        await short_service.create_publication(rendered_candidate.id)
```

- [ ] **Step 2: Run Shorts tests**

Run: `uv run pytest tests/unit/shorts tests/integration/shorts -q`  
Expected: fail on missing Shorts modules.

- [ ] **Step 3: Implement candidates and manifest-driven vertical outputs**

Generate 10–30 non-duplicate complete-thought windows, persist factor scores/evidence, and allow manual trim. Build vertical crop with face tracking and manual keyframes, subtitle style, title/caption/cover/CTA, safe-zone validation, and source-video attribution. Approval binds a Short version hash and is invalidated by edits.

- [ ] **Step 4: Run Shorts tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/shorts tests/integration/shorts -q`  
Expected: pass.

### Task 2: YouTube and Oki event ingestion with unique attribution

**Files:**
- Create: `src/oki/analytics/models.py`
- Create: `src/oki/analytics/schemas.py`
- Create: `src/oki/analytics/youtube.py`
- Create: `src/oki/analytics/oki_events.py`
- Create: `src/oki/analytics/attribution.py`
- Create: `src/oki/analytics/tasks.py`
- Create: `migrations/versions/0019_analytics_events.py`
- Create: `tests/unit/analytics/test_attribution.py`
- Create: `tests/integration/analytics/test_event_deduplication.py`
- Create: `tests/contract/analytics/test_youtube_metrics.py`

**Interfaces:**
- Produces: `YoutubeAnalyticsIngestor.ingest`, `OkiEventIngestor.ingest`, `AttributionService.resolve`, freshness metadata.
- Consumes: publications/Short publications, attribution keys, YouTube connection, Oki event credentials/schema.

- [ ] **Step 1: Write attribution and deduplication tests**

```python
async def test_oki_purchase_resolves_full_dimensions(attribution_service, attributed_purchase) -> None:
    result = await attribution_service.resolve(attributed_purchase)
    assert result.creator_id
    assert result.source_asset_id
    assert result.localization_job_id
    assert result.language == "es"
    assert result.campaign_id


async def test_duplicate_source_event_is_counted_once(event_ingestor, event) -> None:
    await event_ingestor.ingest([event, event])
    assert await event_ingestor.count(source=event.source, external_id=event.external_id) == 1
```

- [ ] **Step 2: Run analytics ingestion tests**

Run: `uv run pytest tests/unit/analytics tests/integration/analytics/test_event_deduplication.py tests/contract/analytics/test_youtube_metrics.py -q`  
Expected: fail on missing analytics modules.

- [ ] **Step 3: Implement raw event ingestion and freshness**

Persist source, external event ID, observed/event timestamps, raw payload checksum, creator/video/language/campaign/creative/attribution dimensions, and ingestion run. Support clicks, installs, registrations, trials, purchases, revenue and YouTube view/watch/subscriber/revenue metrics. Upsert only identical source events; conflicting replays create a security/quality event.

- [ ] **Step 4: Run analytics ingestion tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/analytics tests/integration/analytics/test_event_deduplication.py tests/contract/analytics/test_youtube_metrics.py -q`  
Expected: pass.

### Task 3: Creator/Oki/production dashboards and CSV reports

**Files:**
- Create: `src/oki/analytics/queries.py`
- Create: `src/oki/analytics/reports.py`
- Create: `src/oki/analytics/router.py`
- Create: `tests/integration/analytics/test_dashboard_queries.py`
- Create: `tests/integration/analytics/test_csv_exports.py`

**Interfaces:**
- Produces: SOW creator/video/language/campaign/Oki-conversion endpoints; `DailyProductionReport`, `WeeklyManagementReport`, CSV streaming exports.
- Consumes: analytics events, jobs/tasks/provider usage, publications, reviews, costs.

- [ ] **Step 1: Write metric and freshness tests**

```python
async def test_creator_dashboard_exposes_required_metrics(analytics_client, seeded_metrics) -> None:
    body = (await analytics_client.get("/api/analytics/creators")).json()
    assert {"localized_videos", "localized_minutes", "languages_launched", "incremental_views", "subscribers", "youtube_revenue", "creator_payout", "approval_rate", "average_revision_count", "freshness"} <= set(body["items"][0])


def test_daily_report_contains_blockers_and_quality(report_service, report_date) -> None:
    report = report_service.daily(report_date)
    assert hasattr(report, "blocked_projects")
    assert hasattr(report, "main_quality_issues")
    assert hasattr(report, "platform_claims_or_warnings")
```

- [ ] **Step 2: Run dashboard/report tests**

Run: `uv run pytest tests/integration/analytics/test_dashboard_queries.py tests/integration/analytics/test_csv_exports.py -q`  
Expected: fail on missing queries/reports.

- [ ] **Step 3: Implement all SOW metric families**

Creator metrics include localized count/minutes, languages, views/subscribers, revenue/payout, approval/revision. Oki metrics include clicks through retention, CAC, revenue per video/minute. Production includes stage costs, failures/rerenders, QA issues, queue depth, stage time, provider usage/cost. Implement exact daily and weekly report fields and streamed CSV with filter metadata/freshness.

- [ ] **Step 4: Run dashboard/report tests**

Run: `uv run pytest tests/integration/analytics/test_dashboard_queries.py tests/integration/analytics/test_csv_exports.py -q`  
Expected: pass.

### Task 4: Versioned payout calculations and contribution margin

**Files:**
- Create: `src/oki/finance/models.py`
- Create: `src/oki/finance/schemas.py`
- Create: `src/oki/finance/calculator.py`
- Create: `src/oki/finance/service.py`
- Create: `src/oki/finance/router.py`
- Create: `migrations/versions/0020_finance.py`
- Create: `tests/unit/finance/test_payout_formula.py`
- Create: `tests/integration/finance/test_payout_reproducibility.py`

**Interfaces:**
- Produces: `PayoutCalculator.calculate`, `FinanceService.create_run`, `approve_run`, `export`; `ContributionMarginCalculator`.
- Consumes: immutable agreement version/terms, metric snapshot, production/provider costs, adjustments, finance permission/audit.

- [ ] **Step 1: Write reproducibility and fixed-precision tests**

```python
def test_revenue_share_uses_decimal_not_float(payout_calculator) -> None:
    result = payout_calculator.calculate(gross=Decimal("10.01"), share=Decimal("0.3333"), currency="USD")
    assert result.creator_amount == Decimal("3.34")


async def test_same_payout_snapshot_reproduces_result(finance_service, approved_inputs) -> None:
    first = await finance_service.create_run(approved_inputs)
    second = await finance_service.recalculate(first.id)
    assert first.input_hash == second.input_hash
    assert first.creator_amount == second.creator_amount
```

- [ ] **Step 2: Run finance tests**

Run: `uv run pytest tests/unit/finance tests/integration/finance -q`  
Expected: fail on missing finance modules.

- [ ] **Step 3: Implement versioned formulas, approval, and margin**

Snapshot input metrics, agreement version, formula version, currency, costs, adjustments, and rationale. Require finance approval before export. Contribution margin equals attributable Oki revenue minus creator payout, production/provider costs, and configured direct costs; expose per localized video and minute.

- [ ] **Step 4: Run Stage 5 tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/shorts tests/unit/analytics tests/unit/finance tests/integration/shorts tests/integration/analytics tests/integration/finance tests/contract/analytics -q`  
Expected: pass.

## Stage 5 Acceptance

The system generates 10–30 licensed clip candidates, renders and human-approves a source-linked vertical version, creates an authorized publication path, ingests deduplicated YouTube and Oki events with complete attribution, exposes all SOW metrics/reports/freshness, and reproduces creator payout plus Oki contribution margin from immutable inputs.
