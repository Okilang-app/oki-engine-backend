# Oki Engine Runbook

## Starting / Stopping the Stack
```bash
docker compose up -d
cd src && uvicorn oki.main:create_app --host 0.0.0.0 --port 8000
```

## Running Migrations
```bash
cd src && alembic upgrade head
```

## Resetting a Stuck Workflow Job
```sql
UPDATE localization_jobs SET workflow_state = 'SOURCE_UPLOADED' WHERE id = '<job_id>';
```

## Re-triggering a Failed Publish
```bash
curl -X POST http://localhost:8000/api/publications/<id>/retry \
  -H "Authorization: Bearer <token>"
```

## Revoking a Creator's Agreement
Mark the agreement as terminated in the admin UI or via API.

## Rotating API Keys
1. Update the key in your provider dashboard
2. Update OKI_ELEVENLABS_API_KEY or OKI_OPENAI_API_KEY in .env
3. Restart the backend

## Checking Provider Costs
View cost ledger in the analytics dashboard or query:
```sql
SELECT SUM(amount) FROM cost_ledger_entries WHERE provider = 'elevenlabs' AND created_at > NOW() - INTERVAL '30 days';
```

## Backing Up Data
```bash
pg_dump -h localhost -U oki oki > backup_$(date +%F).sql
```

## Incident Response
1. Check logs: docker compose logs -f backend
2. Check database connectivity
3. Check S3/SeaweedFS connectivity
4. Check provider API status
