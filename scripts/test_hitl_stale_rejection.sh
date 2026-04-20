#!/bin/bash
# Test C: Stale Approval Rejection
# Verifies that pipeline rejects approvals for modified inputs

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEST_PROJECT="test_hitl_stale_rejection_$(date +%s)"

echo "========================================"
echo "Test C: Stale Approval Rejection"
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
# Version 1 of Network
Original network design
EOF

cat > "$PROJECT_ROOT/projects/$TEST_PROJECT/inputs/otp.pdf" << 'EOF'
Mock OTP v1
EOF

cd "$PROJECT_ROOT"

# 2. Run pipeline, generate template
echo ""
echo "First run: generating template..."

python3 -m dawn.cli run "$TEST_PROJECT" dawn/pipelines/t2t_cyber_range.yaml 2>&1 > /dev/null || true

TEMPLATE_PATH="$PROJECT_ROOT/projects/$TEST_PROJECT/inputs/hitl_approval.json"

# 3. Approve bundle v1
echo "Approving bundle v1..."

jq '.approved = true | .operator = "test_user"' \
    "$TEMPLATE_PATH" > "$TEMPLATE_PATH.tmp" && mv "$TEMPLATE_PATH.tmp" "$TEMPLATE_PATH"

# Run again to confirm approval works
python3 -m dawn.cli run "$TEST_PROJECT" dawn/pipelines/t2t_cyber_range.yaml 2>&1 > /dev/null

echo "✓ Bundle v1 approved and pipeline succeeded"

# 4. Modify inputs (changes bundle_sha256)
echo ""
echo "Modifying inputs to create bundle v2..."

cat > "$PROJECT_ROOT/projects/$TEST_PROJECT/inputs/idea.md" << 'EOF'
# Version 2 of Network - MODIFIED
Updated network design with changes
EOF

echo "✓ Inputs modified"

# 5. Re-run pipeline (should reject stale approval)
echo ""
echo "Re-running pipeline with stale approval..."

if python3 -m dawn.cli run "$TEST_PROJECT" dawn/pipelines/t2t_cyber_range.yaml 2>&1 | tee /tmp/test_output.log; then
    echo "ERROR: Pipeline should have rejected stale approval"
    exit 1
fi

echo "✓ Pipeline correctly rejected"

# 6. Verify error message contains "STALE"
if ! grep -qi "stale" /tmp/test_output.log; then
    echo "ERROR: Expected STALE error message"
    cat /tmp/test_output.log
    exit 1
fi

echo "✓ Error message contains 'STALE'"

# Verify bundle_sha256 mismatch mentioned
if ! grep -q "bundle_sha256" /tmp/test_output.log; then
    echo "ERROR: Expected bundle_sha256 mismatch in error"
    cat /tmp/test_output.log
    exit 1
fi

echo "✓ Bundle SHA256 mismatch mentioned"

echo ""
echo "========================================"
echo "Test C: PASSED ✓"
echo "========================================"
