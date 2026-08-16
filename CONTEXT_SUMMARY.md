# Oki Creator Localization Engine — Context Summary

## What Was Built
Full-stack MVP for a YouTube creator localization engine with FastAPI backend + Next.js frontend.

## Backend
- **Location**: `C:/Users/User/oki-engine-backend/` (moved from `.worktrees/backend-implementation/`)
- **Status**: MVP complete, 48 endpoints, 20 migrations applied
- **Server**: Running on `http://127.0.0.1:8000` (uvicorn)
- **Health**: `GET /health` → `{"status":"ok"}`
- **Tests**: **118 passed** (was 107/118 with 11 failures)
- **Database**: PostgreSQL 18 on `127.0.0.1:55432/oki`
- **Docker services**: postgres, valkey, seaweedfs, keycloak, clamav

## Frontend
- **Location**: `C:/Users/User/oki-engine-frontend/`
- **Status**: MVP complete, 10 pages, all building
- **Server**: Running on `http://localhost:3000` (next dev)
- **Build**: `npm run build` succeeds
- **Auth**: Custom OIDC flow via `openid-client` v6 → Keycloak

## Key Files
- Backend summary: `.worktrees/backend-implementation/BACKEND_MVP_SUMMARY.md`
- Frontend summary: `oki-engine-frontend/FRONTEND_MVP_SUMMARY.md`
- Frontend architecture: `oki-engine-frontend/FRONTEND_ARCHITECTURE.md`
- API contracts: `oki-engine-frontend/API_CONTRACTS.md`

## Running Commands
```bash
# Backend
cd .worktrees/backend-implementation
uv run uvicorn oki.main:create_app --host 0.0.0.0 --port 8000

# Frontend
cd oki-engine-frontend
npm run dev
```

## Ports
| Service | Port |
|---------|------|
| Backend API | 8000 |
| Frontend | 3000 |
| PostgreSQL | 55432 |
| Valkey | 56379 |
| SeaweedFS S3 | 58333 |
| Keycloak | 58080 |
| ClamAV | 53310 |

## Fixes Applied (This Session)
- ✅ Fixed all **11 test failures/errors** (107→118 passing)
  - Added `creators` + `source_assets` fixtures to 5 test modules
  - Fixed `PrincipalMembership` constructor (`is_creator` → `role_names`)
  - Fixed `SponsorCandidateResponse` missing timestamps in stub detector
  - Fixed `analysis/service.py` querying `assets` → `source_assets`
  - Fixed analytics datetime string → object type
  - Fixed rights gate `channel` test case (`creator_approved=True`)
  - Fixed rights gate `expired` test case (unique external_reference + effective date range)
- ✅ Fixed unterminated template literal in `src/lib/api.ts`
- ✅ Fixed `asChild` prop TypeScript errors on Button/DialogTrigger/SheetTrigger
- ✅ Fixed React hydration error from nested `<button>` elements
- ✅ Fixed `display_name` not-null in publications test fixture

## Auth Implementation (This Session)
- ✅ Custom OIDC PKCE flow via `openid-client` v6
- ✅ Keycloak client (`oki-web`) configured with redirect/callback URIs
- ✅ Test user created in Keycloak realm
- ✅ `/api/auth/signin` → redirects to Keycloak authorization endpoint
- ✅ `/api/auth/callback` → exchanges code for tokens, sets httpOnly cookies
- ✅ `/api/auth/signout` → clears cookies
- ✅ API client auto-injects `Authorization: Bearer <token>` from cookies
- ✅ App shell shows Sign in / Sign out buttons

## Remaining Work (Future Iterations)
1. Wire AI provider integrations (OpenAI Whisper, Azure Translator, ElevenLabs TTS)
2. Add FFmpeg / media processing integration
3. Real-time job progress updates (SSE/WebSocket)
4. Full browser-based end-to-end test with Keycloak login
5. Production Keycloak realm configuration (not local dev)
