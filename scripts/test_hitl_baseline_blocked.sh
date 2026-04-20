#!/bin/bash
# Test A: Baseline BLOCKED
# Verifies that pipeline blocks when no approval exists

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEST_PROJECT="test_hitl_baseline_blocked_$(date +%s)"

echo "========================================"
echo "Test A: Baseline BLOCKED"
echo "========================================"

cleanup() {
    echo "Cleaning up test project..."
    rm -rf "$PROJECT_ROOT/projects/$TEST_PROJECT"
}

trap cleanup EXIT

# 1. Create test project with inputs
echo "Creating test project: $TEST_PROJECT"
mkdir -p "$PROJECT_ROOT/projects/$TEST_PROJECT/inputs"

# Create a simple idea.md
cat > "$PROJECT_ROOT/projects/$TEST_PROJECT/inputs/idea.md" << 'EOF'
# Test Network Topology

Simple test network for HITL baseline test.
EOF

# Create a mock OTP PDF (actually just a text file for test)
cat > "$PROJECT_ROOT/projects/$TEST_PROJECT/inputs/otp.pdf" << 'EOF'
Mock OTP PDF content for testing
EOF

# 2. Remove any existing approval files
rm -f "$PROJECT_ROOT/projects/$TEST_PROJECT/inputs/hitl_approval.json"

# 3. Run pipeline (should BLOCK)
echo ""
echo "Running pipeline (expecting BLOCKED)..."

cd "$PROJECT_ROOT"

# Run and capture output
if python3 -m dawn.cli run "$TEST_PROJECT" dawn/pipelines/t2t_cyber_range.yaml 2>&1 | tee /tmp/test_output.log; then
    echo "ERROR: Pipeline should have BLOCKED but succeeded!"
    exit 1
fi

# 4. Verify error message contains "BLOCKED"
if ! grep -q "BLOCKED" /tmp/test_output.log; then
    echo "ERROR: Expected BLOCKED error message"
    cat /tmp/test_output.log
    exit 1
fi

echo "✓ Pipeline correctly BLOCKED"

# 5. Verify dawn.hitl.approval artifact exists with status "blocked"
APPROVAL_PATH="$PROJECT_ROOT/projects/$TEST_PROJECT/artifacts/hitl.gate/approval.json"
if [ ! -f "$APPROVAL_PATH" ]; then
    echo "ERROR: Approval artifact not found at $APPROVAL_PATH"
    exit 1
fi

echo "✓ Approval artifact exists"

# Check approval status is "blocked"
if ! grep -q '"status": "blocked"' "$APPROVAL_PATH"; then
    echo "ERROR: Approval status should be 'blocked'"
    cat "$APPROVAL_PATH"
    exit 1
fi

echo "✓ Approval status is 'blocked'"

# 6. Verify template file created at inputs/hitl_approval.json
TEMPLATE_PATH="$PROJECT_ROOT/projects/$TEST_PROJECT/inputs/hitl_approval.json"
if [ ! -f "$TEMPLATE_PATH" ]; then
    echo "ERROR: Template file not created at $TEMPLATE_PATH"
    exit 1
fi

echo "✓ Template file created"

# Verify template structure
if ! jq -e '.bundle_sha256 and .approved == false' "$TEMPLATE_PATH" > /dev/null; then
    echo "ERROR: Template structure invalid"
    cat "$TEMPLATE_PATH"
    exit 1
fi

echo "✓ Template structure valid"

echo ""
echo "========================================"
echo "Test A: PASSED ✓"
echo "========================================"
