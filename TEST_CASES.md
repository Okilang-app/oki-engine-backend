# Oki Engine MVP — Test Cases

## Prerequisites

- Backend running: `http://127.0.0.1:8000`
- Frontend running: `http://localhost:3000`
- Logged in (valid Keycloak session)
- At least one video uploaded (via Assets page or YouTube import)
- At least one internal ad uploaded (via Ad Library page)

---

## TC-1: Upload Video Asset

| Step | Action | Expected |
|------|--------|----------|
| 1 | Go to Assets page | Page loads, shows asset list |
| 2 | Click "Upload" | File picker opens |
| 3 | Select an MP4 file | Upload starts, progress shown |
| 4 | Wait for upload to finish | Asset appears in list with status "active" |

---

## TC-2: Import Video from YouTube URL

| Step | Action | Expected |
|------|--------|----------|
| 1 | Create new project | Enter name, paste YouTube URL in source field |
| 2 | Submit | Job created, video downloads in background |
| 3 | Check Assets page | New asset with YouTube video title, status "active" |

**API call:** `POST /api/assets/import-url` with `{"url": "https://youtube.com/watch?v=..."}`

---

## TC-3: Upload Internal Ad

| Step | Action | Expected |
|------|--------|----------|
| 1 | Go to Ad Library (`/ads`) | Page loads |
| 2 | Upload a short MP4 clip (5-30s) | Ad appears in list with name and duration |
| 3 | Verify ad shows in list | Name, storage_key, duration_seconds visible |

---

## TC-4: Create Project and Analyze

| Step | Action | Expected |
|------|--------|----------|
| 1 | Go to Projects page | List of projects |
| 2 | Click "New Project" | Form appears |
| 3 | Enter name, select source asset | Project created |
| 4 | Click "Analyze" button | Loading state appears (takes 20-40s for real video) |
| 5 | Wait for completion | Success message: "X segments, Y sponsors found" |
| 6 | Go to Review page (`/projects/{id}/review`) | Detected sponsor segments shown with timestamps |

**What happens during Analyze:**
- Downloads video from S3
- Extracts audio via FFmpeg
- Sends audio to Azure Whisper for transcription
- Creates transcript segments in DB
- Runs keyword-based sponsor detection on transcript
- Creates AdSegment records for detected sponsors
- Proposes replacement ads from Ad Library (longest ad that fits)

**Possible errors:**
- 400 "No source asset" — no video linked to the project
- 502 "Transcription failed" — Azure Whisper API error
- 500 — unhandled exception (check server terminal for traceback)

---

## TC-5: Review Sponsor Segments

| Step | Action | Expected |
|------|--------|----------|
| 1 | Open Review page (`/projects/{id}/review`) | Source video player + detected segments listed |
| 2 | Click "Preview" on a segment | Video seeks to the sponsor start time |
| 3 | Verify segment timing | Segment start/end matches where sponsor is in video |
| 4 | Select an ad from dropdown | Ad selected for replacement |
| 5 | Click "Replace" | Segment status changes to "replaced" |
| 6 | OR click "Reject" | Segment will be cut entirely from output |
| 7 | OR click "Approve" | Segment stays in output unchanged |

**Statuses:**
- `detected` — found by analysis, pending review
- `replaced` — will be swapped with internal ad
- `rejected` — will be cut from video
- `approved`/`confirmed` — keeps original content

---

## TC-6: Render Final Video

| Step | Action | Expected |
|------|--------|----------|
| 1 | All segments reviewed (no "detected" remaining) | "Render Video" button enabled |
| 2 | Click "Render Video" | Render job created, progress bar appears |
| 3 | Wait for render (10-60s depending on video size) | Status changes to "COMPLETED" |
| 4 | Rendered video player appears inline | Play modified video directly in page |
| 5 | Click "Download Output Video" | Opens presigned S3 URL, download starts |
| 6 | Compare output with source | Sponsor segments removed/replaced |

**What the renderer does:**
- Downloads source video from S3
- Downloads replacement ad files from S3
- Splits source into "keep" intervals (everything except replaced/rejected segments)
- Normalizes ad clips to match source resolution/fps
- Concatenates: keep1 + ad1 + keep2 + ad2 + ... + keepN
- Uploads result to S3

**Verify render worked:**
- Output file size should differ from source
- If "replaced": ad content visible at that timestamp
- If "rejected": segment gone, video jumps from before to after
- If "approved": content unchanged at that spot

---

## TC-7: Delete Project

| Step | Action | Expected |
|------|--------|----------|
| 1 | Go to Projects list | Projects shown |
| 2 | Delete a project | Project removed from list |
| 3 | Verify cleanup | Transcript segments, ad segments, render jobs all deleted |
| 4 | Source asset still exists in Assets page | Asset unlinked but not deleted |

---

## TC-8: Re-Analyze (Idempotent)

| Step | Action | Expected |
|------|--------|----------|
| 1 | On a project that was already analyzed | Segments visible |
| 2 | Click "Analyze" again | Old segments cleared, fresh analysis runs |
| 3 | New results shown | Segment count may vary slightly (Whisper non-deterministic) |

---

## TC-9: Render Without Review (Edge Case)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Analyze a video | Sponsors detected |
| 2 | Do NOT review any segments | All segments still "detected" |
| 3 | Trigger render | Output equals source (no changes applied) |

This is correct behavior — only "replaced" and "rejected" segments modify the output.

---

## Quick Smoke Test (CLI)

```bash
# Get token
TOKEN=$(curl -s -X POST http://127.0.0.1:58080/realms/oki/protocol/openid-connect/token \
  -d "grant_type=password" -d "client_id=oki-web" \
  -d "username=engineer@oki.test" -d "password=Engineer1234!" \
  | python -c "import sys,json;print(json.loads(sys.stdin.read())['access_token'])")

# 1. Create project
JOB=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"Smoke Test","source_asset_id":"<ASSET_ID>"}' \
  http://127.0.0.1:8000/api/jobs)
JOB_ID=$(echo $JOB | python -c "import sys,json;print(json.loads(sys.stdin.read())['id'])")
echo "Job: $JOB_ID"

# 2. Analyze
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"job_id\":\"$JOB_ID\"}" http://127.0.0.1:8000/api/jobs/analyze

# 3. Check sponsors
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/jobs/$JOB_ID/sponsors"

# 4. Replace sponsor (use segment_id and ad_id from above)
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"ad_id":"<AD_ID>","reason":"test"}' \
  "http://127.0.0.1:8000/api/sponsors/<SEGMENT_ID>/replace"

# 5. Render
RENDER=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"job_id\":\"$JOB_ID\"}" http://127.0.0.1:8000/api/renders)
RENDER_ID=$(echo $RENDER | python -c "import sys,json;print(json.loads(sys.stdin.read())['id'])")
curl -s -X POST -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/renders/$RENDER_ID/execute"

# 6. Wait and check
sleep 20
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/renders/$RENDER_ID"
```
