#!/bin/bash
# Test B: Approval Happy Path
# Verifies that pipeline completes after approval is granted

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEST_PROJECT="test_hitl_approval_happy_$(date +%s)"

echo "========================================"
echo "Test B: Approval Happy Path"
echo "========================================"

cleanup() {
    echo "Cleaning up test project..."
    rm -rf "$PROJECT_ROOT/projects/$TEST_PROJECT"
}

trap cleanup EXIT

# 1. Create test project
echo "Creating test project: $TEST_PROJECT"
mkdir -p "$PROJECT_ROOT/projects/$TEST_PROJECT/inputs"

cat > "$PROJECT_ROOT/projects/$TEST_PROJECT/inputs/idea.md" << 'EOF'
# Test Network for Approval
Test network topology
EOF

cat > "$PROJECT_ROOT/projects/$TEST_PROJECT/inputs/otp.pdf" << 'EOF'
Mock OTP PDF
EOF

# 2. Run pipeline first time (generates template, blocks)
echo ""
echo "First run: generating template..."

cd "$PROJECT_ROOT"

if python3 -m dawn.cli run "$TEST_PROJECT" dawn/pipelines/t2t_cyber_range.yaml 2>&1 > /dev/null; then
    echo "ERROR: Pipeline should have blocked on first run"
    exit 1
fi

echo "✓ First run correctly blocked"

# 3. Edit approval file to approve
TEMPLATE_PATH="$PROJECT_ROOT/projects/$TEST_PROJECT/inputs/hitl_approval.json"

if [ ! -f "$TEMPLATE_PATH" ]; then
    echo "ERROR: Template not created"
    exit 1
fi

echo "✓ Template exists"

# Modify approval file
jq '.approved = true | .operator = "test_user" | .comment = "Approved for testing"' \
    "$TEMPLATE_PATH" > "$TEMPLATE_PATH.tmp" && mv "$TEMPLATE_PATH.tmp" "$TEMPLATE_PATH"

echo "✓ Approval granted in template"

# 4. Re-run pipeline (should succeed)
echo ""
echo "Second run: with approval..."

if ! python3 -m dawn.cli run "$TEST_PROJECT" dawn/pipelines/t2t_cyber_range.yaml 2>&1 | tee /tmp/test_output.log; then
    echo "ERROR: Pipeline should have succeeded with approval"
    cat /tmp/test_output.log
    exit 1
fi

echo "✓ Pipeline completed successfully"

# 5. Verify dawn.hitl.approval has status "approved"
APPROVAL_PATH="$PROJECT_ROOT/projects/$TEST_PROJECT/artifacts/hitl.gate/approval.json"

if [ ! -f "$APPROVAL_PATH" ]; then
    echo "ERROR: Approval artifact not found"
    exit 1
fi

if ! grep -q '"status": "approved"' "$APPROVAL_PATH"; then
    echo "ERROR: Approval status should be 'approved'"
    cat "$APPROVAL_PATH"
    exit 1
fi

echo "✓ Approval status is 'approved'"

echo ""
echo "========================================"
echo "Test B: PASSED ✓"
echo "========================================"
