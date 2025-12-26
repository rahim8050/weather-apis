# Nextcloud HMAC runbook

This runbook complements the contract in [docs/security/nextcloud-hmac.md](nextcloud-hmac.md) by
highlighting the operational guarantees, verification steps, and response playbooks for the real
services wired up in `integrations/`.

## Purpose & guarantees
- **Integrity**: Every request is signed over `METHOD`, `PATH`, canonicalized query, timestamp,
  nonce, and the SHA-256 of the raw body (`integrations/hmac.py`, `tests/test_integrations_nextcloud_hmac.py`).
- **Authentication**: The UUID `X-Client-Id` (legacy `X-NC-CLIENT-ID` also accepted) maps to an `IntegrationClient`
  record with an active secret.
- **Anti-replay**: Nonces are cached via `CACHES[NEXTCLOUD_HMAC_CACHE_ALIAS]` with TTL `NEXTCLOUD_HMAC_NONCE_TTL_SECONDS`.
- **Rotation**: Admin workflows rotate secrets via `/api/v1/integrations/clients/{id}/rotate-secret/`, keeping the previous
  secret valid while `INTEGRATIONS_HMAC_PREVIOUS_TTL_SECONDS` has not expired (`integrations/tests/test_integration_clients.py`).

## Required headers
| Header | Description |
| --- | --- |
| `X-Client-Id` | Preferred UUID that matches `IntegrationClient.client_id`. |
| `X-NC-CLIENT-ID` | Legacy alias (still accepted for backwards compatibility). |
| `X-NC-TIMESTAMP` | Unix seconds integer for skew checks. |
| `X-NC-NONCE` | Unique string/UUID per request; replayed values are rejected by cache add. |
| `X-NC-SIGNATURE` | Hex HMAC-SHA256 over the canonical string (`integrations/hmac.py`). |

## Canonical string & signature
```
METHOD
PATH
CANONICAL_QUERY
TIMESTAMP
NONCE
BODY_SHA256
```
- `METHOD`: uppercase HTTP method.
- `PATH`: `request.path` (exact, trailing slash sensitive).
- `CANONICAL_QUERY`: parse query (`parse_qsl`), decode `+`→space, re-encode with RFC3986 safe chars `-_.~`,
  sort by `(encoded_key, encoded_value)`, rejoin with `&`, no leading `?`.
- `TIMESTAMP`, `NONCE`: headers as-is.
- `BODY_SHA256`: SHA-256 hex of raw body bytes; `GET` hashes `b""`.

Signature: `hmac.new(secret, canonical_bytes, sha256).hexdigest()`; incoming signatures are lowercased before
`hmac.compare_digest` to accept uppercase variants (`tests/test_integrations_nextcloud_hmac.py`).

## Configuration knobs
- `NEXTCLOUD_HMAC_ENABLED` (default `True`)
- `NEXTCLOUD_HMAC_MAX_SKEW_SECONDS` (default `300`)
- `NEXTCLOUD_HMAC_NONCE_TTL_SECONDS` (default `360`)
- `NEXTCLOUD_HMAC_CACHE_ALIAS` (matches a Django cache alias in `CACHES`)
- `NEXTCLOUD_HMAC_CLIENTS_JSON` (legacy `client_id -> secret` map)
- `INTEGRATIONS_HMAC_PREVIOUS_TTL_SECONDS` (default `259200` seconds = 72h overlap window for rotating secrets)

Ensure `NEXTCLOUD_HMAC_CACHE_ALIAS` points to a shared Redis/Memcached backend (not LocMem) so nonce reuse
is detected across workers.

## Provisioning a client
1. Authenticate as an admin user (JWT) and `POST /api/v1/integrations/clients/` with `{"name": "Nextcloud"}`.
2. The response includes `{ "client_id": "<uuid>", "client_secret": "<secret>" }`, and **the secret is shown only once**.
3. Store the secret securely in the Nextcloud instance configuration and never log it.
4. `IntegrationClient` metadata (name, `is_active`, timestamps) is readable via `GET /api/v1/integrations/clients/` or
   `/clients/{id}/` without exposing secrets.
5. Disable a client by setting `is_active = false` via `PATCH /clients/{id}/` to immediately block signing with both
   active and previous secrets.

## Verification recipes
_Placeholders: `<client-id>`, `<secret>`, `<nonce>`; compute canonical string as described above._

1. **Success (valid signature)**:
   ```bash
   curl -H "X-Client-Id: <client-id>" \
        -H "X-NC-TIMESTAMP: $(date +%s)" \
        -H "X-NC-NONCE: <nonce>" \
        -H "X-NC-SIGNATURE: <correct-hex>" \
        http://localhost:8000/api/v1/integrations/nextcloud/ping/
   ```
   Expect `200` with `{"status": 0, "data": {"ok": true, "client_id": "<client-id>"}}`.

2. **Missing headers**: omit `X-NC-SIGNATURE` or `X-Client-Id`; endpoint returns `403` and `errors` mention missing headers.
3. **Invalid signature**: tamper with body/query or use the wrong secret; response is `403` (`"Invalid Nextcloud signature"`).
4. **Old timestamp**: set `X-NC-TIMESTAMP` outside `NEXTCLOUD_HMAC_MAX_SKEW_SECONDS`; response is `403` with timestamp message.
5. **Replay nonce**: reuse the same `X-NC-NONCE` twice; first succeeds, second returns `403` due to nonce cache key already added.
6. **Canonical query**: sign with sorted canonical query but send unsorted raw query (`?b=2&a=1&b=1`); accepted (`canonicalize_query` test).
7. **Uppercase hex**: send uppercase `X-NC-SIGNATURE`; accepted because verifier lowercases before comparing.

## Rotation procedure
1. `POST /api/v1/integrations/clients/{id}/rotate-secret/` – rotates the secret, returns new secret + `previous_valid_until`.
2. Rotation is only allowed when `IntegrationClient.is_active` is true; concurrent calls respect a DB lock (`select_for_update`).
3. Previous secret stays valid until `previous_expires_at = now + INTEGRATIONS_HMAC_PREVIOUS_TTL_SECONDS`.
4. During overlap window both secrets validate (`tests/test_integration_clients.py`).
5. After `previous_expires_at` passes, only the new secret works; replays with the old signature return `403`.

## Troubleshooting matrix
| Symptom | Likely cause | Action |
| --- | --- | --- |
| `403` “Missing Nextcloud HMAC headers” | Required header absent | Confirm `X-Client-Id`, `X-NC-TIMESTAMP`, `X-NC-NONCE`, `X-NC-SIGNATURE` present and correctly spelled. |
| `403` “Unknown Nextcloud client_id” | `client_id` not in DB or env list | Verify `IntegrationClient` exists or update `NEXTCLOUD_HMAC_CLIENTS_JSON`. |
| `403` “Invalid Nextcloud signature” | Canonical string mismatch or wrong secret | Recompute canonical string per spec; ensure path/query/body exact as in request. |
| `403` “Nextcloud timestamp outside skew” | Clock drift or stale timestamp | Sync clocks (NTP) and ensure timestamp is within `NEXTCLOUD_HMAC_MAX_SKEW_SECONDS`. |
| `403` “Nextcloud nonce replay detected” | Nonce reused within TTL | Use fresh nonce; ensure cache alias is shared (Redis) so repeated hits are blocked. |
| `403` from old secret after rotation | Overlap TTL expired | Rotate Nextcloud config to new secret and ensure previous TTL matches expected propagation window. |

## Incident response (suspected secret leak)
1. `PATCH /api/v1/integrations/clients/{id}/` with `{"is_active": false}` to immediately reject all signatures.
2. Rotate via `POST /clients/{id}/rotate-secret/` to issue a new secret; copy the response once and update the Nextcloud instance.
3. Re-enable client (`is_active = true`) once clients are updated.
4. Review logs for `integration_client.secret_rotated` and `nextcloud_hmac.verified_with_previous_secret` to confirm usage of old secrets.

## Production readiness checklist
- ✅ Shared cache backend (Redis/Memcached) configured via `NEXTCLOUD_HMAC_CACHE_ALIAS` to enforce replay protection.
- ✅ NTP-synced hosts so `NEXTCLOUD_HMAC_MAX_SKEW_SECONDS` (default 300s) is sufficient.
- ✅ Monitoring/alerting on `403` spikes from `/api/v1/integrations/nextcloud/ping/` (logs already show failure reasons).
- ✅ Rotation playbooks in place; operators know to rotate via `/clients/{id}/rotate-secret/` and update downstream configs within the overlap TTL.
- ✅ Secrets stored securely and never logged; only the creation + rotation responses expose a secret, once.
