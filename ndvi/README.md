# NDVI subsystem

This app materializes NDVI observations in the database and serves them via API endpoints. NDVI is computed asynchronously through Celery jobs to keep request latency predictable and to protect upstream quotas.

## Environment variables

- `SENTINELHUB_CLIENT_ID`, `SENTINELHUB_CLIENT_SECRET`: OAuth client credentials (required).
- `NDVI_ENGINE` (default `sentinelhub`).
- `NDVI_DEFAULT_STEP_DAYS` (default `7`), `NDVI_DEFAULT_MAX_CLOUD` (default `30`), `NDVI_DEFAULT_LOOKBACK_DAYS` (default `14`).
- `NDVI_MAX_AREA_KM2` (default `5000`), `NDVI_MAX_DATERANGE_DAYS` (default `370`).
- `NDVI_CACHE_TTL_TIMESERIES_SECONDS` (default `86400`), `NDVI_CACHE_TTL_LATEST_SECONDS` (default `21600`).
- `NDVI_LOCK_TIMEOUT_SECONDS` (default `60`), `NDVI_MANUAL_REFRESH_COOLDOWN_SECONDS` (default `900`).
- `NDVI_REQUEST_TIMEOUT_SECONDS` (default `20`).
- Celery: `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_TASK_ALWAYS_EAGER` (defaults to eager during tests).

## Schedules (Celery Beat)

- Daily refresh (`ndvi.tasks.enqueue_daily_refresh`) at 03:15 UTC: refresh latest NDVI for all active farms with bounding boxes.
- Weekly gap-fill (`ndvi.tasks.enqueue_weekly_gap_fill`) at 04:00 UTC on Sundays: backfill the last ~120 days at 7-day steps.

## Endpoints (`/api/v1/`)

- `GET /farms/{farm_id}/ndvi/timeseries/?start=YYYY-MM-DD&end=YYYY-MM-DD&step_days=7&max_cloud=30`
- `GET /farms/{farm_id}/ndvi/latest/?lookback_days=14&max_cloud=30`
- `POST /farms/{farm_id}/ndvi/refresh/` (manual trigger with throttling)
- `GET /ndvi/jobs/{job_id}/`

All endpoints require authentication, enforce farm ownership, and return the global success envelope (`{"status": 0, "message": "...", "data": ...}`).

## Operational notes

- NDVI is persisted to the `NdviObservation` table (unique per farm/engine/bucket_date).
- Jobs are tracked in `NdviJob` with idempotent request hashes and distributed locks to avoid duplicate upstream calls.
- OAuth tokens for Sentinel Hub are cached in Redis/Django cache; API responses are cached per user/farm/params.
- If requests ask for ranges larger than configured limits or missing bounding boxes, the API returns validation errors without hitting the engine.
