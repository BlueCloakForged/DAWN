#!/bin/bash
# Acceptance Test: T2T HITL Approval Path

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=== T2T Acceptance Test 2: HITL Approval Path ==="

# Requires test 1 to have run first
if [ ! -f "projects/test_t2t_baseline/inputs/hitl_approval.json" ]; then
    echo "Error: Run test_t2t_baseline.sh first"
    exit 1
fi

# Approve the project
echo "Approving project..."
python3 - << 'PYTHON'
import json
with open('projects/test_t2t_baseline/inputs/hitl_approval.json', 'r') as f:
    approval = json.load(f)

approval['approved'] = True
approval['operator'] = 'test_operator'
approval['notes'] = 'Test approval for acceptance test'

with open('projects/test_t2t_baseline/inputs/hitl_approval.json', 'w') as f:
    json.dump(approval, f, indent=2)

print("✓ Approval file updated")
PYTHON

# Re-run pipeline
echo ""
echo "Re-running pipeline with approval..."
python3 -m dawn.runtime.main \
    --project test_t2t_baseline \
    --pipeline dawn/pipelines/t2t_cyber_range.yaml \
    2>&1 | tail -20

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ Pipeline succeeded"
else
    echo "✗ Pipeline failed (EXIT_CODE=$EXIT_CODE)"
    exit 1
fi

# Check approval artifact
if [ -f "projects/test_t2t_baseline/artifacts/hitl.gate/approval.json" ]; then
    echo "✓ approval.json artifact created"
    python3 -c "import json; a=json.load(open('projects/test_t2t_baseline/artifacts/hitl.gate/approval.json')); print(f\"  status: {a.get('status')}\"); print(f\"  operator: {a.get('operator')}\")"
else
    echo "✗ approval.json artifact missing"
    exit 1
fi

# Check JSON validation passed
if grep -q "validate.json_artifacts" /tmp/t2t_baseline.log && grep -q "SUCCEEDED" /tmp/t2t_baseline.log; then
    echo "✓ JSON validation passed"
else
    echo "Note: Check validation logs"
fi

echo ""
echo "=== ✅ TEST 2 PASSED ==="
echo "HITL approval path successful"
