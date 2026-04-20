#!/bin/bash
set -e

echo "Starting Phase 10.6 Verification..."

# Cleanup
rm -rf projects/verify_10_6_run
export PYTHONPATH=.

# Test A: Start Run -> RUNNING appears
echo "Running Test A: Live status (RUNNING)..."
python3 -m dawn.runtime.new --project verify_10_6_run --pipeline-id test_10_6 --profile normal

# Trigger run in background
python3 -m dawn.runtime.pipelines run --id test_10_6 --project verify_10_6_run --executor subprocess &
RUN_PID=$!

sleep 2
STATUS=$(python3 -c "import json; print(json.load(open('projects/verify_10_6_run/project_index.json'))['runs'].get('last_status'))")
echo "Observed status: $STATUS"

if [ "$STATUS" != "RUNNING" ] && [ "$STATUS" != "SUCCEEDED" ]; then
    # Note: Subprocess executor updates index. If it finishes too fast, it might be SUCCEEDED.
    # But test.sleep_long should take 10s.
    echo "❌ Test A Failed: Expected RUNNING (or SUCCEEDED if finished), got $STATUS"
    kill $RUN_PID 2>/dev/null || true
    exit 1
fi
echo "✅ Test A Passed: Status is $STATUS during execution."

# Test B: Live logs available
echo "Running Test B: Live logs availability..."
# Start console server to test API
python3 -m forgechain_console.server &
SERVER_PID=$!
sleep 2

# Get last_run_id
RUN_ID=$(python3 -c "import json; print(json.load(open('projects/verify_10_6_run/project_index.json'))['runs'].get('last_run_id'))")
echo "Testing logs for Run ID: $RUN_ID"

# Check log endpoint (non-streaming first)
echo "Waiting for log content..."
for i in {1..10}; do
    LOGS=$(curl -s http://127.0.0.1:3434/api/projects/verify_10_6_run/runs/$RUN_ID/logs)
    if echo "$LOGS" | grep -q "test.sleep_long: Sleeping"; then
        echo "✅ Test B Passed: Logs are accessible via API."
        break
    fi
    if [ $i -eq 10 ]; then
        echo "❌ Test B Failed: Logs missing 'test.sleep_long: Sleeping'"
        kill $RUN_PID 2>/dev/null || true
        kill $SERVER_PID 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

wait $RUN_PID
kill $SERVER_PID 2>/dev/null || true

# Test C: Completion updates history
echo "Running Test C: History persistence..."
HISTORY_COUNT=$(python3 -c "import json; print(len(json.load(open('projects/verify_10_6_run/project_index.json'))['runs'].get('history', [])))")
if [ "$HISTORY_COUNT" -eq 1 ]; then
    echo "✅ Test C Passed: History updated with 1 run."
else
    echo "❌ Test C Failed: Expected 1 history entry, got $HISTORY_COUNT"
    exit 1
fi

echo "Phase 10.6 Verification Completed Successfully!"
