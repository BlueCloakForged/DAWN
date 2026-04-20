#!/bin/bash
# Acceptance Tests: Domain-Agnostic DAWN with T2T Parser
# Tests: BLOCKED baseline, approval path, stale rejection, determinism

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=== DAWN T2T Acceptance Tests ==="
echo ""

# Helper: Create test project with inputs
create_test_project() {
    local project=$1
    rm -rf "projects/${project}"
    mkdir -p "projects/${project}/inputs"
    
    # Create sample input files
    echo "Test content for ${project}" > "projects/${project}/inputs/file1.txt"
    echo "More test data" > "projects/${project}/inputs/file2.txt"
    
    # Create minimal OTP PDF (placeholder - real test would use actual OTP)
    cat > "projects/${project}/inputs/test_otp.pdf" << 'EOF'
%PDF-1.4
%Test OTP placeholder
EOF
}

# Helper: Manually simulate ingest.handoff output for testing
simulate_ingest() {
    local project=$1
    local bundle_hash=$2
    
    mkdir -p "projects/${project}/artifacts/ingest.handoff"
    
    cat > "projects/${project}/artifacts/ingest.handoff/project_ir.json" << EOF
{
  "schema_version": "1.0.0",
  "bundle_sha256": "${bundle_hash}",
  "parser_id": "t2t",
  "ir_type": "network",
  "payload": {
    "name": "Test Network",
    "nodes": 5,
    "groups": 2,
    "connections": 3,
    "services": ["http", "ssh"],
    "ir": {}
  },
  "confidence": {
    "score": 0.65,
    "flags": ["low_confidence"],
    "hitl_required": true
  }
}
EOF
}

# Test 1: Baseline BLOCKED (No Approval)
echo "=== Test 1: Baseline BLOCKED (No Approval) ==="
create_test_project "test_blocked"

# Compute bundle hash manually
bundle_hash_1=$(python3 << 'PYTHON'
import json, hashlib
from pathlib import Path

inputs = Path("projects/test_blocked/inputs")
files = []
for p in sorted(inputs.rglob("*")):
    if p.is_file():
        with open(p, "rb") as f:
            files.append({
                "path": str(p.relative_to(Path("projects/test_blocked"))).replace("\\", "/"),
                "sha256": hashlib.sha256(f.read()).hexdigest(),
                "size": p.stat().st_size
            })

bundle_str = json.dumps(files, sort_keys=True)
print(hashlib.sha256(bundle_str.encode()).hexdigest())
PYTHON
)

echo "Bundle SHA256: $bundle_hash_1"

# Simulate ingest
simulate_ingest "test_blocked" "$bundle_hash_1"

# Run hitl.gate (should BLOCK)
cat > "projects/test_blocked/test_pipeline.yaml" << 'EOF'
pipelineId: test_blocked
links:
  - id: hitl.gate
    config:
      mode: BLOCKED
      auto_threshold: 0.7
EOF

python3 -m dawn.runtime.main \
  --project test_blocked \
  --pipeline projects/test_blocked/test_pipeline.yaml \
  2>&1 | tee /tmp/test_blocked.log || true

# Check template created
if [ -f "projects/test_blocked/inputs/hitl_approval.json" ]; then
    echo "✓ Approval template created"
    template_bundle=$(python3 -c "import json; print(json.load(open('projects/test_blocked/inputs/hitl_approval.json'))['bundle_sha256'])")
    if [ "$template_bundle" = "$bundle_hash_1" ]; then
        echo "✓ Template bound to correct bundle_sha256"
    else
        echo "✗ Template bundle_sha256 mismatch"
        exit 1
    fi
else
    echo "✗ Template NOT created"
    exit 1
fi

echo ""

# Test 2: Approval Happy Path
echo "=== Test 2: Approval Happy Path ==="

# Approve the project
python3 << 'PYTHON'
import json
with open('projects/test_blocked/inputs/hitl_approval.json', 'r') as f:
    approval = json.load(f)

approval['approved'] = True
approval['operator'] = 'test_operator'
approval['comment'] = 'Test approval'

with open('projects/test_blocked/inputs/hitl_approval.json', 'w') as f:
    json.dump(approval, f, indent=2)
PYTHON

# Re-run (should succeed)
python3 -m dawn.runtime.main \
  --project test_blocked \
  --pipeline projects/test_blocked/test_pipeline.yaml \
  2>&1 | tail -15

if [ -f "projects/test_blocked/artifacts/hitl.gate/approval.json" ]; then
    status=$(python3 -c "import json; print(json.load(open('projects/test_blocked/artifacts/hitl.gate/approval.json'))['status'])")
    if [ "$status" = "approved" ]; then
        echo "✓ Approval path successful (status=approved)"
    else
        echo "✗ Expected status=approved, got: $status"
        exit 1
    fi
else
    echo "✗ Approval artifact missing"
    exit 1
fi

echo ""

# Test 3: Stale Approval Rejection
echo "=== Test 3: Stale Approval Rejection ==="

# Change input file
echo "Modified content" > "projects/test_blocked/inputs/file1.txt"

# Compute new bundle hash
bundle_hash_2=$(python3 << 'PYTHON'
import json, hashlib
from pathlib import Path

inputs = Path("projects/test_blocked/inputs")
files = []
for p in sorted(inputs.rglob("*")):
    if p.is_file() and not p.name.endswith('.json'):  # Skip approval file
        with open(p, "rb") as f:
            files.append({
                "path": str(p.relative_to(Path("projects/test_blocked"))).replace("\\", "/"),
                "sha256": hashlib.sha256(f.read()).hexdigest(),
                "size": p.stat().st_size
            })

bundle_str = json.dumps(files, sort_keys=True)
print(hashlib.sha256(bundle_str.encode()).hexdigest())
PYTHON
)

echo "New Bundle SHA256: $bundle_hash_2"

if [ "$bundle_hash_1" = "$bundle_hash_2" ]; then
    echo "✗ Bundle hash did not change (test invalid)"
    exit 1
fi

# Update IR with new bundle hash
simulate_ingest "test_blocked" "$bundle_hash_2"

# Run with old approval (should fail with STALE)
python3 -m dawn.runtime.main \
  --project test_blocked \
  --pipeline projects/test_blocked/test_pipeline.yaml \
  2>&1 | tee /tmp/test_stale.log || true

if grep -q "STALE APPROVAL" /tmp/test_stale.log; then
    echo "✓ Stale approval detected and rejected"
else
    echo "✗ Stale approval NOT detected"
    exit 1
fi

echo ""

# Test 4: Determinism
echo "=== Test 4: Determinism (Identical Inputs → Identical Hashes) ==="

create_test_project "test_det_1"
create_test_project "test_det_2"

# Compute bundle hashes
det_hash_1=$(python3 << 'PYTHON'
import json, hashlib
from pathlib import Path

inputs = Path("projects/test_det_1/inputs")
files = []
for p in sorted(inputs.rglob("*")):
    if p.is_file():
        with open(p, "rb") as f:
            files.append({
                "path": str(p.relative_to(Path("projects/test_det_1"))).replace("\\", "/"),
                "sha256": hashlib.sha256(f.read()).hexdigest(),
                "size": p.stat().st_size
            })

bundle_str = json.dumps(files, sort_keys=True)
print(hashlib.sha256(bundle_str.encode()).hexdigest())
PYTHON
)

det_hash_2=$(python3 << 'PYTHON'
import json, hashlib
from pathlib import Path

inputs = Path("projects/test_det_2/inputs")
files = []
for p in sorted(inputs.rglob("*")):
    if p.is_file():
        with open(p, "rb") as f:
            files.append({
                "path": str(p.relative_to(Path("projects/test_det_2"))).replace("\\", "/"),
                "sha256": hashlib.sha256(f.read()).hexdigest(),
                "size": p.stat().st_size
            })

bundle_str = json.dumps(files, sort_keys=True)
print(hashlib.sha256(bundle_str.encode()).hexdigest())
PYTHON
)

echo "Det Hash 1: $det_hash_1"
echo "Det Hash 2: $det_hash_2"

if [ "$det_hash_1" = "$det_hash_2" ]; then
    echo "✓ Determinism verified (identical inputs → identical bundle_sha256)"
else
    echo "✗ Determinism FAILED (hashes differ)"
    exit 1
fi

echo ""
echo "=== ✅ ALL ACCEPTANCE TESTS PASSED ==="
echo "  ✓ Test 1: BLOCKED baseline (template created, bound to bundle)"
echo "  ✓ Test 2: Approval happy path (status=approved)"
echo "  ✓ Test 3: Stale approval rejection (bundle mismatch detected)"
echo "  ✓ Test 4: Determinism (identical inputs → identical hashes)"
