# Nextcloud HMAC runbook

This runbook complements the contract in
[docs/security/nextcloud-hmac.md](nextcloud-hmac.md) by highlighting the
operational guarantees, verification steps, and response playbooks for the
services wired up in `integrations/`.

## Purpose & guarantees
- **Integrity**: Every request is signed over `METHOD`, `PATH`, canonicalized
  query, timestamp, nonce, and the SHA-256 of the raw body
  (`integrations/hmac.py`, `tests/test_integrations_nextcloud_hmac.py`).
- **Authentication**: `X-Client-Id` (legacy `X-NC-CLIENT-ID` accepted) must
  exist as a key in `INTEGRATION_HMAC_CLIENTS_JSON`.
- **Anti-replay**: Nonces are cached via `CACHES[NEXTCLOUD_HMAC_CACHE_ALIAS]`
  with TTL `NEXTCLOUD_HMAC_NONCE_TTL_SECONDS`.
- **Rotation**: Update `INTEGRATION_HMAC_CLIENTS_JSON` and Nextcloud config;
  keep the old entry until cutover is complete.

## Required headers
| Header | Description |
| --- | --- |
| `X-Client-Id` | Client identifier that exists in `INTEGRATION_HMAC_CLIENTS_JSON`. |
| `X-NC-CLIENT-ID` | Legacy alias (still accepted). |
| `X-NC-TIMESTAMP` | Unix seconds integer for skew checks. |
| `X-NC-NONCE` | Unique string/UUID per request; replayed values are rejected. |
| `X-NC-SIGNATURE` | Hex HMAC-SHA256 over the canonical string. |

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
- `CANONICAL_QUERY`: parse query (`parse_qsl`), decode `+`→space, re-encode with
  RFC3986 safe chars `-_.~`, sort by `(encoded_key, encoded_value)`, rejoin
  with `&`, no leading `?`.
- `TIMESTAMP`, `NONCE`: headers as-is.
- `BODY_SHA256`: SHA-256 hex of raw body bytes; `GET` hashes `b""`.

Signature: `hmac.new(secret_bytes, canonical_bytes, sha256).hexdigest()`.
Incoming signatures are lowercased before `hmac.compare_digest` to accept
uppercase variants.

## Configuration knobs
- `NEXTCLOUD_HMAC_ENABLED` (default `True`)
- `NEXTCLOUD_HMAC_MAX_SKEW_SECONDS` (default `300`)
- `NEXTCLOUD_HMAC_NONCE_TTL_SECONDS` (default `360`)
- `NEXTCLOUD_HMAC_CACHE_ALIAS` (matches a Django cache alias in `CACHES`)
- `INTEGRATION_HMAC_CLIENTS_JSON` (JSON map `client_id -> secret_b64`)
- `INTEGRATION_LEGACY_CONFIG_ALLOWED` (default `False`)
  - when `False`, presence of legacy `NEXTCLOUD_HMAC_CLIENTS_JSON` causes a
    hard failure until removed

Ensure `NEXTCLOUD_HMAC_CACHE_ALIAS` points to a shared Redis/Memcached backend
(not LocMem) so nonce reuse is detected across workers.

## Provisioning a client
1. Generate a new `client_id` (UUID recommended) and random secret bytes.
2. Base64-encode the secret and set `INTEGRATION_HMAC_CLIENTS_JSON`:
   `{"<client-id>":"<base64-secret>"}`.
3. Store `INTEGRATION_HMAC_CLIENT_ID` and the base64 secret in Nextcloud app
   config (admin UI, encrypted at rest), with optional system config
   (`config.php`) overrides for automation.
4. Remove any legacy config keys; keep `INTEGRATION_LEGACY_CONFIG_ALLOWED=false`.

## Verification recipes
_Placeholders: `<client-id>`, `<secret>`, `<nonce>`; compute the canonical
string as described above._

1. **Success (valid signature)**:
   ```bash
   curl -H "X-Client-Id: <client-id>" \
        -H "X-NC-TIMESTAMP: $(date +%s)" \
        -H "X-NC-NONCE: <nonce>" \
        -H "X-NC-SIGNATURE: <correct-hex>" \
        http://localhost:8000/api/v1/integrations/nextcloud/ping/
   ```
   Expect `200` with `{"status": 0, "data": {"ok": true, "client_id": "<client-id>"}}`.

2. **Missing headers**: omit `X-NC-SIGNATURE` or `X-Client-Id`; endpoint returns
   `403` and `errors.code=missing_headers`.
3. **Invalid signature**: tamper with body/query or use the wrong secret;
   response is `403` with `errors.code=sig_mismatch`.
4. **Skew**: set `X-NC-TIMESTAMP` outside `NEXTCLOUD_HMAC_MAX_SKEW_SECONDS`;
   response is `403` with `errors.code=skew`.
5. **Replay nonce**: reuse the same `X-NC-NONCE` twice; first succeeds, second
   returns `403` with `errors.code=replay`.
6. **Canonical query**: sign with sorted canonical query but send unsorted raw
   query (`?b=2&a=1&b=1`); accepted (`canonicalize_query` test).
7. **Uppercase hex**: send uppercase `X-NC-SIGNATURE`; accepted.

## Rotation procedure
1. Add a new `client_id -> secret_b64` entry in `INTEGRATION_HMAC_CLIENTS_JSON`.
2. Update Nextcloud to use the new `client_id` and secret.
3. Remove the old entry once requests are confirmed on the new client.

## Troubleshooting matrix
| Symptom | Likely cause | Action |
| --- | --- | --- |
| `errors.code=missing_headers` | Required headers absent | Confirm header names and values. |
| `errors.code=missing_config` / `bad_json` | Missing/invalid `INTEGRATION_HMAC_CLIENTS_JSON` | Fix JSON and deploy. |
| `errors.code=bad_base64` | Secret is not strict base64 | Re-encode secret (no whitespace). |
| `errors.code=unknown_client` | `client_id` not in `INTEGRATION_HMAC_CLIENTS_JSON` | Verify client_id mapping. |
| `errors.code=sig_mismatch` | Canonical mismatch or wrong secret | Recompute canonical string and secret. |
| `errors.code=body_hash_mismatch` | Body hash does not match raw bytes | Sign exact request body bytes. |
| `errors.code=path_mismatch` | Path differs (often trailing slash/redirect) | Use exact path; avoid redirects. |
| `errors.code=method_mismatch` | Signed method differs | Sign the actual HTTP method. |
| `errors.code=skew` | Clock drift / stale timestamp | Sync clocks (NTP). |
| `errors.code=replay` | Nonce reused within TTL | Use a fresh nonce. |

## Incident response (suspected secret leak)
1. Remove the compromised `client_id` from `INTEGRATION_HMAC_CLIENTS_JSON`.
2. Create a new `client_id` + secret and update Nextcloud configuration.
3. Review logs for `nextcloud_hmac.denied` spikes and reason codes.

## Production readiness checklist
- ✅ Shared cache backend configured via `NEXTCLOUD_HMAC_CACHE_ALIAS`.
- ✅ NTP-synced hosts so `NEXTCLOUD_HMAC_MAX_SKEW_SECONDS` is sufficient.
- ✅ Monitoring on `403` spikes from `/api/v1/integrations/nextcloud/ping/` with
  `errors.code` breakdowns.
- ✅ `INTEGRATION_HMAC_CLIENTS_JSON` managed via secrets manager; legacy config
  removed or explicitly allowed during migration.
