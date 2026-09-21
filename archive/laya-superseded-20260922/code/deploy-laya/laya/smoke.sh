#!/usr/bin/env bash
# CourseMate Laya inference service — smoke probe (curl).
# Run against a running service (real or fake). The request body below matches
# deploy/laya/laya-definitions.example.json; edit both together.
set -uo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8105}"
TOKEN="${TOKEN:-}"
AUTH=()
if [[ -n "$TOKEN" ]]; then
  AUTH=(-H "Authorization: Bearer $TOKEN")
fi

REV="1c5edc17a7acd8701df6fc341c0d179f1c62c982"
PASS=0
FAIL=0

check() {
  local label="$1" expected="$2" actual="$3" body="$4"
  if [[ "$actual" == "$expected" ]]; then
    echo "PASS  $label (HTTP $actual)"
    PASS=$((PASS + 1))
  else
    echo "FAIL  $label (expected HTTP $expected, got $actual): $(printf '%s' "$body" | head -c 300)"
    FAIL=$((FAIL + 1))
  fi
}

# 1. liveness (before/independent of readiness)
code=$(curl -s -o /tmp/laya-live.json -w '%{http_code}' "$BASE_URL/health/live")
check "/health/live" 200 "$code" "$(cat /tmp/laya-live.json 2>/dev/null)"

# 2. readiness
code=$(curl -s -o /tmp/laya-ready.json -w '%{http_code}' "$BASE_URL/health/ready")
check "/health/ready" 200 "$code" "$(cat /tmp/laya-ready.json 2>/dev/null)"

# 3. model-info (authenticated)
code=$(curl -s -o /tmp/laya-info.json -w '%{http_code}' "${AUTH[@]}" "$BASE_URL/internal/v1/model-info")
check "/internal/v1/model-info" 200 "$code" "$(cat /tmp/laya-info.json 2>/dev/null)"

# 4. one accepted decision
BODY=$(cat <<JSON
{
  "request_id": "smoke-0001",
  "decision_definition_id": "course-triage",
  "definition_version": "1",
  "compiled_state": {"body": "billed twice, please refund"},
  "questions": {
    "department": {"type": "choice", "instructions": "Which department?", "criteria": {"billing": "payments, refunds", "technical": "bugs, outages"}},
    "churn": {"type": "noul", "instructions": "Does the user threaten to cancel?"}
  },
  "deadline_ms": 5000,
  "model_revision": "$REV",
  "compiler_version": "1.0.0"
}
JSON
)
code=$(curl -s -o /tmp/laya-dec.json -w '%{http_code}' "${AUTH[@]}" -H 'Content-Type: application/json' -d "$BODY" "$BASE_URL/internal/v1/decisions")
check "decision (OK)" 200 "$code" "$(cat /tmp/laya-dec.json 2>/dev/null)"

# 5. rejected oversized body
BIG=$(python3 -c 'import json; print(json.dumps({"request_id":"smoke-big","decision_definition_id":"course-triage","definition_version":"1","compiled_state":"x"*3000000,"questions":{},"deadline_ms":5000,"model_revision":"'$REV'","compiler_version":"1.0.0"}))')
code=$(curl -s -o /tmp/laya-big.json -w '%{http_code}' "${AUTH[@]}" -H 'Content-Type: application/json' -d "$BIG" "$BASE_URL/internal/v1/decisions")
check "oversized body" 413 "$code" "$(cat /tmp/laya-big.json 2>/dev/null)"

# 6. deadline exceeded (tiny deadline -> 408)
FAST=$(printf '%s' "$BODY" | python3 -c 'import json,sys; d=json.load(sys.stdin); d["request_id"]="smoke-deadline"; d["deadline_ms"]=1; print(json.dumps(d))')
code=$(curl -s -o /tmp/laya-deadline.json -w '%{http_code}' "${AUTH[@]}" -H 'Content-Type: application/json' -d "$FAST" "$BASE_URL/internal/v1/decisions")
check "deadline exceeded" 408 "$code" "$(cat /tmp/laya-deadline.json 2>/dev/null)"

# 7. auth required (no token)
code=$(curl -s -o /tmp/laya-noauth.json -w '%{http_code}' "$BASE_URL/internal/v1/model-info")
check "auth required" 401 "$code" "$(cat /tmp/laya-noauth.json 2>/dev/null)"

echo
echo "smoke: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
