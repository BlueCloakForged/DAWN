#!/bin/bash
set -e

echo "Starting DAWN Verification..."

# 1. Clean previous runs
rm -rf projects/test_project

# 2. Run default pipeline
echo "Running default pipeline..."
PYTHONPATH=. python3 -m dawn.runtime.main --project test_project --pipeline dawn/pipelines/default.yaml

# 3. Verify ledger existence
if [ ! -f "projects/test_project/ledger/events.jsonl" ]; then
    echo "FAILED: Ledger file not found"
    exit 1
fi

# 4. Run summary command
echo "Pipeline Summary:"
python3 dawn/runtime/summary.py projects/test_project/ledger/events.jsonl

# 5. Check for success status in ledger
if grep -q "SUCCEEDED" projects/test_project/ledger/events.jsonl; then
    echo "SUCCESS: Pipeline executed core links"
else
    echo "FAILED: No successful events found in ledger"
    exit 1
fi

echo "Verification Complete."
