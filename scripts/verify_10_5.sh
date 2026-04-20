#!/bin/bash
set -e

echo "Starting Phase 10.5 Verification..."

# Cleanup
rm -rf projects/verify_10_5_new

# Ensure PYTHONPATH
export PYTHONPATH=.

# Test A: New project creates index
echo "Running Test A: New Project Index..."
python3 -m dawn.runtime.new --project verify_10_5_new --pipeline-id handoff_min --profile normal

if [ ! -f "projects/verify_10_5_new/project_index.json" ]; then
    echo "❌ Test A Failed: project_index.json not found"
    exit 1
fi

SCHEMA_VERSION=$(python3 -c "import json; print(json.load(open('projects/verify_10_5_new/project_index.json'))['schema_version'])")
if [ "$SCHEMA_VERSION" != "1.0.0" ]; then
    echo "❌ Test A Failed: Incorrect schema version $SCHEMA_VERSION"
    exit 1
fi
echo "✅ Test A Passed: project_index.json created with correct schema."

# Test B: Success run updates index
echo "Running Test B: Success Run Updates Index..."
python3 -m dawn.runtime.new --project verify_10_5_success --pipeline-id test_10_3_success --profile normal
echo "Automated test B" > projects/verify_10_5_success/inputs/idea.md

python3 -m dawn.runtime.pipelines run --id test_10_3_success --project verify_10_5_success --executor local --profile normal

INDEX_DATA=$(python3 -c "import json; d=json.load(open('projects/verify_10_5_success/project_index.json')); print(f\"{d['runs']['last_status']}|{len(d['artifacts'])}\")")
STATUS=$(echo "$INDEX_DATA" | cut -d'|' -f1)
ART_COUNT=$(echo "$INDEX_DATA" | cut -d'|' -f2)

if [ "$STATUS" != "SUCCEEDED" ]; then
    echo "❌ Test B Failed: last_status is $STATUS, expected SUCCEEDED"
    exit 1
fi

if [ "$ART_COUNT" -eq 0 ]; then
    echo "❌ Test B Failed: No artifacts listed in index"
    exit 1
fi
echo "✅ Test B Passed: last_status is SUCCEEDED and artifacts are indexed."

# Test C: Failure run still produces index
echo "Running Test C: Failure Run Updates Index..."
# Use app_iterate with isolation (policy violation)
rm -rf projects/verify_10_5_fail
python3 -m dawn.runtime.new --project verify_10_5_fail --pipeline-id app_iterate --profile isolation
echo "Automated failure test" > projects/verify_10_5_fail/inputs/idea.md

# We expect this to fail
python3 -m dawn.runtime.pipelines run --id app_iterate --project verify_10_5_fail --executor local --profile isolation || true

INDEX_FAIL=$(python3 -c "import json; d=json.load(open('projects/verify_10_5_fail/project_index.json')); print(f\"{d['runs']['last_status']}|{d['runs'].get('last_error','')}\")")
F_STATUS=$(echo "$INDEX_FAIL" | cut -d'|' -f1)
F_ERROR=$(echo "$INDEX_FAIL" | cut -d'|' -f2)

if [ "$F_STATUS" != "FAILED" ]; then
    echo "❌ Test C Failed: last_status is $F_STATUS, expected FAILED"
    exit 1
fi

if [ -z "$F_ERROR" ]; then
    echo "❌ Test C Failed: No last_error recorded in index"
    exit 1
fi
echo "✅ Test C Passed: FAILED status and error message recorded in index."

# Test D: Console reads index
echo "Running Test D: Console Reads Index..."
python3 -m forgechain_console.server &
SERVER_PID=$!

sleep 3
PROJ_LIST=$(curl -s http://127.0.0.1:3434/api/projects)
if echo "$PROJ_LIST" | grep -q "verify_10_5_success"; then
    echo "✅ Test D1 Passed: Console lists project from index."
else
    echo "❌ Test D1 Failed: Console project list missing verify_10_5_success"
    kill $SERVER_PID
    exit 1
fi

PROJ_DATA=$(curl -s http://127.0.0.1:3434/api/projects/verify_10_5_success)
if echo "$PROJ_DATA" | grep -q "\"schema_version\":\"1.0.0\""; then
    echo "✅ Test D2 Passed: Console returns full index."
else
    echo "❌ Test D2 Failed: Console project details invalid"
    kill $SERVER_PID
    exit 1
fi

kill $SERVER_PID
echo "Phase 10.5 Verification Completed Successfully!"
