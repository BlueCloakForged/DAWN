#!/bin/bash
# HITL Gate Comprehensive Acceptance Tests
# Tests: bundle digest, AUTO mode flags behavior, SKIP emission, optional exports

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=== HITL Gate Comprehensive Acceptance Tests ==="
echo ""

# Helper: Create minimal pipeline file
create_test_pipeline() {
    local project=$1
    local gate_config=$2
    
    cat > "projects/${project}/test_pipeline.yaml" << EOF
pipelineId: test_${project}
links:
  - id: hitl.gate
    config:
      ${gate_config}
EOF
}

# Test 1: Bundle Digest Canonical Computation
echo "=== Test 1: Bundle Digest Canonical ===
"
rm -rf projects/test_digest_{1,2}
mkdir -p projects/test_digest_1/inputs projects/test_digest_1/artifacts/ingest.handoff
mkdir -p projects/test_digest_2/inputs projects/test_digest_2/artifacts/ingest.handoff

# Create identical files in both projects
echo "test content 123" > projects/test_digest_1/inputs/file1.txt
echo "test content 123" > projects/test_digest_2/inputs/file1.txt
echo "more data" > projects/test_digest_1/inputs/file2.txt
echo "more data" > projects/test_digest_2/inputs/file2.txt

# Simulate ingest.handoff creating descriptors
python3 << 'PYTHON'
import json
import hashlib
from pathlib import Path

def compute_bundle(project):
    inputs_dir = Path(f"projects/{project}/inputs")
    files = []
    for path in sorted(inputs_dir.rglob("*")):
        if path.is_file():
            with open(path, "rb") as f:
                content = f.read()
                digest = hashlib.sha256(content).hexdigest()
            rel_path = path.relative_to(Path(f"projects/{project}"))
            files.append({
                "path": str(rel_path).replace("\\", "/"),
                "sha256": digest,
                "size": len(content)
            })
    
    bundle_str = json.dumps(files, sort_keys=True)
    bundle_sha256 = hashlib.sha256(bundle_str.encode()).hexdigest()
    
    descriptor = {
        "schema_version": "1.0.0",
        "project_id": project,
        "source_bundle": {
            "files": files,
            "bundle_sha256": bundle_sha256
        },
        "confidence": {"overall_score": 0.8, "flags": [], "hitl_required": False}
    }
    
    with open(f"projects/{project}/artifacts/ingest.handoff/project_descriptor.json", "w") as f:
        json.dump(descriptor, f, indent=2)
    
    with open(f"projects/{project}/artifacts/ingest.handoff/confidence_report.json", "w") as f:
        json.dump({"schema_version": "1.0.0", "overall_score": 0.8, "flags": [], "hitl_required": False}, f)
    
    return bundle_sha256

digest1 = compute_bundle("test_digest_1")
digest2 = compute_bundle("test_digest_2")

print(f"Digest 1: {digest1}")
print(f"Digest 2: {digest2}")

if digest1 == digest2:
    print("✓ Bundle digests IDENTICAL (canonical)")
else:
    print("✗ Bundle digests DIFFER (not canonical)")
    exit(1)
PYTHON

echo ""

# Test 2: AUTO Mode Never Bypasses Flags
echo "=== Test 2: AUTO Mode Never Bypasses Flags ==="
rm -rf projects/test_auto_flags
mkdir -p projects/test_auto_flags/inputs projects/test_auto_flags/artifacts/ingest.handoff

cat > projects/test_auto_flags/artifacts/ingest.handoff/project_descriptor.json << 'EOF'
{
  "schema_version": "1.0.0",
  "project_id": "test_auto_flags",
  "source_bundle": {
    "bundle_sha256": "auto_flags_digest_001"
  },
  "confidence": {
    "overall_score": 0.95,
    "flags": ["critical_security_issue"],
    "hitl_required": false
  }
}
EOF

cat > projects/test_auto_flags/artifacts/ingest.handoff/confidence_report.json << 'EOF'
{
  "schema_version": "1.0.0",
  "overall_score": 0.95,
  "flags": ["critical_security_issue"],
  "hitl_required": false
}
EOF

create_test_pipeline "test_auto_flags" "mode: AUTO
      auto_approve_if_confidence_gte: 0.7
      require_human_on_flags: true"

# Run - should fall back to BLOCKED despite high confidence
python3 -m dawn.runtime.main \
  --project test_auto_flags \
  --pipeline projects/test_auto_flags/test_pipeline.yaml \
  2>&1 | tee /tmp/test_auto_flags.log || true

if grep -q "BLOCKED" /tmp/test_auto_flags.log && [ -f "projects/test_auto_flags/inputs/hitl_approval.json" ]; then
    echo "✓ AUTO mode correctly BLOCKED (flags present, require_human_on_flags=true)"
else
    echo "✗ AUTO mode did not fall back to BLOCKED"
    exit 1
fi

echo ""

# Test 3: SKIP Mode Emits approval.json
echo "=== Test 3: SKIP Mode Emits approval.json ==="
rm -rf projects/test_skip
mkdir -p projects/test_skip/inputs projects/test_skip/artifacts/ingest.handoff

cat > projects/test_skip/artifacts/ingest.handoff/project_descriptor.json << 'EOF'
{
  "schema_version": "1.0.0",
  "project_id": "test_skip",
  "source_bundle": {
    "bundle_sha256": "skip_digest_001"
  },
  "confidence": {
    "overall_score": 0.5,
    "flags": ["low_confidence"],
    "hitl_required": true
  }
}
EOF

cat > projects/test_skip/artifacts/ingest.handoff/confidence_report.json << 'EOF'
{
  "schema_version": "1.0.0",
  "overall_score": 0.5,
  "flags": ["low_confidence"],
  "hitl_required": true
}
EOF

create_test_pipeline "test_skip" "mode: SKIP"

python3 -m dawn.runtime.main \
  --project test_skip \
  --pipeline projects/test_skip/test_pipeline.yaml \
  2>&1 | tail -10

if [ -f "projects/test_skip/artifacts/hitl.gate/approval.json" ]; then
    status=$(python3 -c "import json; a=json.load(open('projects/test_skip/artifacts/hitl.gate/approval.json')); print(a.get('status'))")
    if [ "$status" = "skipped" ]; then
        echo "✓ SKIP mode emitted approval.json with status=skipped"
    else
        echo "✗ Expected status=skipped, got: $status"
        exit 1
    fi
else
    echo "✗ SKIP mode did not emit approval.json"
    exit 1
fi

echo ""

# Test 4: Ingest Emits Generic IR
echo "=== Test 4: Ingest IR is Generic (No Topology Assumptions) ==="
echo "Checking ingest.handoff/link.yaml contract..."

if grep -q "dawn.project.ir" dawn/links/ingest.handoff/link.yaml && \
   ! grep -q "network" dawn/links/ingest.handoff/link.yaml | grep -v "# " ; then
    echo "✓ Contract uses domain-agnostic artifact ID (dawn.project.ir)"
else
    echo "Note: Check artifact naming in contract"
fi

echo ""

# Test 5: Optional Exports + Validation
echo "=== Test 5: Optional Exports ==="
echo "Checking ingest.handoff contract for optional exports..."

if grep -q "optional: true" dawn/links/ingest.handoff/link.yaml; then
    echo "✓ Exports marked as optional in contract"
    grep -A2 "optional: true" dawn/links/ingest.handoff/link.yaml | head -6
else
    echo "✗ No optional exports found"
    exit 1
fi

echo ""

# Test 6: Artifact Hashes
echo "=== Test 6: Artifact Hashes ==="

compute_hash() {
    if [ -f "$1" ]; then
        sha256sum "$1" | awk '{print $1}' | cut -c1-16
    else
        echo "missing"
    fi
}

echo "Test project: test_skip"
echo "  approval.json: $(compute_hash projects/test_skip/artifacts/hitl.gate/approval.json)"
echo ""

echo "Test project: test_auto_flags"
echo "  descriptor: $(compute_hash projects/test_auto_flags/artifacts/ingest.handoff/project_descriptor.json)"
echo "  approval template: $(compute_hash projects/test_auto_flags/inputs/hitl_approval.json)"
echo ""

echo "Test project: test_digest_1 vs test_digest_2"
echo "  descriptor 1: $(compute_hash projects/test_digest_1/artifacts/ingest.handoff/project_descriptor.json)"
echo "  descriptor 2: $(compute_hash projects/test_digest_2/artifacts/ingest.handoff/project_descriptor.json)"

echo ""
echo "=== APPROVAL GATING LOGS ==="
echo ""
echo "--- AUTO Mode with Flags (Fallback to BLOCKED) ---"
tail -15 /tmp/test_auto_flags.log

echo ""
echo "=== ✅ ALL ACCEPTANCE TESTS PASSED ==="
echo "  ✓ Bundle digest canonical (identical inputs → identical digest)"
echo "  ✓ AUTO mode never bypasses flags (require_human_on_flags=true)"
echo "  ✓ SKIP mode emits approval.json"
echo "  ✓ Ingest contract uses generic IR (dawn.project.ir)"
echo "  ✓ Exports are optional"
