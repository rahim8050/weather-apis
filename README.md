# Weather APIs

## Project Overview

- Django REST API that issues JWTs, lets users register/login, and manages long-lived API keys tied to each user.
- JWTs are for end-user sessions and for managing API keys; API keys are for service-to-service calls authenticated as the owning user.
- API key lifecycle (list/create/revoke/rotate) is strictly JWT-gated; API-key clients consume other authenticated endpoints that allow API-key auth.

## Authentication

- **JWT (Authorization: Bearer)** — returned by `/api/v1/auth/register/` and `/api/v1/auth/login/`, refreshed via `/api/v1/auth/token/refresh/`. Used by human users and required for API key management under `/api/v1/keys/`.
- **API key (X-API-Key)** — authenticates as the owning user for service calls where API-key auth is allowed. API keys cannot manage other API keys; the `/api/v1/keys/` endpoints only accept JWTs.
- Open endpoints (`/api/v1/auth/register/`, `/api/v1/auth/login/`, `/api/v1/auth/token/refresh/`) do not require authentication.

## API Documentation

- Swagger UI: `/api/docs/`
- ReDoc: `/api/redoc/`
- Raw schema (OpenAPI 3): `/api/schema/`

## Rate Limiting

- Per-API-key throttling uses the `api_key` scope with a default of `1000/min` (override via `API_KEY_THROTTLE_RATE`). Each API key is counted independently.
- User-level limits: anon `100/min`, authenticated user `1000/min`, register `5/min`, login `10/min`, token refresh `20/min`.

## Security Guarantees

- Plaintext API keys are returned only at creation/rotation time; they cannot be retrieved afterward.
- API keys are stored hashed and peppered (`DJANGO_API_KEY_PEPPER`) and compared using a peppered hash.
- Revoked or expired keys are rejected during authentication.

## Local Development

- Required environment: `DJANGO_SECRET_KEY`; for production also set a strong `DJANGO_API_KEY_PEPPER` and `REDIS_URL`.
- Common environment options: `DJANGO_DEBUG` (default `False`), `DJANGO_ALLOWED_HOSTS`, `DJANGO_CORS_ALLOWED_ORIGINS`, `DATABASE_URL` (defaults to SQLite), `API_KEY_THROTTLE_RATE` (default `1000/min`).
- Install deps: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Migrate database: `python manage.py migrate`
- Run server: `python manage.py runserver` (schema/docs available once running)
- Run tests and checks locally: see Quality Gates below.

## Quality Gates

- `pytest -q`
- `python -m mypy .`
- `ruff format .`
- `ruff check .`
- `bandit -q -r .`
