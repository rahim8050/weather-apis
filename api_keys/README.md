# API Keys

This app implements first-party API keys for authenticating requests via the
`X-API-Key` header and associates each key with a user account.

## What exists today

- API key model: `api_keys.models.ApiKey`
- API key authentication: `api_keys.auth.ApiKeyAuthentication`
- Key lifecycle endpoints (JWT-only): `api_keys.views.ApiKeyView`,
  `api_keys.views.ApiKeyRevokeView`, `api_keys.views.ApiKeyRotateView`
- Per-key throttling: `api_keys.throttling.ApiKeyRateThrottle`
- Generic scope enforcement (not globally applied yet):
  `api_keys.permissions.ApiKeyScopePermission`

## Scopes (least privilege)

Scopes live on the `ApiKey.scope` field with these values:

- `read` (default): safe/read-only endpoints
- `write`: endpoints that mutate state (POST/PUT/PATCH/DELETE)
- `admin`: reserved for privileged operations (optional future use)

### Scope rules (generic)

`ApiKeyScopePermission` enforces the following:

- If `request.auth` is **not** an `ApiKey` (e.g., JWT auth), it allows the
  request unchanged.
- If `request.auth` **is** an `ApiKey`:
  - SAFE methods (`GET`, `HEAD`, `OPTIONS`) require `read` or `write` (or
    `admin`).
  - Unsafe methods require `write` (or `admin`).

This permission is intentionally generic so other apps (e.g. NDVI) can opt in
per-endpoint without changing global behavior.

## How to wire scopes into other apps (future NDVI wiring)

When you add an endpoint that should allow API keys, do **both** of the
following:

1. Ensure API key authentication can run (either by using default auth classes
   or explicitly adding it).
2. Add `ApiKeyScopePermission` to restrict API-key requests to the appropriate
   scope.

### Example: APIView (read-only)

```python
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from api_keys.permissions import ApiKeyScopePermission


class NdviReadView(APIView):
    permission_classes = (AllowAny, ApiKeyScopePermission)

    def get(self, request, *args, **kwargs):
        ...
```

### Example: APIView (write endpoint)

```python
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from api_keys.permissions import ApiKeyScopePermission


class NdviWriteView(APIView):
    permission_classes = (AllowAny, ApiKeyScopePermission)

    def post(self, request, *args, **kwargs):
        ...
```

Notes:
- `ApiKeyScopePermission` only *restricts* API key callers. JWT callers are not
  affected.
- If an endpoint should be JWT-only, keep it JWT-only (do not add API key
  authentication).

### Suggested tests when wiring NDVI

Add tests mirroring `tests/test_api_keys.py` patterns:

- `test_ndvi_read_allows_read_scope_key`
- `test_ndvi_write_requires_write_scope_key`
- `test_ndvi_jwt_bypasses_scope_permission`

## Key creation & rotation payloads

Key lifecycle endpoints are JWT-only by design.

- Create: `POST /api/v1/keys/`
  - accepts `name`, optional `expires_at`, optional `scope`
  - returns plaintext `api_key` only once
- Rotate: `POST /api/v1/keys/<uuid>/rotate/`
  - accepts optional `name`, optional `expires_at`, optional `scope`
  - revokes old key immediately, returns new plaintext once
- List: `GET /api/v1/keys/`
  - returns metadata only (never returns plaintext or `key_hash`)

## `last_used_at` tracking (low-write)

`ApiKey.last_used_at` is updated only on successful API key authentication,
and at most once per 5 minutes per key.

This is implemented in `ApiKeyAuthentication.authenticate` using a
`QuerySet.update()` filter that only writes when:

- `last_used_at` is `NULL`, or
- `last_used_at` is older than the write interval

This avoids a database write on every request in production.

## Audit logging (no plaintext leakage)

Audit events are emitted via the `api_keys` logger. Events include:

- `api_key.created` / `api_key.revoked` / `api_key.rotated`
- `api_key.auth.success` / `api_key.auth.failure` / `api_key.auth.missing`

Logs include: user_id, key_id (when available), request path/method,
status code, client IP (best-effort), and user-agent (best-effort).

Plaintext API keys must never be logged.

## Throttling envelope (429)

When DRF raises `Throttled`, the global exception handler wraps the response in
the project’s standard envelope:

```json
{
  "status": 1,
  "message": "Too Many Requests",
  "data": null,
  "errors": { "detail": "...", "wait": 12 }
}
```

This keeps rate-limit errors consistent with other API error responses.

