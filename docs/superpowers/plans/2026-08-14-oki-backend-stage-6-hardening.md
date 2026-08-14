# Oki Backend Stage 6 Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete notifications, observability, security controls, recovery, full acceptance verification, operational documentation, agent context, and final Graphify outputs.

**Architecture:** Hardening wraps the already functional backend without creating a second control plane. Production evidence comes from executable health/security/recovery checks, a complete end-to-end smoke scenario, and traceability from every SOW criterion to code and verification.

**Tech Stack:** Prior stages plus OpenTelemetry Collector, Prometheus, Grafana, Sentry, structlog, ClamAV, Trivy/pip-audit, PostgreSQL backup tools, Graphify.

**Spec:** `docs/superpowers/specs/2026-08-14-oki-localization-backend-design.md`

## Global Constraints

- No critical security finding is accepted.
- Logs, traces, errors, and audits must not contain secrets, OAuth tokens, contract contents, or unrestricted transcript text.
- Staging and production use separate credentials, buckets, databases, identity realms/clients, and OAuth connections.
- Recovery and replay recheck current rights.
- Documentation must contain exact executable commands and no secret values.
- Graphify is rebuilt only after source, tests, and docs describe the delivered system.

---

### Task 1: Notifications and scheduled operational policies

**Files:**
- Create: `src/oki/notifications/enums.py`
- Create: `src/oki/notifications/models.py`
- Create: `src/oki/notifications/service.py`
- Create: `src/oki/notifications/email.py`
- Create: `src/oki/notifications/telegram.py`
- Create: `src/oki/notifications/tasks.py`
- Create: `src/oki/notifications/router.py`
- Create: `migrations/versions/0021_notifications.py`
- Create: `tests/unit/notifications/test_routing.py`
- Create: `tests/integration/notifications/test_delivery_idempotency.py`
- Create: `tests/integration/notifications/test_expiry_schedules.py`

**Interfaces:**
- Produces: `NotificationService.enqueue`, `DeliveryAdapter`, email/Telegram/in-app adapters; scheduled rights/campaign/OAuth/review/payout checks.
- Consumes: outbox events, user preferences, creator assignments, scheduler, audit.

- [ ] **Step 1: Write routing, duplicate, and expiry tests**

```python
def test_publication_error_routes_to_publisher_and_manager(router, event) -> None:
    recipients = router.recipients(event.with_type("publication_error"))
    assert {"publisher", "creator_manager"} <= {item.role for item in recipients}


async def test_same_event_channel_recipient_delivers_once(notification_service, notification_event) -> None:
    await notification_service.handle(notification_event)
    await notification_service.handle(notification_event)
    assert await notification_service.delivery_count(notification_event.id) == 1
```

- [ ] **Step 2: Run notification tests**

Run: `uv run pytest tests/unit/notifications tests/integration/notifications -q`  
Expected: fail on missing notification modules.

- [ ] **Step 3: Implement required triggers and adapters**

Support rights/campaign expiration, missing files, failed/dead-letter jobs, review task, creator approval, publication error/claim, OAuth expiry/revocation, and payout approval. Email/Telegram are real configurable HTTP/SMTP adapters; in-app notifications always persist. Delivery retries only transient errors and exposes status.

- [ ] **Step 4: Run notification tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/notifications tests/integration/notifications -q`  
Expected: pass.

### Task 2: Structured observability, redaction, metrics, tracing, and alerts

**Files:**
- Create: `src/oki/observability/logging.py`
- Create: `src/oki/observability/redaction.py`
- Create: `src/oki/observability/tracing.py`
- Create: `src/oki/observability/metrics.py`
- Create: `deploy/otel/collector.yaml`
- Create: `deploy/prometheus/prometheus.yml`
- Create: `deploy/prometheus/alerts.yml`
- Create: `deploy/grafana/provisioning/dashboards/oki.json`
- Create: `tests/unit/observability/test_redaction.py`
- Create: `tests/integration/observability/test_trace_propagation.py`
- Create: `tests/integration/observability/test_metrics.py`

**Interfaces:**
- Produces: `configure_logging`, `redact_event`, `configure_tracing`, metric instruments and `/metrics`.
- Consumes: FastAPI/Celery lifecycle, correlation/job/task/provider fields, Sentry DSN when configured.

- [ ] **Step 1: Write secret-redaction and trace-continuity tests**

```python
@pytest.mark.parametrize("field", ["authorization", "refresh_token", "access_token", "client_secret", "contract_text", "transcript_text"])
def test_sensitive_fields_are_redacted(field, redact_event) -> None:
    assert redact_event({field: "secret"})[field] == "[REDACTED]"


async def test_api_outbox_worker_share_trace_id(traced_command) -> None:
    trace_ids = await traced_command()
    assert len(set(trace_ids)) == 1
```

- [ ] **Step 2: Run observability tests**

Run: `uv run pytest tests/unit/observability tests/integration/observability -q`  
Expected: fail on missing observability modules.

- [ ] **Step 3: Implement required logs, spans, metrics, and alerts**

Instrument API latency/error, task duration/failure/retry, queue depth/age, worker use, provider latency/usage/cost, storage, render throughput, rights denials, approvals, publication, and analytics freshness. Configure alerts for rights/publication anomaly, backlog, repeated failure, cost ceiling, backup failure, storage, OAuth, claims, and stale analytics.

- [ ] **Step 4: Run observability tests and validate configs**

Run: `uv run pytest tests/unit/observability tests/integration/observability -q`  
Expected: pass.  
Run: `docker compose config --quiet`  
Expected: exit 0.

### Task 3: Security controls, rate limits, audit immutability, and dependency scanning

**Files:**
- Create: `src/oki/security/rate_limit.py`
- Create: `src/oki/security/uploads.py`
- Create: `src/oki/security/events.py`
- Create: `tests/security/test_object_authorization.py`
- Create: `tests/security/test_rate_limits.py`
- Create: `tests/security/test_signed_urls.py`
- Create: `tests/security/test_audit_immutability.py`
- Create: `scripts/security-check.ps1`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: Redis-backed rate-limit dependency, upload limits/normalization, security-event recorder, CI security checks.
- Consumes: Keycloak Principal, object store, ClamAV, PostgreSQL roles, environment settings.

- [ ] **Step 1: Write authorization and immutability tests**

```python
async def test_creator_cannot_presign_foreign_artifact(client, creator_headers, foreign_artifact) -> None:
    response = await client.post(f"/api/artifacts/{foreign_artifact.id}/download-url", headers=creator_headers)
    assert response.status_code == 404


async def test_application_role_cannot_update_or_delete_audit(db_application_session, audit_event) -> None:
    with pytest.raises(DBAPIError):
        await db_application_session.execute(text("delete from audit_events where id=:id"), {"id": audit_event.id})
```

- [ ] **Step 2: Run security tests**

Run: `uv run pytest tests/security -q`  
Expected: fail until all controls are installed.

- [ ] **Step 3: Implement security boundary and CI scans**

Apply organization/project filters before object lookup, short signed URL expiry, rate limits by subject/action/IP, upload size/type/key validation, ClamAV enforcement, security event logging, token revocation paths, and append-only DB grants. CI runs tests, Ruff, mypy, migration check, `pip-audit`, secret scan, and container/image scan.

- [ ] **Step 4: Run security and static checks**

Run: `uv run pytest tests/security -q`  
Expected: pass.  
Run: `uv run ruff check src tests && uv run mypy src && uv run pip-audit`  
Expected: exit 0 with no critical vulnerability.

### Task 4: Backup, restoration, dead-letter recovery, and cost-limit drills

**Files:**
- Create: `scripts/backup.ps1`
- Create: `scripts/restore.ps1`
- Create: `scripts/recovery-drill.ps1`
- Create: `src/oki/jobs/recovery.py`
- Create: `tests/integration/recovery/test_dead_letter_replay.py`
- Create: `tests/integration/recovery/test_rights_recheck.py`
- Create: `tests/integration/recovery/test_cost_limit.py`

**Interfaces:**
- Produces: `RecoveryService.replay(dead_letter_id, principal)`, verified PostgreSQL/object manifest backup and restore scripts.
- Consumes: Rights Gate, task checkpoints, object store versions, database credentials, audit.

- [ ] **Step 1: Write recovery guard tests**

```python
async def test_replay_rechecks_revoked_rights(recovery_service, dead_letter, revoke) -> None:
    await revoke(dead_letter.agreement_version_id)
    with pytest.raises(RightsProblem):
        await recovery_service.replay(dead_letter.id)


async def test_cost_ceiling_stops_before_provider(cost_guard, provider_spy) -> None:
    with pytest.raises(CostLimitProblem):
        await cost_guard.authorize(estimated=Decimal("12"), remaining=Decimal("10"))
    assert provider_spy.calls == []
```

- [ ] **Step 2: Run recovery tests**

Run: `uv run pytest tests/integration/recovery -q`  
Expected: fail on missing recovery service/scripts.

- [ ] **Step 3: Implement replay and verified backups**

Replay requires permission, an unmodified checkpoint/input hash, current rights, available budget, and audit. Backup captures `pg_dump` custom format, migration head, object version manifest, configuration fingerprint, checksum manifest, and encrypted destination. Restore validates checksums, restores into an empty target, applies/validates migrations, checks object references, and runs readiness plus rights smoke.

- [ ] **Step 4: Run recovery tests and local drill**

Run: `uv run pytest tests/integration/recovery -q`  
Expected: pass.  
Run: `pwsh scripts/recovery-drill.ps1 -Environment local`  
Expected: exits 0 and reports database rows plus referenced object checksums restored.

### Task 5: Full SOW acceptance test and provider opt-in checks

**Files:**
- Create: `tests/e2e/test_localization_acceptance.py`
- Create: `tests/e2e/test_prohibited_operations.py`
- Create: `tests/external/test_openai_or_azure.py`
- Create: `tests/external/test_elevenlabs.py`
- Create: `tests/external/test_youtube_private_upload.py`
- Create: `scripts/smoke.ps1`

**Interfaces:**
- Produces: one executable local acceptance story and explicitly marked live provider checks.
- Consumes: all stages.

- [ ] **Step 1: Write the complete acceptance story**

```python
async def test_licensed_localization_acceptance_story(system) -> None:
    creator = await system.onboard_creator_with_channel_proof()
    agreement = await system.approve_complete_agreement(creator)
    asset = await system.upload_and_validate_master(creator, agreement)
    analysis = await system.analyse_and_human_review_sponsors(asset)
    translation = await system.translate_and_approve(analysis, language="es")
    dub = await system.dub_mix_and_approve(translation)
    render = await system.insert_authorized_oki_creative_and_render(dub)
    await system.internal_and_creator_approve(render)
    publication = await system.upload_private_and_pass_checks(render)
    await system.employee_release(publication)
    short = await system.generate_and_approve_short(render)
    await system.attribute_conversion_and_calculate_payout(publication, short)
    trace = await system.audit_trace(publication)
    assert trace.is_complete
```

- [ ] **Step 2: Run the story and observe missing acceptance wiring**

Run: `uv run pytest tests/e2e/test_localization_acceptance.py tests/e2e/test_prohibited_operations.py -q`  
Expected: any missing cross-module contract fails with a specific assertion.

- [ ] **Step 3: Fix only cross-module acceptance gaps**

Wire routers, state transitions, fixtures, outbox delivery, object references, and audit trace until the exact story passes. Prohibited-operation tests assert no routes/services exist for scraping, fingerprint evasion, automatic dispute/counter-notice, fabricated approval, unauthorized clone/replacement, watermark removal, or post-takedown re-upload.

- [ ] **Step 4: Run local acceptance and optional live contracts**

Run: `pwsh scripts/smoke.ps1 -Mode Local`  
Expected: exit 0 and print each state through `PERFORMANCE_REVIEW`.  
When credentials exist, run: `uv run pytest tests/external -m external -q`  
Expected: real OpenAI/Azure and ElevenLabs calls succeed and YouTube test upload remains private; never run public release against an uncontrolled channel.

### Task 6: Operations, schema, API, handover, traceability, and Graphify context

**Files:**
- Create: `README.md`
- Create: `CLAUDE.md`
- Create: `docs/architecture.md`
- Create: `docs/database-schema.md`
- Create: `docs/workflow.md`
- Create: `docs/permissions.md`
- Create: `docs/api.md`
- Create: `docs/providers.md`
- Create: `docs/storage.md`
- Create: `docs/deployment.md`
- Create: `docs/monitoring.md`
- Create: `docs/backup-restore.md`
- Create: `docs/runbook.md`
- Create: `docs/employee-sop.md`
- Create: `docs/security.md`
- Create: `docs/testing.md`
- Create: `docs/requirements-traceability.md`
- Create: `docs/developer-handover.md`
- Create: `docs/diagrams/architecture.mmd`
- Create: `docs/diagrams/workflow.mmd`

**Interfaces:**
- Produces: durable human and agent context plus updated `graphify-out/graph.json`, `graph.html`, `GRAPH_REPORT.md`.
- Consumes: delivered source, migrations, OpenAPI, compose, scripts, tests, and SOW.

- [ ] **Step 1: Generate executable references from source**

Export OpenAPI from `create_app`, schema table/relationship lists from SQLAlchemy metadata/Alembic head, permissions from seeded actions, workflow transitions from `WorkflowStateMachine`, and environment names/descriptions from `Settings`. Documentation may wrap these generated artifacts but must not manually contradict them.

- [ ] **Step 2: Write operational and handover documentation**

Every document listed above contains exact commands, ownership, expected output, failure codes, and safe recovery. `docs/requirements-traceability.md` maps each SOW functional/non-functional requirement, endpoint, quality gate, test family, delivery stage, prohibited behavior, and final acceptance step to code paths and test IDs.

- [ ] **Step 3: Install project Graphify context and rebuild the graph**

Run: `graphify claude install`  
Expected: local `CLAUDE.md` tells future agents to query the graph first.  
Run the Graphify full pipeline over the repository, excluding caches/build/secrets and existing graph output from recursive ingestion.  
Expected: `graphify-out/graph.json`, `graph.html`, and `GRAPH_REPORT.md` cover code and docs; no sensitive files are included.

- [ ] **Step 4: Run final verification**

Run: `uv run pytest -q`  
Expected: all non-external tests pass.  
Run: `uv run ruff check src tests && uv run mypy src && uv run alembic check`  
Expected: exit 0.  
Run: `docker compose config --quiet && pwsh scripts/smoke.ps1 -Mode Local`  
Expected: exit 0.  
Run the documented Graphify query for `Rights Gate` and verify it reaches workflow, provider, rendering, publishing, audit, and tests.

## Stage 6 Acceptance

All critical tests pass; recovery is exercised; monitoring/alerts and cost controls are configured; documentation and traceability are complete; the local portable environment starts and demonstrates the acceptance story; no critical security issue remains; Graphify describes the delivered code and docs; live provider claims are made only for credentials and actions actually exercised.
