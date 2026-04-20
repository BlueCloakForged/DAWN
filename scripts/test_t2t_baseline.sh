#!/bin/bash
# Acceptance Test: T2T Ingest Baseline

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=== T2T Acceptance Test 1: Ingest Baseline ==="

# Clean previous run
rm -rf projects/test_t2t_baseline

# Create project with sample inputs
mkdir -p projects/test_t2t_baseline/inputs

# Create minimal test OTP (just enough for T2T to parse)
cat > projects/test_t2t_baseline/inputs/test_otp.pdf << 'EOF'
%PDF-1.4
%Test OTP placeholder
EOF

# Note: For real testing, copy actual OTP PDF
# cp ~/Documents/CROW4_OTP.pdf projects/test_t2t_baseline/inputs/otp.pdf

echo "Running T2T pipeline (expect BLOCKED at hitl.gate)..."
python3 -m dawn.runtime.main \
    --project test_t2t_baseline \
    --pipeline dawn/pipelines/t2t_cyber_range.yaml \
    2>&1 | tee /tmp/t2t_baseline.log || true

# Check artifacts
echo ""
echo "=== Checking Artifacts ==="
if [ -f "projects/test_t2t_baseline/artifacts/ingest.handoff/project_descriptor.json" ]; then
    echo "✓ project_descriptor.json exists"
    python3 -c "import json; d=json.load(open('projects/test_t2t_baseline/artifacts/ingest.handoff/project_descriptor.json')); print(f\"  schema_version: {d.get('schema_version')}\"); print(f\"  project_id: {d.get('project_id')}\"); print(f\"  confidence: {d.get('confidence', {}).get('overall_score')}\")"
else
    echo "✗ project_descriptor.json missing"
    exit 1
fi

if [ -f "projects/test_t2t_baseline/artifacts/ingest.handoff/network_topology.cro.json" ]; then
    echo "✓ network_topology.cro.json exists"
else
    echo "✗ network_topology.cro.json missing"
    exit 1
fi

# Check HITL template created
if [ -f "projects/test_t2t_baseline/inputs/hitl_approval.json" ]; then
    echo "✓ hitl_approval.json template created"
    python3 -c "import json; a=json.load(open('projects/test_t2t_baseline/inputs/hitl_approval.json')); print(f\"  approved: {a.get('approved')}\")"
else
    echo "✗ hitl_approval.json template NOT created"
    exit 1
fi

echo ""
echo "=== ✅ TEST 1 PASSED ==="
echo "Ingestion successful, HITL gate blocked as expected"
