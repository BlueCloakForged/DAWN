#!/bin/bash
set -e

echo "Starting Phase 11 Final Verification..."

# Cleanup previous test projects
rm -rf projects/console_test_success projects/console_test_isolate

# Ensure PYTHONPATH is set
export PYTHONPATH=.

# Test A: Launch Console
echo "Running Test A: Launch Console..."
python3 -m forgechain_console.server &
SERVER_PID=$!

# Wait for server to start
sleep 3
if curl -s http://127.0.0.1:3434/api/pipelines > /dev/null; then
    echo "✅ Test A Passed: Console is listening on 3434."
else
    echo "❌ Test A Failed: Console not responding."
    kill $SERVER_PID
    exit 1
fi

# Test B: Golden path via API (Using test_10_3_success)
echo "Running Test B: Golden Path (Success)..."
# 1. Create project
curl -s -X POST http://127.0.0.1:3434/api/projects \
     -H "Content-Type: application/json" \
     -d '{"project_id": "console_test_success", "pipeline_id": "test_10_3_success", "profile": "normal"}'

# 2. Update idea.md
curl -s -X PUT http://127.0.0.1:3434/api/projects/console_test_success/inputs/idea.md \
     -H "Content-Type: application/json" \
     -d '{"content": "Automated console success test"}'

# 3. Run pipeline
curl -s -X POST http://127.0.0.1:3434/api/projects/console_test_success/run \
     -H "Content-Type: application/json" \
     -d '{"executor": "local", "profile": "normal"}'

# Wait for completion (poll)
echo "Polling for success..."
PASSED_B=0
for i in {1..20}; do
    STATUS=$(curl -s http://127.0.0.1:3434/api/projects/console_test_success | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', {}).get('package.project_report', ''))")
    if [ "$STATUS" == "SUCCEEDED" ]; then
        echo "✅ Test B Passed: Pipeline completed successfully."
        PASSED_B=1
        break
    fi
    sleep 2
done

if [ $PASSED_B -eq 0 ]; then
    echo "❌ Test B Failed: Pipeline did not reach SUCCEEDED state."
    kill $SERVER_PID
    exit 1
fi

# Test C: Failure path (Isolation)
echo "Running Test C: Isolation Failure..."
# 1. Create project with app_iterate
curl -s -X POST http://127.0.0.1:3434/api/projects \
     -H "Content-Type: application/json" \
     -d '{"project_id": "console_test_isolate", "pipeline_id": "app_iterate", "profile": "isolation"}'

# 2. Run with isolation
curl -s -X POST http://127.0.0.1:3434/api/projects/console_test_isolate/run \
     -H "Content-Type: application/json" \
     -d '{"executor": "subprocess", "profile": "isolation"}'

echo "Polling for isolation failure..."
PASSED_C=0
for i in {1..20}; do
    RESPONSE=$(curl -s http://127.0.0.1:3434/api/projects/console_test_isolate)
    if echo "$RESPONSE" | grep -q "POLICY_VIOLATION"; then
        echo "✅ Test C Passed: Policy violation detected."
        PASSED_C=1
        break
    fi
    sleep 2
done

if [ $PASSED_C -eq 0 ]; then
    echo "❌ Test C Failed: Policy violation NOT detected."
    kill $SERVER_PID
    exit 1
fi

# Kill server
kill $SERVER_PID
echo "Phase 11 Final Verification Completed Successfully!"
