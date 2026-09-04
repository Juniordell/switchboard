#!/usr/bin/env bash
#
# T3.5 smoke: every tool, over HTTP, with curl, against the loaded database.
#
#   ./scripts/smoke_tools.sh
#
# Starts its own uvicorn on SMOKE_PORT, waits for /health, drives all
# thirteen tools, cleans up the rows the write tools committed, and stops
# the server. Exits non-zero on the first real failure.
#
# Twelve of the thirteen answer from Postgres. `search_notes` also makes a
# real embedding call (OPENAI_API_KEY), and `web_search` is the one tool
# that touches no local data at all - without TAVILY_API_KEY it is reported
# as SKIPPED rather than quietly passed.
#
# No jq: this parses with python3, which is already required to run anything
# else here.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SMOKE_PORT="${SMOKE_PORT:-8099}"
BASE="http://127.0.0.1:${SMOKE_PORT}"
CALL_ID="call_smoke_$$"

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

PASS=0
FAIL=0
SKIP=0
FAILED_TOOLS=()

green() { printf '\033[32m%s\033[0m' "$1"; }
red() { printf '\033[31m%s\033[0m' "$1"; }
yellow() { printf '\033[33m%s\033[0m' "$1"; }

# --- server -----------------------------------------------------------------

SERVER_PID=""
cleanup() {
    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" 2>/dev/null
        wait "$SERVER_PID" 2>/dev/null
    fi
}
trap cleanup EXIT

echo "starting uvicorn on :${SMOKE_PORT}"
uv run uvicorn switchboard_api.main:app --port "$SMOKE_PORT" --log-level warning \
    >/tmp/smoke_uvicorn.log 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 40); do
    if curl -sf "${BASE}/health" >/dev/null 2>&1; then break; fi
    sleep 0.25
done

if ! curl -sf "${BASE}/health" >/dev/null 2>&1; then
    red "server never came up"; echo
    cat /tmp/smoke_uvicorn.log
    exit 1
fi
echo "health: $(curl -s "${BASE}/health")"
echo

# --- helpers ----------------------------------------------------------------

# field <json> <dotted.path> - prints the value, or nothing if absent.
field() {
    python3 -c '
import json, sys
doc = json.loads(sys.argv[1])
for part in sys.argv[2].split("."):
    if isinstance(doc, list):
        if not part.isdigit() or int(part) >= len(doc):
            sys.exit(0)
        doc = doc[int(part)]
    elif isinstance(doc, dict) and part in doc:
        doc = doc[part]
    else:
        sys.exit(0)
if doc is None:
    sys.exit(0)
# json.dumps so a bool prints as true/false rather than Python True/False -
# this is read by [ "$x" = "true" ] in shell.
print(doc if isinstance(doc, str) else json.dumps(doc))
' "$1" "$2"
}

# call <tool> <json body> - prints the response body.
call() {
    curl -s -X POST "${BASE}/api/tools/$1" \
        -H 'Content-Type: application/json' \
        -H "X-Call-Id: ${CALL_ID}" \
        -H 'X-As-Of: 2026-09-03T09:00:00+00:00' \
        -d "$2"
}

# check <tool> <body> <dotted path that must be non-empty> <description>
check() {
    local tool="$1" body="$2" path="$3" what="$4"
    local response ok value
    response="$(call "$tool" "$body")"
    ok="$(field "$response" ok)"
    value="$(field "$response" "$path")"

    if [ "$ok" = "true" ] && [ -n "$value" ]; then
        printf '  %s %-22s %s\n' "$(green PASS)" "$tool" "$what → $value"
        PASS=$((PASS + 1))
    else
        printf '  %s %-22s %s\n' "$(red FAIL)" "$tool" "$what"
        printf '       %s\n' "$(echo "$response" | head -c 400)"
        FAIL=$((FAIL + 1))
        FAILED_TOOLS+=("$tool")
    fi
}

echo "=== the binding surface ==="
TOOLS_JSON="$(curl -s "${BASE}/api/tools")"
TOOL_COUNT="$(python3 -c 'import json,sys; print(len(json.loads(sys.argv[1])))' "$TOOLS_JSON")"
echo "  GET /tools → ${TOOL_COUNT} tools with JSON Schema"
python3 -c '
import json, sys
for tool in json.loads(sys.argv[1]):
    kind = "write" if tool["writes"] else "read"
    print("    %-22s %-9s %s" % (tool["name"], tool["agent"], kind))
' "$TOOLS_JSON"
echo

# --- read tools -------------------------------------------------------------

echo "=== read tools, against the loaded database ==="

check resolve_address \
    '{"spoken_address":"eighty nine harbor light shores"}' \
    result.address.candidates.0.canonical_id "the hard requirement resolves"

check resolve_customer \
    '{"name":"Serena Weeks"}' \
    result.customer.candidates.0.customer_id "a unique name resolves"

check identify_caller_role \
    '{"utterance":"my house is not cooling and I live here"}' \
    result.role "role from what the caller said"

check get_visit_history \
    '{"canonical_id":"cadr_2fa76af76a2a53d2909332ef8c0dba59"}' \
    result.visits.0.job_number "most recent visit's job number"

check get_warranty_status \
    '{"canonical_id":"cadr_2fa76af76a2a53d2909332ef8c0dba59","equipment":"condenser"}' \
    result.warranty.level "precedence level"

check get_customer_balance \
    '{"customer_id":"cus_93de03daac11405980a515166b7b97cf"}' \
    result.balance.outstanding_balance "cents outstanding"

check search_notes \
    '{"entity_id":"job_28e341b2495a4e8cbf6d677eddcc00b5","query":"drain line"}' \
    result.notes.0.note_id "top note, real embedding call"

check get_schedule \
    '{"start":"2026-09-03T09:00:00+00:00","end":"2026-09-17T09:00:00+00:00","role":"owner"}' \
    result.jobs.0.scheduled_start "soonest scheduled job"

check find_availability \
    '{"start":"2026-09-03T09:00:00+00:00","end":"2026-09-08T09:00:00+00:00","limit":3}' \
    result.slots.0.start "first bookable window"

# --- web_search -------------------------------------------------------------

echo
echo "=== web tool ==="
WEB_RESPONSE="$(call web_search '{"query":"r410a refrigerant phase out","max_results":3}')"
WEB_OK="$(field "$WEB_RESPONSE" ok)"
WEB_URL="$(field "$WEB_RESPONSE" result.results.0.url)"
WEB_ERR="$(field "$WEB_RESPONSE" error.error)"

if [ "$WEB_OK" = "true" ] && [ -n "$WEB_URL" ]; then
    printf '  %s %-22s %s\n' "$(green PASS)" "web_search" "source returned → $WEB_URL"
    PASS=$((PASS + 1))
elif [ "$WEB_ERR" = "WebSearchUnavailableError" ] && [ -z "${TAVILY_API_KEY:-}" ]; then
    printf '  %s %-22s %s\n' "$(yellow SKIP)" "web_search" \
        "TAVILY_API_KEY is not set - tool returned its typed error, not a crash"
    SKIP=$((SKIP + 1))
else
    printf '  %s %-22s %s\n' "$(red FAIL)" "web_search" "unexpected response"
    printf '       %s\n' "$(echo "$WEB_RESPONSE" | head -c 400)"
    FAIL=$((FAIL + 1))
    FAILED_TOOLS+=("web_search")
fi

# --- write tools ------------------------------------------------------------

echo
echo "=== write tools, committing for real ==="

BOOK_BODY='{"customer_id":"cus_93de03daac11405980a515166b7b97cf",
 "scheduled_start":"2026-11-05T14:00:00+00:00",
 "description":"smoke test booking",
 "display_address":"1 Smoke Test St",
 "spoken_confirmation":"yes, the fifth at two works"}'

BOOK_RESPONSE="$(call book_job "$BOOK_BODY")"
BOOKED_JOB="$(field "$BOOK_RESPONSE" result.job_id)"
if [ -n "$BOOKED_JOB" ] && [ "$(field "$BOOK_RESPONSE" ok)" = "true" ]; then
    printf '  %s %-22s %s\n' "$(green PASS)" "book_job" "booked → $BOOKED_JOB"
    PASS=$((PASS + 1))
else
    printf '  %s %-22s %s\n' "$(red FAIL)" "book_job" "no job id"
    printf '       %s\n' "$(echo "$BOOK_RESPONSE" | head -c 400)"
    FAIL=$((FAIL + 1))
    FAILED_TOOLS+=("book_job")
fi

REPLAY="$(field "$(call book_job "$BOOK_BODY")" result.replayed)"
if [ "$REPLAY" = "true" ]; then
    printf '  %s %-22s %s\n' "$(green PASS)" "book_job (retry)" \
        "same call, same slot → replayed, nothing written twice"
    PASS=$((PASS + 1))
else
    printf '  %s %-22s %s\n' "$(red FAIL)" "book_job (retry)" \
        "expected a replay, got replayed=$REPLAY"
    FAIL=$((FAIL + 1))
    FAILED_TOOLS+=("book_job retry")
fi

check move_job \
    "{\"job_id\":\"${BOOKED_JOB}\",\"scheduled_start\":\"2026-11-07T10:00:00+00:00\",\"spoken_confirmation\":\"the seventh instead\"}" \
    result.previous_start "moved, previous slot recorded"

check add_note \
    "{\"job_id\":\"${BOOKED_JOB}\",\"content\":\"caller mentioned the upstairs unit ices over\"}" \
    result.note_id "note written"

# The booking must be visible to a read in the same call.
SEEN="$(field "$(call get_schedule \
    '{"start":"2026-11-01T00:00:00+00:00","end":"2026-11-30T00:00:00+00:00","role":"owner"}')" \
    result.jobs.0.job_id)"
if [ "$SEEN" = "$BOOKED_JOB" ]; then
    printf '  %s %-22s %s\n' "$(green PASS)" "overlay → get_schedule" \
        "the booking is visible to a read"
    PASS=$((PASS + 1))
else
    printf '  %s %-22s %s\n' "$(red FAIL)" "overlay → get_schedule" \
        "expected $BOOKED_JOB, saw ${SEEN:-nothing}"
    FAIL=$((FAIL + 1))
    FAILED_TOOLS+=("overlay")
fi

# --- audit and notify -------------------------------------------------------

echo
echo "=== audit trail ==="
AUDIT="$(docker compose exec -T db psql -U postgres -d switchboard -t -A -F'|' -c \
    "SELECT tool, action, spoken_confirmation IS NOT NULL FROM ops.write_audit
     WHERE call_id = '${CALL_ID}' ORDER BY created_at")"
if [ -n "$AUDIT" ]; then
    echo "$AUDIT" | while IFS='|' read -r tool action confirmed; do
        printf '  %s %-22s %s\n' "$(green ROW)" "$tool" \
            "action=$action spoken_confirmation_recorded=$confirmed"
    done
    PASS=$((PASS + 1))
else
    printf '  %s %s\n' "$(red FAIL)" "no audit rows for ${CALL_ID}"
    FAIL=$((FAIL + 1))
fi

# --- cleanup ----------------------------------------------------------------

echo
echo "=== cleaning up this run's writes ==="
docker compose exec -T db psql -U postgres -d switchboard -t -A -c "
DELETE FROM ops.agent_notes WHERE call_id = '${CALL_ID}';
DELETE FROM ops.job_reschedules WHERE call_id = '${CALL_ID}';
DELETE FROM ops.booked_jobs WHERE call_id = '${CALL_ID}';
DELETE FROM ops.write_audit WHERE call_id = '${CALL_ID}';
SELECT 'ops rows remaining for this call: ' || (
    (SELECT count(*) FROM ops.write_audit WHERE call_id = '${CALL_ID}') +
    (SELECT count(*) FROM ops.booked_jobs WHERE call_id = '${CALL_ID}') +
    (SELECT count(*) FROM ops.agent_notes WHERE call_id = '${CALL_ID}') +
    (SELECT count(*) FROM ops.job_reschedules WHERE call_id = '${CALL_ID}'));"

# --- summary ----------------------------------------------------------------

echo
echo "=========================================="
printf 'passed: %s   failed: %s   skipped: %s\n' \
    "$(green "$PASS")" "$(red "$FAIL")" "$(yellow "$SKIP")"
if [ "$SKIP" -gt 0 ]; then
    yellow "skipped tools were not verified - a skip is not a pass"; echo
fi
if [ "$FAIL" -gt 0 ]; then
    red "failed: ${FAILED_TOOLS[*]}"; echo
    exit 1
fi
echo "=========================================="
