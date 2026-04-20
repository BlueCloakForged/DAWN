#!/bin/bash
# Test E: Determinism
# Verifies identical inputs produce identical bundle_sha256 and artifacts

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEST_PROJECT_1="test_determinism_run1_$(date +%s)"
TEST_PROJECT_2="test_determinism_run2_$(($(date +%s) + 1))"

echo "========================================"
echo "Test E: Determinism"
echo "========================================"

cleanup() {
    echo "Cleaning up test projects..."
    rm -rf "$PROJECT_ROOT/projects/$TEST_PROJECT_1"
    rm -rf "$PROJECT_ROOT/projects/$TEST_PROJECT_2"
}

trap cleanup EXIT

cd "$PROJECT_ROOT"

# Function to create identical inputs
create_inputs() {
    local project=$1
    mkdir -p "$PROJECT_ROOT/projects/$project/inputs"
    
    cat > "$PROJECT_ROOT/projects/$project/inputs/idea.md" << 'EOF'
# Deterministic Test Network
This is an identical input for determinism testing.
The content must be exactly the same.
EOF
    
    cat > "$PROJECT_ROOT/projects/$project/inputs/otp.pdf" << 'EOF'
Mock OTP PDF with deterministic content
Same bytes every time
EOF
}

# 1. Create two projects with identical inputs
echo "Creating test projects with identical inputs..."

create_inputs "$TEST_PROJECT_1"
create_inputs "$TEST_PROJECT_2"

echo "✓ Identical inputs created"

# 2. Run pipeline on both (they will block, but we just need bundle + IR)
echo ""
echo "Run 1: $TEST_PROJECT_1..."

python3 -m dawn.cli run "$TEST_PROJECT_1" dawn/pipelines/t2t_cyber_range.yaml 2>&1 > /dev/null || true

echo "✓ Run 1 complete"

echo ""
echo "Run 2: $TEST_PROJECT_2..."

# Wait a moment to ensure different timestamps if any
sleep 1

python3 -m dawn.cli run "$TEST_PROJECT_2" dawn/pipelines/t2t_cyber_range.yaml 2>&1 > /dev/null || true

echo "✓ Run 2 complete"

# 3. Compare bundle_sha256
BUNDLE_1="$PROJECT_ROOT/projects/$TEST_PROJECT_1/artifacts/ingest.project_bundle/dawn.project.bundle.json"
BUNDLE_2="$PROJECT_ROOT/projects/$TEST_PROJECT_2/artifacts/ingest.project_bundle/dawn.project.bundle.json"

if [ ! -f "$BUNDLE_1" ] || [ ! -f "$BUNDLE_2" ]; then
    echo "ERROR: Bundle artifacts not found"
    ls -la "$PROJECT_ROOT/projects/$TEST_PROJECT_1/artifacts/ingest.project_bundle/" || true
    ls -la "$PROJECT_ROOT/projects/$TEST_PROJECT_2/artifacts/ingest.project_bundle/" || true
    exit 1
fi

SHA1=$(jq -r '.bundle_sha256' "$BUNDLE_1")
SHA2=$(jq -r '.bundle_sha256' "$BUNDLE_2")

if [ "$SHA1" != "$SHA2" ]; then
    echo "ERROR: bundle_sha256 mismatch!"
    echo "Run 1: $SHA1"
    echo "Run 2: $SHA2"
    exit 1
fi

echo "✓ bundle_sha256 identical: $SHA1"

# 4. Verify bundle artifacts are byte-identical
BUNDLE_HASH_1=$(sha256sum "$BUNDLE_1" | awk '{print $1}')
BUNDLE_HASH_2=$(sha256sum "$BUNDLE_2" | awk '{print $1}')

if [ "$BUNDLE_HASH_1" != "$BUNDLE_HASH_2" ]; then
    echo "ERROR: Bundle manifests are not byte-identical!"
    echo "This suggests non-deterministic output (timestamps, ordering, etc.)"
    diff "$BUNDLE_1" "$BUNDLE_2" || true
    exit 1
fi

echo "✓ Bundle manifests are byte-identical"

# 5. Verify no timestamps in bundle
if grep -q "timestamp\|created_at\|updated_at" "$BUNDLE_1"; then
    echo "ERROR: Bundle contains timestamps!"
    cat "$BUNDLE_1"
    exit 1
fi

echo "✓ No timestamps in bundle manifest"

# 6. Check IR artifacts if they exist
IR_1="$PROJECT_ROOT/projects/$TEST_PROJECT_1/artifacts/ingest.handoff/project_ir.json"
IR_2="$PROJECT_ROOT/projects/$TEST_PROJECT_2/artifacts/ingest.handoff/project_ir.json"

if [ -f "$IR_1" ] && [ -f "$IR_2" ]; then
    if grep -q "timestamp\|created_at\|updated_at" "$IR_1"; then
        echo "ERROR: IR contains timestamps!"
        cat "$IR_1"
        exit 1
    fi
    
    echo "✓ No timestamps in IR"
    
    # Compare IR bundle_sha256 references
    IR_SHA1=$(jq -r '.bundle_sha256' "$IR_1")
    IR_SHA2=$(jq -r '.bundle_sha256' "$IR_2")
    
    if [ "$IR_SHA1" != "$IR_SHA2" ]; then
        echo "ERROR: IR bundle_sha256 mismatch!"
        exit 1
    fi
    
    echo "✓ IR bundle_sha256 references match"
fi

echo ""
echo "========================================"
echo "Test E: PASSED ✓"
echo "========================================"
echo "Determinism verified:"
echo "  - Identical bundle_sha256"
echo "  - Byte-identical artifacts"
echo "  - No timestamps"
echo "========================================"
