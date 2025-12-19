# Weather app

Back to root: `../README.md`

## Overview

This app exposes provider-backed weather endpoints under `/api/v1/weather/…`
with a small service layer for provider selection, caching, and metrics.

It is not responsible for authentication primitives (see `accounts/` and
`api_keys/`) and does not manage farms (see `farms/`).

## Key concepts / data model

This app is provider-integrations + normalized response types (no DB models).

Normalized types (from code: `weather/engines/types.py`):
- `Location(lat, lon, tz)`
- `CurrentWeather(observed_at, temperature_c, wind_speed_mps, source)`
- `DailyForecast(day, t_min_c, t_max_c, precipitation_mm, source)`
- `WeeklyReport(week_start, week_end, t_min_avg_c, t_max_avg_c, precipitation_sum_mm, days, source)`

Supported providers (from code: `weather/engines/registry.py`):
- `open_meteo`
- `nasa_power`

## API surface

Base path: `/api/v1/weather/` (from code: `weather/urls.py` and `config/urls.py`).

All successful responses use the project envelope produced by
`config.api.responses.success_response`:

```json
{ "status": 0, "message": "string", "data": {}, "errors": null }
```

| Method | Path | Auth | Purpose | Key params |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/weather/current/` | JWT or `X-API-Key` | Current conditions | query: `lat`, `lon`, optional `tz`, optional `provider` |
| GET | `/api/v1/weather/daily/` | JWT or `X-API-Key` | Daily min/max/precip | query: `lat`, `lon`, `start`, `end`, optional `tz`, optional `provider` |
| GET | `/api/v1/weather/weekly/` | JWT or `X-API-Key` | Weekly aggregates | query: `lat`, `lon`, `start`, `end`, optional `tz`, optional `provider` |

### Examples

#### Current

```bash
curl -sS 'http://localhost:8000/api/v1/weather/current/?lat=-1.2864&lon=36.8172&tz=Africa/Nairobi&provider=open_meteo' \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Response:

```json
{
  "status": 0,
  "message": "OK",
  "data": {
    "observed_at": "2025-01-02T10:00:00+03:00",
    "temperature_c": 24.2,
    "wind_speed_mps": 3.5,
    "source": "open_meteo"
  },
  "errors": null
}
```

#### Daily

```bash
curl -sS 'http://localhost:8000/api/v1/weather/daily/?lat=-1.2864&lon=36.8172&start=2025-01-01&end=2025-01-07&tz=Africa/Nairobi' \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Response:

```json
{
  "status": 0,
  "message": "OK",
  "data": { "forecasts": [{ "day": "2025-01-01", "t_min_c": null }] },
  "errors": null
}
```

#### Weekly

```bash
curl -sS 'http://localhost:8000/api/v1/weather/weekly/?lat=-1.2864&lon=36.8172&start=2025-01-01&end=2025-01-31&tz=Africa/Nairobi' \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Response:

```json
{
  "status": 0,
  "message": "OK",
  "data": { "reports": [{ "week_start": "2024-12-30", "week_end": "2025-01-05" }] },
  "errors": null
}
```

## Business logic

- Provider registry + allowlist validation: `weather/engines/registry.py`
- Provider selection: query `provider=...` overrides default
  `WEATHER_PROVIDER_DEFAULT` (from code: `weather/services.py`)
- Caching:
  - Uses Django cache `caches["default"]`
  - Cache keys include provider, rounded lat/lon, timezone, and (for ranged
    endpoints) start/end (from code: `weather/services.py`)
- Weekly aggregation:
  - Derived from daily forecasts
  - Buckets weeks Monday→Sunday using the requested timezone’s calendar days
    (from code: `weather/services.py`)

Provider notes:
- Open-Meteo:
  - Requests pass `timezone=<tz>` (from code: `weather/engines/open_meteo.py`)
- NASA POWER:
  - Requests set `time-standard=UTC` (from code: `weather/engines/nasa_power.py`)
  - `current` is derived from the latest available daily value from a small
    local-day window (today and yesterday; from code: `weather/engines/nasa_power.py`)

## AuthZ / permissions

- Views use `IsAuthenticated` (from code: `weather/views.py`).
- Authentication comes from DRF defaults (JWT + API key; from code:
  `config/settings.py`).

## Settings / env vars

Weather-related settings are read in `config/settings.py`:

- `WEATHER_PROVIDER_DEFAULT`
- `WEATHER_DEFAULT_TZ`
- `OPEN_METEO_BASE_URL`
- `NASA_POWER_BASE_URL`
- `WEATHER_CACHE_TTL_CURRENT_S`, `WEATHER_CACHE_TTL_DAILY_S`, `WEATHER_CACHE_TTL_WEEKLY_S`
- `WEATHER_MAX_RANGE_DAYS`

## Background jobs

None.

## Metrics / monitoring

The service layer emits Prometheus metrics (from code: `weather/metrics.py`):

- `weather_provider_requests_total{provider,endpoint}`
- `weather_provider_errors_total{provider,endpoint,error_type}`
- `weather_provider_latency_seconds{provider,endpoint}`
- `weather_cache_hits_total{provider,endpoint}`
- `weather_cache_misses_total{provider,endpoint}`

## Testing

- Tests live in `weather/tests/test_weather.py`.
- Run: `pytest weather/tests/test_weather.py`

