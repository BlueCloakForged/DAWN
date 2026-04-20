#!/bin/bash
# Acceptance Test: HITL Gate Modes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=== HITL Gate Acceptance Tests ==="
echo ""

# Test 1: BLOCKED mode with missing approval
echo "=== Test 1: BLOCKED Mode (Missing Approval) ==="
rm -rf projects/test_hitl_blocked
mkdir -p projects/test_hitl_blocked/inputs

# Create minimal descriptor with bundle digest
cat > projects/test_hitl_blocked/inputs/test.txt << 'EOF'
Sample input file for bundle hash
EOF

# Create minimal descriptor artifact (simulate ingest.handoff)
mkdir -p projects/test_hitl_blocked/artifacts/ingest.handoff
cat > projects/test_hitl_blocked/artifacts/ingest.handoff/project_descriptor.json << 'EOF'
{
  "schema_version": "1.0.0",
  "project_id": "test_hitl_blocked",
  "source_bundle": {
    "files": [{"path": "inputs/test.txt", "sha256": "abc123", "size": 100}],
    "bundle_sha256": "test_bundle_digest_001"
  },
  "confidence": {
    "overall_score": 0.5,
    "flags": ["low_confidence"],
    "hitl_required": true
  }
}
EOF

cat > projects/test_hitl_blocked/artifacts/ingest.handoff/confidence_report.json << 'EOF'
{
  "schema_version": "1.0.0",
  "overall_score": 0.5,
  "flags": ["low_confidence"],
  "hitl_required": true
}
EOF

# Run hitl.gate with BLOCKED mode (should fail and create template)
echo "Running hitl.gate (expect BLOCKED)..."
python3 -m dawn.runtime.main --project test_hitl_blocked --pipeline - << 'YAML' 2>&1 | tee /tmp/hitl_test1.log || true
pipelineId: test_hitl_blocked
links:
  - id: hitl.gate
    config:
      mode: BLOCKED
      bind_to_bundle_digest: true
YAML

# Check template created
if [ -f "projects/test_hitl_blocked/inputs/hitl_approval.json" ]; then
    echo "✓ Approval template created"
    python3 -c "import json; a=json.load(open('projects/test_hitl_blocked/inputs/hitl_approval.json')); print(f\"  bundle_digest: {a.get('bundle_digest')}\"); print(f\"  approved: {a.get('approved')}\")"
else
    echo "✗ Template NOT created"
    exit 1
fi

echo ""

# Test 2: BLOCKED mode with valid approval
echo "=== Test 2: BLOCKED Mode (Valid Approval) ==="

# Approve the project
python3 - << 'PYTHON'
import json
with open('projects/test_hitl_blocked/inputs/hitl_approval.json', 'r') as f:
    approval = json.load(f)

approval['approved'] = True
approval['approved_by'] = 'test_operator'
approval['comment'] = 'Test approval'

with open('projects/test_hitl_blocked/inputs/hitl_approval.json', 'w') as f:
    json.dump(approval, f, indent=2)
PYTHON

# Re-run (should succeed)
python3 -m dawn.runtime.main --project test_hitl_blocked --pipeline - << 'YAML' 2>&1 | tail -10
pipelineId: test_hitl_blocked
links:
  - id: hitl.gate
    config:
      mode: BLOCKED
      bind_to_bundle_digest: true
YAML

if [ -f "projects/test_hitl_blocked/artifacts/hitl.gate/approval.json" ]; then
    echo "✓ Approval artifact created"
    python3 -c "import json; a=json.load(open('projects/test_hitl_blocked/artifacts/hitl.gate/approval.json')); print(f\"  status: {a.get('status')}\"); print(f\"  approved_by: {a.get('approved_by')}\")"
else
    echo "✗ Approval artifact missing"
    exit 1
fi

echo ""

# Test 3: Stale approval prevention
echo "=== Test 3: Stale Approval Prevention ==="

# Change bundle digest in descriptor (simulate new inputs)
python3 - << 'PYTHON'
import json
with open('projects/test_hitl_blocked/artifacts/ingest.handoff/project_descriptor.json', 'r') as f:
    desc = json.load(f)

desc['source_bundle']['bundle_sha256'] = 'test_bundle_digest_002_CHANGED'

with open('projects/test_hitl_blocked/artifacts/ingest.handoff/project_descriptor.json', 'w') as f:
    json.dump(desc, f, indent=2)
PYTHON

# Run with old approval (should fail with stale error)
python3 -m dawn.runtime.main --project test_hitl_blocked --pipeline - << 'YAML' 2>&1 | tee /tmp/hitl_test3.log || true
pipelineId: test_hitl_blocked
links:
  - id: hitl.gate
    config:
      mode: BLOCKED
      bind_to_bundle_digest: true
YAML

if grep -q "STALE APPROVAL" /tmp/hitl_test3.log; then
    echo "✓ Stale approval detected and rejected"
else
    echo "✗ Stale approval NOT detected"
    exit 1
fi

echo ""

# Test 4: AUTO mode with high confidence
echo "=== Test 4: AUTO Mode (High Confidence) ==="
rm -rf projects/test_hitl_auto
mkdir -p projects/test_hitl_auto/inputs projects/test_hitl_auto/artifacts/ingest.handoff

cat > projects/test_hitl_auto/artifacts/ingest.handoff/project_descriptor.json << 'EOF'
{
  "schema_version": "1.0.0",
  "project_id": "test_hitl_auto",
  "source_bundle": {
    "bundle_sha256": "auto_bundle_001"
  },
  "confidence": {
    "overall_score": 0.85,
    "flags": [],
    "hitl_required": false
  }
}
EOF

cat > projects/test_hitl_auto/artifacts/ingest.handoff/confidence_report.json << 'EOF'
{
  "schema_version": "1.0.0",
  "overall_score": 0.85,
  "flags": [],
  "hitl_required": false
}
EOF

# Run with AUTO mode (should auto-approve)
python3 -m dawn.runtime.main --project test_hitl_auto --pipeline - << 'YAML' 2>&1 | tail -10
pipelineId: test_hitl_auto
links:
  - id: hitl.gate
    config:
      mode: AUTO
      auto_approve_if_confidence_gte: 0.7
      require_human_on_flags: true
YAML

if [ -f "projects/test_hitl_auto/artifacts/hitl.gate/approval.json" ]; then
    status=$(python3 -c "import json; a=json.load(open('projects/test_hitl_auto/artifacts/hitl.gate/approval.json')); print(a.get('status'))")
    if [ "$status" = "approved_auto" ]; then
        echo "✓ Auto-approved (high confidence, no flags)"
    else
        echo "✗ Expected auto approval, got: $status"
        exit 1
    fi
else
    echo "✗ Approval artifact missing"
    exit 1
fi

echo ""

# Test 5: AUTO mode with flags (should fall back to BLOCKED)
echo "=== Test 5: AUTO Mode with Flags (Falls Back to BLOCKED) ==="
rm -rf projects/test_hitl_auto_flags
mkdir -p projects/test_hitl_auto_flags/inputs projects/test_hitl_auto_flags/artifacts/ingest.handoff

cat > projects/test_hitl_auto_flags/artifacts/ingest.handoff/project_descriptor.json << 'EOF'
{
  "schema_version": "1.0.0",
  "project_id": "test_hitl_auto_flags",
  "source_bundle": {
    "bundle_sha256": "auto_flags_001"
  },
  "confidence": {
    "overall_score": 0.85,
    "flags": ["critical_issue"],
    "hitl_required": false
  }
}
EOF

cat > projects/test_hitl_auto_flags/artifacts/ingest.handoff/confidence_report.json << 'EOF'
{
  "schema_version": "1.0.0",
  "overall_score": 0.85,
  "flags": ["critical_issue"],
  "hitl_required": false
}
EOF

# Run with AUTO mode (should fall back to BLOCKED)
python3 -m dawn.runtime.main --project test_hitl_auto_flags --pipeline - << 'YAML' 2>&1 | tee /tmp/hitl_test5.log || true
pipelineId: test_hitl_auto_flags
links:
  - id: hitl.gate
    config:
      mode: AUTO
      auto_approve_if_confidence_gte: 0.7
      require_human_on_flags: true
YAML

if grep -q "BLOCKED" /tmp/hitl_test5.log && [ -f "projects/test_hitl_auto_flags/inputs/hitl_approval.json" ]; then
    echo "✓ Fell back to BLOCKED mode (flags present)"
else
    echo "✗ Did not fall back to BLOCKED"
    exit 1
fi

echo ""
echo "=== ✅ ALL HITL GATE TESTS PASSED ==="
echo "  ✓ BLOCKED mode with missing approval"
echo "  ✓ BLOCKED mode with valid approval"
echo "  ✓ Stale approval prevention"
echo "  ✓ AUTO mode auto-approval"
echo "  ✓ AUTO mode fallback to BLOCKED"
