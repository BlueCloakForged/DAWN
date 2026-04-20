#!/bin/bash
# Acceptance Tests: Bundle Registration + Domain-Agnostic DAWN
# Tests all 4 required scenarios

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=== DAWN Bundle Registration Acceptance Tests ==="
echo ""

# Test 1: Baseline Ingestion (BLOCKED)
echo "=== Test 1: Baseline Ingestion (BLOCKED) ==="
PROJECT="test_t2t_baseline"
rm -rf "projects/${PROJECT}"
mkdir -p "projects/${PROJECT}/inputs"

# Create sample input files
cat > "projects/${PROJECT}/inputs/sample.txt" << 'EOF'
Sample input document for T2T testing
EOF

cat > "projects/${PROJECT}/inputs/test_otp.pdf" << 'EOF'
%PDF-1.4
%Test OTP placeholder for acceptance test
EOF

echo "Running pipeline (expect BLOCKED at hitl.gate)..."
python3 -m dawn.runtime.main \
  --project "${PROJECT}" \
  --pipeline dawn/pipelines/t2t_cyber_range.yaml \
  2>&1 | tee "/tmp/test_${PROJECT}.log" || true

# Check bundle manifest
if [ -f "projects/${PROJECT}/artifacts/ingest.project_bundle/bundle_manifest.json" ]; then
    echo "✓ Bundle manifest created"
    bundle_hash=$(python3 -c "import json; print(json.load(open('projects/${PROJECT}/artifacts/ingest.project_bundle/bundle_manifest.json'))['bundle_sha256'])")
    echo "  Bundle SHA256: $bundle_hash"
else
    echo "✗ Bundle manifest missing"
    exit 1
fi

# Check project IR
if [ -f "projects/${PROJECT}/artifacts/ingest.handoff/project_ir.json" ]; then
    echo "✓ Project IR created"
    ir_bundle_hash=$(python3 -c "import json; print(json.load(open('projects/${PROJECT}/artifacts/ingest.handoff/project_ir.json'))['bundle_sha256'])")
    if [ "$ir_bundle_hash" = "$bundle_hash" ]; then
        echo "✓ IR bundle_sha256 matches manifest"
    else
        echo "✗ IR bundle_sha256 mismatch"
        exit 1
    fi
else
    echo "✗ Project IR missing"
    exit 1
fi

# Check HITL template
if [ -f "projects/${PROJECT}/inputs/hitl_approval.json" ]; then
    echo "✓ HITL approval template created"
    approval_bundle=$(python3 -c "import json; print(json.load(open('projects/${PROJECT}/inputs/hitl_approval.json'))['bundle_sha256'])")
    if [ "$approval_bundle" = "$bundle_hash" ]; then
        echo "✓ Approval template bound to correct bundle"
    else
        echo "✗ Approval bundle_sha256 mismatch"
        exit 1
    fi
else
    echo "✗ HITL approval template missing"
    exit 1
fi

# Check determinism (rerun)
echo "Testing determinism (rerun pipeline)..."
rm -rf "projects/${PROJECT}/artifacts"
rm -f "projects/${PROJECT}/inputs/hitl_approval.json"

python3 -m dawn.runtime.main \
  --project "${PROJECT}" \
  --pipeline dawn/pipelines/t2t_cyber_range.yaml \
  2>&1 > /dev/null || true

bundle_hash_2=$(python3 -c "import json; print(json.load(open('projects/${PROJECT}/artifacts/ingest.project_bundle/bundle_manifest.json'))['bundle_sha256'])")

if [ "$bundle_hash" = "$bundle_hash_2" ]; then
    echo "✓ Determinism verified (identical bundle_sha256 on rerun)"
else
    echo "✗ Determinism FAILED"
    exit 1
fi

echo ""

# Test 2: Approval Path
echo "=== Test 2: Approval Path ==="

# Approve the project
python3 << 'PYTHON'
import json
with open('projects/test_t2t_baseline/inputs/hitl_approval.json', 'r') as f:
    approval = json.load(f)

approval['approved'] = True
approval['operator'] = 'test_operator'
approval['comment'] = 'Acceptance test approval'

with open('projects/test_t2t_baseline/inputs/hitl_approval.json', 'w') as f:
    json.dump(approval, f, indent=2)
PYTHON

# Rerun
python3 -m dawn.runtime.main \
  --project "${PROJECT}" \
  --pipeline dawn/pipelines/t2t_cyber_range.yaml \
  2>&1 | tail -20

if [ -f "projects/${PROJECT}/artifacts/hitl.gate/approval.json" ]; then
    status=$(python3 -c "import json; print(json.load(open('projects/${PROJECT}/artifacts/hitl.gate/approval.json'))['status'])")
    if [ "$status" = "approved" ]; then
        echo "✓ Approval path successful"
    else
        echo "✗ Expected approved, got: $status"
        exit 1
    fi
else
    echo "✗ Approval artifact missing"
    exit 1
fi

echo ""

# Test 3: Stale Approval Rejection
echo "=== Test 3: Stale Approval Rejection ==="

# Modify an input file
echo "Modified content for stale test" > "projects/${PROJECT}/inputs/sample.txt"

# Rerun (should detect stale approval)
python3 -m dawn.runtime.main \
  --project "${PROJECT}" \
  --pipeline dawn/pipelines/t2t_cyber_range.yaml \
  2>&1 | tee /tmp/test_stale.log || true

if grep -q "STALE APPROVAL" /tmp/test_stale.log; then
    echo "✓ Stale approval detected and rejected"
else
    echo "✗ Stale approval NOT detected"
    exit 1
fi

echo ""

# Test 4: AUTO Mode Rules
echo "=== Test 4: AUTO Mode Rules ==="

# Test 4a: High confidence + flags → BLOCKED
PROJECT_AUTO="test_auto_flags"
rm -rf "projects/${PROJECT_AUTO}"
mkdir -p "projects/${PROJECT_AUTO}/inputs" "projects/${PROJECT_AUTO}/artifacts/ingest.project_bundle" "projects/${PROJECT_AUTO}/artifacts/ingest.handoff"

# Create bundle manifest
cat > "projects/${PROJECT_AUTO}/artifacts/ingest.project_bundle/bundle_manifest.json" << 'EOF'
{
  "schema_version": "1.0.0",
  "total_files": 1,
  "total_bytes": 100,
  "files": [{"path": "inputs/test.txt", "sha256": "abc123", "size": 100}],
  "bundle_sha256": "test_auto_bundle_001"
}
EOF

# Create IR with high confidence but flags
cat > "projects/${PROJECT_AUTO}/artifacts/ingest.handoff/project_ir.json" << 'EOF'
{
  "schema_version": "1.0.0",
  "bundle_sha256": "test_auto_bundle_001",
  "parser_id": "t2t",
  "ir_type": "network",
  "payload": {},
  "confidence": {
    "score": 0.85,
    "flags": ["security_issue"],
    "hitl_required": false
  }
}
EOF

# Create pipeline
cat > "projects/${PROJECT_AUTO}/test_pipeline.yaml" << 'EOF'
pipelineId: test_auto_flags
links:
  - id: hitl.gate
    config:
      mode: AUTO
      auto_threshold: 0.7
EOF

python3 -m dawn.runtime.main \
  --project "${PROJECT_AUTO}" \
  --pipeline "projects/${PROJECT_AUTO}/test_pipeline.yaml" \
  2>&1 | tee /tmp/test_auto.log || true

if grep -q "flags present" /tmp/test_auto.log && [ -f "projects/${PROJECT_AUTO}/inputs/hitl_approval.json" ]; then
    echo "✓ AUTO mode with flags → BLOCKED (correct)"
else
    echo "✗ AUTO mode with flags did not block"
    exit 1
fi

echo ""
echo "=== ✅ ALL ACCEPTANCE TESTS PASSED ==="
echo "  ✓ Test 1: Baseline ingestion, HITL blocks, determinism"
echo "  ✓ Test 2: Approval path successful"
echo "  ✓ Test 3: Stale approval rejection"
echo "  ✓ Test 4: AUTO mode rules (flags → BLOCKED)"
