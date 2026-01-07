# Integration HMAC authentication

This document defines the shared HMAC contract between the DRF backend and the
Nextcloud app. It is the single contract for configuration, headers, and
canonicalization.

## Environment variables

Backend (DRF):
- `INTEGRATION_HMAC_CLIENTS_JSON`
  - JSON object mapping `client_id -> secret_b64`
  - `secret_b64` must be strict base64; decoded bytes are used for HMAC
  - example (placeholders only): `{"<uuid-client-id>":"<base64-secret>"}`
- `INTEGRATION_LEGACY_CONFIG_ALLOWED` (default `False`)
  - when `False`, any legacy keys (ex: `NEXTCLOUD_HMAC_CLIENTS_JSON`) hard-fail

Client (Nextcloud):
- `INTEGRATION_HMAC_CLIENT_ID`
  - the `client_id` used to sign outbound requests to DRF
- `INTEGRATION_HMAC_CLIENTS_JSON`
  - JSON map of `client_id -> secret_b64` (strict base64)
  - stored in Nextcloud app config (admin UI) encrypted at rest, with optional
    system config (config.php) overrides

Shared knobs (backend config):
- `NEXTCLOUD_HMAC_MAX_SKEW_SECONDS` (default `300`)
- `NEXTCLOUD_HMAC_NONCE_TTL_SECONDS` (default `360`)
- `NEXTCLOUD_HMAC_CACHE_ALIAS` (default `default`)

## Required headers
- `X-Client-Id` (preferred; case-sensitive)
- `X-NC-CLIENT-ID` (legacy alias, still accepted)
- `X-NC-TIMESTAMP` (unix seconds)
- `X-NC-NONCE` (unique per request)
- `X-NC-SIGNATURE` (hex HMAC-SHA256 of the canonical string)

## Canonicalization rules
Canonical string:
```
METHOD\nPATH\nCANONICAL_QUERY\nTIMESTAMP\nNONCE\nBODY_SHA256
```
- `METHOD`: `request.method.upper()`
- `PATH`: `request.path` exactly (trailing slash matters)
- `CANONICAL_QUERY`:
  - parse the raw query string (no leading `?`), preserve duplicates
  - decode with form semantics (`+` becomes space)
  - re-encode using RFC3986 (spaces become `%20`, never `+`) with safe chars
    `-_.~`
  - sort by `(encoded_key, encoded_value)` and re-join with `&`
- `TIMESTAMP`: unix seconds string
- `NONCE`: header value exactly as received
- `BODY_SHA256`:
  - sha256 hex of raw request body bytes
  - for `GET`, hash the empty byte string (`b""`)

Signature: `HMAC_SHA256_HEX(secret_bytes, canonical_string_utf8)`.

Important:
- No redirects for signed requests (301/302 are bugs); signed path must match
  the verified path exactly.

## Rotation strategy
- Add a new `client_id -> secret_b64` entry to `INTEGRATION_HMAC_CLIENTS_JSON`.
- Update Nextcloud to use the new `INTEGRATION_HMAC_CLIENT_ID` + secret.
- Remove the old entry once requests are confirmed on the new client_id.

## Troubleshooting (reason codes)
Use `errors.code` from a `403` response:
- `missing_headers`: required signature headers are missing.
- `missing_config`: `INTEGRATION_HMAC_CLIENTS_JSON` missing or empty.
- `bad_json`: invalid JSON or non-string keys/values in the map.
- `bad_base64`: secret is not strict base64.
- `unknown_client`: `client_id` not found in `INTEGRATION_HMAC_CLIENTS_JSON`.
- `sig_mismatch`: canonical string mismatch or wrong secret.
- `body_hash_mismatch`: request body hash does not match the raw bytes sent.
- `path_mismatch`: path differs (often trailing slash or proxy rewrite).
- `method_mismatch`: signed method differs from request method.
- `skew`: timestamp outside `NEXTCLOUD_HMAC_MAX_SKEW_SECONDS`.
- `replay`: nonce reused within `NEXTCLOUD_HMAC_NONCE_TTL_SECONDS`.
