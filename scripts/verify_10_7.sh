#!/bin/bash
set -e

echo "Starting Phase 10.7 Verification..."

# Cleanup
rm -rf projects/verify_10_7
export PYTHONPATH=.

# Test 1: Start project and verify Artifacts API
echo "Running Test 1: Artifacts API..."
python3 -m dawn.runtime.new --project verify_10_7 --pipeline-id test_10_6 --profile normal
# Trigger run to generate artifacts
python3 -m dawn.runtime.pipelines run --id test_10_6 --project verify_10_7 --executor subprocess

# Start console server
python3 -m forgechain_console.server &
SERVER_PID=$!
sleep 2

# Check artifacts endpoint
ARTS=$(curl -s http://127.0.0.1:3434/api/projects/verify_10_7/artifacts)
if echo "$ARTS" | grep -q "verification_artifact.txt"; then
    echo "✅ Test 1 Passed: Artifacts listed in API."
else
    echo "❌ Test 1 Failed: Artifacts list missing verification_artifact.txt."
    kill $SERVER_PID
    exit 1
fi

# Test 2: Inputs API (List and Edit)
echo "Running Test 2: Inputs API..."
INPUTS=$(curl -s http://127.0.0.1:3434/api/projects/verify_10_7/inputs)
if echo "$INPUTS" | grep -q "idea.md"; then
    echo "✅ Test 2a Passed: Inputs listed."
else
    echo "❌ Test 2a Failed: Inputs list missing idea.md."
    kill $SERVER_PID
    exit 1
fi

curl -s -X PUT http://127.0.0.1:3434/api/projects/verify_10_7/inputs/idea.md -H "Content-Type: application/json" -d '{"content": "New Idea Content"}' | grep -q "success"
if grep -q "New Idea Content" projects/verify_10_7/inputs/idea.md; then
    echo "✅ Test 2b Passed: Input edited correctly."
else
    echo "❌ Test 2b Failed: Input file not updated."
    kill $SERVER_PID
    exit 1
fi

# Test 3: Gate Resolution API
echo "Running Test 3: Gate Resolution (human_decision)..."
curl -s -X POST http://127.0.0.1:3434/api/projects/verify_10_7/gate -H "Content-Type: application/json" -d '{"filename": "human_decision.json", "decision": "APPROVED", "reason": "Looks good"}' | grep -q "success"

if [ -f projects/verify_10_7/inputs/human_decision.json ]; then
    DECISION=$(python3 -c "import json; print(json.load(open('projects/verify_10_7/inputs/human_decision.json'))['decision'])")
    if [ "$DECISION" == "APPROVED" ]; then
        echo "✅ Test 3 Passed: Gate decision written to file."
    else
        echo "❌ Test 3 Failed: Decision value mismatch: $DECISION"
        kill $SERVER_PID
        exit 1
    fi
else
    echo "❌ Test 3 Failed: human_decision.json not created."
    kill $SERVER_PID
    exit 1
fi

kill $SERVER_PID

# Test 4: Schema Alignment Validation
echo "Running Test 4: Schema Alignment..."
# Trigger index update
python3 -m dawn.runtime.project_index projects/verify_10_7

INDEX="projects/verify_10_7/project_index.json"

# 4a: Check inputs.files
if python3 -c "import json; idx=json.load(open('$INDEX')); exit(0 if len(idx['inputs']['files']) > 0 else 1)"; then
    echo "✅ Test 4a Passed: inputs.files registry populated."
else
    echo "❌ Test 4a Failed: inputs.files missing or empty."
    exit 1
fi

# 4c: Check approvals history
if python3 -c "import json; idx=json.load(open('$INDEX')); exit(0 if len(idx['approvals']['history']) > 0 else 1)"; then
    echo "✅ Test 4c Passed: approvals.history audit trail populated."
else
    echo "❌ Test 4c Failed: approvals.history missing or empty."
    exit 1
fi

# 4d: Check MIME types
if python3 -c "import json; idx=json.load(open('$INDEX')); art=idx['artifacts']['verification_artifact.txt']; exit(0 if art['mime'] == 'text/plain' else 1)"; then
    echo "✅ Test 4d Passed: Correct MIME for .txt."
else
    echo "❌ Test 4d Failed: Incorrect MIME for .txt."
    exit 1
fi

echo "Phase 11.0 Schema Refinements Verified Successfully!"
