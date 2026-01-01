#!/usr/bin/env bash
set -euo pipefail

: "${BASE_URL:?set BASE_URL e.g. http://127.0.0.1:8001}"
: "${CLIENT_ID:?set CLIENT_ID (must match DRF settings key)}"
: "${API_KEY:?set API_KEY (wk_live_...)}"
: "${HMAC_SECRET:?set HMAC_SECRET (plaintext secret)}"

TOKEN_PATH="${TOKEN_PATH:-/api/v1/integrations/token/}"
WHOAMI_PATH="${WHOAMI_PATH:-/api/v1/integrations/whoami/}"
QUERY="${QUERY:-}"
BODY="${BODY:-}"

TS="$(date +%s)"
NONCE="$(python -c 'import uuid; print(uuid.uuid4())')"

# sha256(body) as hex
BODY_SHA="$(printf "%s" "$BODY" | openssl dgst -sha256 -binary | xxd -p -c 256)"

# canonical = method \n path \n query \n ts \n nonce \n body_sha
CANONICAL="$(printf "POST\n%s\n%s\n%s\n%s\n%s" "$TOKEN_PATH" "$QUERY" "$TS" "$NONCE" "$BODY_SHA")"

SIG_HEX="$(printf "%s" "$CANONICAL" \
  | openssl dgst -sha256 -mac HMAC -macopt key:"$HMAC_SECRET" -binary \
  | xxd -p -c 256)"

echo "canonical_sha256=$(printf "%s" "$CANONICAL" | openssl dgst -sha256 | awk "{print \$2}")"
echo "sig_hex_len=${#SIG_HEX}"

JWT_JSON="$(curl -sS -X POST "${BASE_URL}${TOKEN_PATH}" \
  -H "X-Client-Id: ${CLIENT_ID}" \
  -H "X-Timestamp: ${TS}" \
  -H "X-Nonce: ${NONCE}" \
  -H "X-Signature: ${SIG_HEX}" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  --data "${BODY}")"

echo "token_json=${JWT_JSON}"

JWT="$(python -c 'import sys,json
j=json.loads(sys.stdin.read())
print((j.get("data") or {}).get("access") or j.get("access") or j.get("token") or "")' <<<"$JWT_JSON")"

echo "jwt_len=${#JWT}"

if [[ -z "${JWT}" ]]; then
  echo "ERROR: JWT extraction failed (expected data.access)."
  exit 2
fi

echo
echo "---- WHOAMI ----"
curl -sS -i "${BASE_URL}${WHOAMI_PATH}" \
  -H "Authorization: Bearer ${JWT}" \
  -H "Accept: application/json"
echo
