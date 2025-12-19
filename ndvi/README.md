# NDVI app

Back to root: `../README.md`

## Overview

This app provides NDVI retrieval for user-owned farms using a provider engine
(currently Sentinel Hub) and exposes endpoints under `/api/v1/…/ndvi/`.

It is responsible for:
- NDVI timeseries/latest endpoints and response caching
- Job creation, idempotency, and Celery task execution
- Raster artifact storage and raster retrieval/queueing endpoints

It is not responsible for:
- Farm ownership and bounding box persistence (see `farms/`)
- Authentication primitives (see `accounts/` and `api_keys/`)

## Key concepts / data model

Models (from code: `ndvi/models.py`):

- `NdviObservation`: materialized NDVI observation for a farm and `bucket_date`.
- `NdviJob`: idempotent job record tracked for Celery tasks.
- `NdviRasterArtifact`: persisted PNG raster artifact for a farm/date/size/cloud.

## API surface

Routes (from code: `ndvi/urls.py` and `config/urls.py`):

All successful JSON responses use the project envelope produced by
`config.api.responses.success_response`:

```json
{ "status": 0, "message": "string", "data": {}, "errors": null }
```

AuthZ notes:
- All farm-scoped endpoints enforce “owner-only” access by fetching farms with
  `owner_id=request.user.id` and `is_active=True` (from code: `ndvi/views.py`).
- Unauthorized access to another user’s farm appears as `404` (from code:
  `ndvi/views.py` and `ndvi/tests/test_ndvi.py`).

| Method | Path | Auth | Purpose | Key params |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/farms/<farm_id>/ndvi/timeseries/` | JWT or `X-API-Key` | NDVI timeseries (cached; may enqueue gap-fill) | query: `start`, `end`, optional `step_days`, optional `max_cloud` |
| GET | `/api/v1/farms/<farm_id>/ndvi/latest/` | JWT or `X-API-Key` | Latest observation (cached; may enqueue refresh) | query: optional `lookback_days`, optional `max_cloud` |
| POST | `/api/v1/farms/<farm_id>/ndvi/refresh/` | JWT or `X-API-Key` | Manual refresh trigger (cooldown) | no body |
| GET | `/api/v1/farms/<farm_id>/ndvi/raster.png` | JWT or `X-API-Key` | Fetch raster PNG (binary) | query: `date`, optional `size`, optional `max_cloud` |
| POST | `/api/v1/farms/<farm_id>/ndvi/raster/queue` | JWT or `X-API-Key` | Queue raster render job (cooldown) | body: `date`, optional `size`, optional `max_cloud` |
| GET | `/api/v1/ndvi/jobs/<job_id>/` | JWT or `X-API-Key` | Job status for current user | path: `job_id` |

### Examples

#### Timeseries

```bash
curl -sS \
  "http://localhost:8000/api/v1/farms/$FARM_ID/ndvi/timeseries/?start=2024-01-01&end=2024-01-15&step_days=7&max_cloud=30" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Response:

```json
{
  "status": 0,
  "message": "NDVI time series",
  "data": {
    "observations": [{ "bucket_date": "2024-01-01", "mean": 0.1 }],
    "engine": "sentinelhub",
    "is_partial": true,
    "missing_buckets_count": 2
  },
  "errors": null
}
```

#### Latest

```bash
curl -sS \
  "http://localhost:8000/api/v1/farms/$FARM_ID/ndvi/latest/?lookback_days=14&max_cloud=30" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Response:

```json
{
  "status": 0,
  "message": "Latest NDVI",
  "data": { "observation": null, "stale": true, "engine": "sentinelhub" },
  "errors": null
}
```

#### Manual refresh

```bash
curl -sS -X POST "http://localhost:8000/api/v1/farms/$FARM_ID/ndvi/refresh/" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Response (queued):

```json
{
  "status": 0,
  "message": "Refresh queued",
  "data": { "job_id": 123 },
  "errors": null
}
```

#### Raster PNG (binary)

```bash
curl -sS -D- \
  "http://localhost:8000/api/v1/farms/$FARM_ID/ndvi/raster.png?date=2024-03-03&size=256&max_cloud=25" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -o ndvi.png
```

Response:
- `200` with `Content-Type: image/png` and `ETag` header, or
- `304` if `If-None-Match` matches the current artifact hash, or
- `404` error envelope if the raster is not found (from code: `ndvi/views.py`)

#### Raster queue

```bash
curl -sS -X POST "http://localhost:8000/api/v1/farms/$FARM_ID/ndvi/raster/queue" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"date":"2024-03-03","size":256,"max_cloud":25}'
```

Response (queued):

```json
{
  "status": 0,
  "message": "Raster render queued",
  "data": { "job_id": 456 },
  "errors": null
}
```

#### Job status

```bash
curl -sS "http://localhost:8000/api/v1/ndvi/jobs/$JOB_ID/" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Response:

```json
{ "status": 0, "message": "Job status", "data": { "status": "queued" }, "errors": null }
```

## Business logic

High-level flow:
- Validate request params via DRF serializers (`ndvi/serializers.py`).
- Validate farm bbox and enforce quota (`ndvi/services.py`).
- Return cached response if present (timeseries/latest caches in
  `ndvi/services.py`).
- Enqueue jobs for missing data:
  - Timeseries can enqueue `gap_fill`
  - Latest can enqueue `refresh_latest`
  - Manual refresh and raster queue always enqueue (subject to cooldown)
  (from code: `ndvi/views.py`)

Jobs and idempotency:
- `enqueue_job()` writes an `NdviJob` keyed by a request hash so identical
  requests create a single active job (from code: `ndvi/services.py`).
- `run_ndvi_job` acquires a distributed lock in cache to prevent duplicate
  upstream calls (from code: `ndvi/tasks.py` and `ndvi/services.py`).

Provider engines:
- Timeseries/latest engine: `ndvi/engines/sentinelhub.py` (Statistics API).
  - Uses UTC `Z` time ranges in request payloads (from code:
    `ndvi/engines/sentinelhub.py`).
- Raster engine: configured by `NDVI_RASTER_ENGINE_PATH` and resolved in
  `ndvi/raster/registry.py`; default is the Sentinel Hub raster engine (from
  code: `ndvi/raster/registry.py` and `config/settings.py`).

## AuthZ / permissions

- `IsAuthenticated` on all NDVI endpoints (from code: `ndvi/views.py`).
- Farm ownership enforced by `_get_farm()` which filters by `owner_id` and
  `is_active` (from code: `ndvi/views.py`).

## Settings / env vars

Settings read from `config/settings.py` (non-exhaustive; see that file for full
list):

- `NDVI_ENGINE`
- `NDVI_MAX_AREA_KM2`, `NDVI_MAX_DATERANGE_DAYS`
- `NDVI_DEFAULT_STEP_DAYS`, `NDVI_DEFAULT_MAX_CLOUD`, `NDVI_DEFAULT_LOOKBACK_DAYS`
- `NDVI_CACHE_TTL_TIMESERIES_SECONDS`, `NDVI_CACHE_TTL_LATEST_SECONDS`
- `NDVI_LOCK_TIMEOUT_SECONDS`
- `NDVI_MANUAL_REFRESH_COOLDOWN_SECONDS`
- Raster settings:
  - `NDVI_RASTER_ENGINE_PATH`, `NDVI_RASTER_ENGINE_NAME`
  - `NDVI_RASTER_DEFAULT_SIZE`, `NDVI_RASTER_MAX_SIZE`
  - `NDVI_RASTER_MANUAL_QUEUE_COOLDOWN_SECONDS`
  - `NDVI_RASTER_CACHE_TTL_SECONDS`

Sentinel Hub credentials are read from environment variables (from code:
`ndvi/engines/sentinelhub.py`):
- `SENTINELHUB_CLIENT_ID`
- `SENTINELHUB_CLIENT_SECRET`
- `SENTINELHUB_BASE_URL` (optional; defaults to `https://services.sentinel-hub.com`)

## Background jobs

Celery tasks (from code: `ndvi/tasks.py`):

- `ndvi.tasks.run_ndvi_job` (retries: `max_retries=3`, `default_retry_delay=60`)
- `ndvi.tasks.enqueue_daily_refresh`
- `ndvi.tasks.enqueue_weekly_gap_fill`

Celery beat schedules are configured in `config/settings.py` under
`CELERY_BEAT_SCHEDULE`.

## Metrics / monitoring

Prometheus metrics (from code: `ndvi/metrics.py`):

- `ndvi_jobs_total{status,type,engine}`
- `ndvi_upstream_requests_total{engine,outcome}`
- `ndvi_upstream_latency_seconds{engine}`
- `ndvi_cache_hit_total{layer}`
- `ndvi_farms_stale_total{engine}`

## Testing

- API tests: `ndvi/tests/test_ndvi.py`
- Raster tests: `ndvi/tests/test_ndvi_raster_png.py`
- Run: `pytest ndvi/tests/`

