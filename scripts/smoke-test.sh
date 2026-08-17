#!/bin/bash
# SSL Certificate Manager — Smoke Test
# Verifies the deployed application is functional end-to-end.

set -euo pipefail

BASE_URL="${BASE_URL:-https://localhost}"
API_KEY="${API_KEY:-}"

if [ -z "$API_KEY" ] && [ -f /etc/certmanager/certmanager.env ]; then
    API_KEY=$(grep '^API_KEY=' /etc/certmanager/certmanager.env | cut -d= -f2)
fi

if [ -z "$API_KEY" ]; then
    echo "ERROR: API_KEY not set. Export it or ensure /etc/certmanager/certmanager.env exists."
    exit 1
fi

PASS=0
FAIL=0

check() {
    local desc="$1"
    local result="$2"
    if [ "$result" = "0" ]; then
        echo "  ✓ ${desc}"
        PASS=$((PASS + 1))
    else
        echo "  ✗ ${desc}"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== SSL Certificate Manager Smoke Test ==="
echo "  Target: ${BASE_URL}"
echo ""

# 1. Health check (no auth)
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" "${BASE_URL}/api/v1/health")
check "Health endpoint returns 200" "$([ "$HTTP_CODE" = "200" ] && echo 0 || echo 1)"

# 2. Auth required
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" "${BASE_URL}/api/v1/ca")
check "CA endpoint returns 401 without key" "$([ "$HTTP_CODE" = "401" ] && echo 0 || echo 1)"

# 3. Auth works
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" -H "X-API-Key: ${API_KEY}" "${BASE_URL}/api/v1/ca")
check "CA endpoint returns 200 with key" "$([ "$HTTP_CODE" = "200" ] && echo 0 || echo 1)"

# 4. Create a test CA
CA_RESPONSE=$(curl -sk -X POST "${BASE_URL}/api/v1/ca" \
    -H "X-API-Key: ${API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{"subject":{"cn":"Smoke Test CA","o":"Test","ou":"","c":"GB","st":"","l":""},"key_algo":"RSA","key_size":2048,"validity_days":365,"path_length":0}')
CA_ID=$(echo "$CA_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
check "Create test CA" "$([ -n "$CA_ID" ] && echo 0 || echo 1)"

# 5. Issue a certificate
if [ -n "$CA_ID" ]; then
    CERT_RESPONSE=$(curl -sk -X POST "${BASE_URL}/api/v1/cert" \
        -H "X-API-Key: ${API_KEY}" \
        -H "Content-Type: application/json" \
        -d "{\"profile\":\"server\",\"signing_ca_id\":\"${CA_ID}\",\"subject\":{\"cn\":\"test.smoke.local\",\"o\":\"\",\"ou\":\"\",\"c\":\"\",\"st\":\"\",\"l\":\"\"},\"san\":[{\"type\":\"dns\",\"value\":\"test.smoke.local\"}],\"key_algo\":\"RSA\",\"key_size\":2048,\"validity_days\":30}")
    SERIAL=$(echo "$CERT_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('serial',''))" 2>/dev/null || echo "")
    check "Issue test certificate" "$([ -n "$SERIAL" ] && echo 0 || echo 1)"

    # 6. Download PEM
    if [ -n "$SERIAL" ]; then
        HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" -H "X-API-Key: ${API_KEY}" "${BASE_URL}/api/v1/export/${SERIAL}/pem")
        check "Download PEM format" "$([ "$HTTP_CODE" = "200" ] && echo 0 || echo 1)"

        # 7. Revoke
        HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" -X DELETE -H "X-API-Key: ${API_KEY}" "${BASE_URL}/api/v1/cert/${SERIAL}")
        check "Revoke certificate" "$([ "$HTTP_CODE" = "200" ] && echo 0 || echo 1)"
    fi
fi

# 8. Audit log
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" -H "X-API-Key: ${API_KEY}" "${BASE_URL}/api/v1/audit?page_size=5")
check "Audit log accessible" "$([ "$HTTP_CODE" = "200" ] && echo 0 || echo 1)"

# 9. Frontend served
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" "${BASE_URL}/")
check "Frontend SPA served" "$([ "$HTTP_CODE" = "200" ] && echo 0 || echo 1)"

# 10. TLS certificate valid (from tool's own CA)
TLS_SUBJECT=$(curl -sk -v "${BASE_URL}/api/v1/health" 2>&1 | grep "subject:" | head -1 || echo "")
check "TLS certificate present" "$([ -n "$TLS_SUBJECT" ] && echo 0 || echo 1)"

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
