# Team Context — Oki Backend Implementation

**Last updated:** 2026-08-15
**Active branch:** `feature/backend-implementation` (git worktree at `.worktrees/backend-implementation`)

## What's Done

### Stage 0 Foundation (complete, all reviewed)

| Task | Status | Focused tests | Commits |
|---|---|---|---|
| Task 1 — Application kernel (FastAPI, errors, UUIDv7, logging, correlation) | Complete, review clean | 18 passed | `8f13d3c..a213eeb` |
| Task 2 — PostgreSQL/Compose/Valkey/SeaweedFS/UoW | Complete, review clean | 16 passed | `2156d64..dbf11d6` |
| Task 3 — Workflow state machine, idempotency, outbox, Hatchet integration | Complete, final re-review clean | 55 passed | `bb2241d..098780b` |
| Task 4 — Keycloak OIDC verification, RBAC, creator scope | Under fix round 1 (5 review defects) | 24 passed pre-fix | `a4ab655..f6f2c72` |

**Task 4 fix round in progress:**
- nbf claim optional (Keycloak default tokens omit it)
- Roles scoped to organization (prevent cross-tenant grants)
- Bounded unknown-key JWKS refresh cooldown
- Safe role downgrade (skip referenced roles)
- Lifespan verifier cleanup (remove from app.state on shutdown)

## What's In Progress

### Stage 1 Rights and Ingestion

| Task | Status | Agent | Notes |
|---|---|---|---|
| Task 1 — Creator/channel/agreement/grant/consent | In progress | CreatorRightsIntake | Hit transient Windows WinError 64 on alembic migration; retrying. All modules written, awaiting GREEN. |
| Task 2 — Rights Gate | Pending | Not dispatched | Needs Task 1 immutable legal tables |
| Task 3 — tusd resumable upload / assets | Pending | Not dispatched | Needs RightsGate boundary |
| Task 4 — Media validation → SOURCE_VALIDATED | Pending | Not dispatched | Needs asset/rights gate |

## What's Next (MVP)

**Target:** Video ad insertion MVP — rights check → choose ad cut window → insert approved Oki creative → render → validated ad-integrated master.

**Sequence:**
1. Stage 1 completes rights and source intake (Tasks 1–4).
2. Stage 2 partial — sponsor candidate detection + human review (Tasks 2–3, no timeline merge/OTIO for MVP).
3. Stage 3 partial — campaign creative library + replacement plan + FFmpeg render manifest (Tasks 4–5, no dubbing/Shorts).

**Renumbered migrations for MVP:**
- 0004: creators/rights (already in progress)
- 0005: assets/uploads
- 0006: asset validation
- 0007: analysis timeline (minimal sponsor only)
- 0008: sponsor review
- 0010: campaigns/creatives (was 0013, renumbered)
- 0011: renders (was 0014, renumbered)

## Architecture Decisions

- **Hatchet** replaces Celery for durable workflows. Oki PostgreSQL owns all business state.
- **Valkey** replaces Redis for disposable cache.
- **SeaweedFS** replaces MinIO for S3-compatible local storage.
- **tusd** owns resumable upload transport; Oki owns validation and immutable registration.
- No YouTube video download — source bytes must be provided by the creator through authorized upload or explicitly permitted source asset.

## Running Agents

| Agent | Task | Status | Last reported |
|---|---|---|---|
| KeycloakAuthorization | Stage 0 Task 4 fix round | Running 26m+ | Writing 5 focused regressions |
| CreatorRightsIntake | Stage 1 Task 1 | Running | Retrying alembic migration after WinError 64 |

## Documents

- SOW: `docs/superpowers/specs/2026-08-14-oki-localization-backend-design.md`
- Open-source strategy: `docs/architecture/open-source-integration-strategy.md`
- MVP plan: `docs/architecture/video-ad-insertion-mvp.md`
- Stage 0 plan: `docs/superpowers/plans/2026-08-14-oki-backend-stage-0-foundation.md`
- Stage 1 plan: `docs/superpowers/plans/2026-08-14-oki-backend-stage-1-rights-ingestion.md`
- Task reports: `.superpowers/sdd/…/task-{N}-report.md`

## Commands

```bash
cd .worktrees/backend-implementation
uv run alembic upgrade head
uv run pytest tests/unit tests/integration -q
```

Focused environment: `OKI_DATABASE_URL=postgresql+asyncpg://oki:oki@localhost:55432/oki`

## Open Risks

1. **FFmpeg not on workstation** — worker.Dockerfile must add FFmpeg for validation/render.
2. **Sponsor detection accuracy** — mitigated by mandatory human review gate.
3. **No live Keycloak/Hatchet in focused tests** — identity/workflow verified with real crypto/SDK construction but no live control-plane dispatch.
