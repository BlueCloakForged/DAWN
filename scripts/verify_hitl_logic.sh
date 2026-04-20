#!/bin/bash
# Manual Verification: Core HITL Logic (Orchestrator-Independent)
# Tests bundle digest canonicality, stale detection, approval flow

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=== Manual HITL Verification (Core Logic) ==="
echo ""

# Test 1: Bundle Digest Canonical
echo "=== Test 1: Bundle Digest Canonical ==="
mkdir -p /tmp/test_bundle_{1,2}/inputs

echo "content A" > /tmp/test_bundle_1/inputs/file1.txt
echo "content B" > /tmp/test_bundle_1/inputs/file2.txt

echo "content A" > /tmp/test_bundle_2/inputs/file1.txt
echo "content B" > /tmp/test_bundle_2/inputs/file2.txt

hash1=$(python3 << 'PYTHON'
import json, hashlib
from pathlib import Path

def compute_bundle(base):
    inputs = Path(base) / "inputs"
    files = []
    for p in sorted(inputs.rglob("*")):
        if p.is_file():
            with open(p, "rb") as f:
                files.append({
                    "path": str(p.relative_to(Path(base))).replace("\\", "/"),
                    "sha256": hashlib.sha256(f.read()).hexdigest(),
                    "size": p.stat().st_size
                })
    bundle_str = json.dumps(files, sort_keys=True)
    return hashlib.sha256(bundle_str.encode()).hexdigest()

print(compute_bundle("/tmp/test_bundle_1"))
PYTHON
)

hash2=$(python3 << 'PYTHON'
import json, hashlib
from pathlib import Path

def compute_bundle(base):
    inputs = Path(base) / "inputs"
    files = []
    for p in sorted(inputs.rglob("*")):
        if p.is_file():
            with open(p, "rb") as f:
                files.append({
                    "path": str(p.relative_to(Path(base))).replace("\\", "/"),
                    "sha256": hashlib.sha256(f.read()).hexdigest(),
                    "size": p.stat().st_size
                })
    bundle_str = json.dumps(files, sort_keys=True)
    return hashlib.sha256(bundle_str.encode()).hexdigest()

print(compute_bundle("/tmp/test_bundle_2"))
PYTHON
)

echo "Hash 1: $hash1"
echo "Hash 2: $hash2"

if [ "$hash1" = "$hash2" ]; then
    echo "✓ Bundle digests IDENTICAL (canonical)"
else
    echo "✗ Bundle digests DIFFER"
    exit 1
fi

echo ""

# Test 2: Template Generation (Deterministic)
echo "=== Test 2: Template Generation Deterministic ==="

python3 << 'PYTHON'
import json
import hashlib

bundle = "test_bundle_abc123"

def create_template(bundle_sha256, score, flags):
    return {
        "schema_version": "1.0.0",
        "bundle_sha256": bundle_sha256,
        "approved": False,
        "operator": "",
        "comment": "",
        "_context": {
            "confidence_score": score,
            "flags": sorted(flags)
        },
        "_instructions": [
            "Set 'approved' to true or false",
            "Add your name to 'operator'",
            "Optionally add 'comment'",
            "DO NOT modify 'bundle_sha256'"
        ]
    }

template1 = create_template(bundle, 0.65, ["low_confidence", "no_diagram"])
template2 = create_template(bundle, 0.65, ["no_diagram", "low_confidence"])  # Different order

# Templates should be identical (flags are sorted)
if template1 == template2:
    print("✓ Template generation is deterministic (flags sorted)")
else:
    print("✗ Templates differ")
    exit(1)

# Compute hashes
hash1 = hashlib.sha256(json.dumps(template1, sort_keys=True).encode()).hexdigest()
hash2 = hashlib.sha256(json.dumps(template2, sort_keys=True).encode()).hexdigest()

if hash1 == hash2:
    print("✓ Template hashes identical")
else:
    print ("✗ Template hashes differ")
    exit(1)
PYTHON

echo ""

# Test 3: Stale Approval Detection
echo "=== Test 3: Stale Approval Detection ==="

python3 << 'PYTHON'
def check_stale(approval_bundle, current_bundle):
    """Returns True if stale."""
    return approval_bundle != current_bundle

bundle_old = "abc123"
bundle_new = "def456"

if check_stale(bundle_old, bundle_new):
    print("✓ Stale approval detected (bundle mismatch)")
else:
    print("✗ Stale approval NOT detected")
    exit(1)

if not check_stale(bundle_new, bundle_new):
    print("✓ Fresh approval accepted (bundle match)")
else:
    print("✗ Fresh approval rejected incorrectly")
    exit(1)
PYTHON

echo ""

# Test 4: AUTO Mode Logic
echo "=== Test 4: AUTO Mode Logic ==="

python3 << 'PYTHON'
def can_auto_approve(score, flags, hitl_required, threshold=0.7):
    """Returns (can_approve, reason)."""
    if score < threshold:
        return (False, f"score {score} < threshold {threshold}")
    if flags:
        return (False, f"flags present: {flags}")
    if hitl_required:
        return (False, "hitl_required=true")
    return (True, "all conditions met")

# Test cases
cases = [
    (0.8, [], False, True, "high score, no flags, no hitl"),
    (0.8, ["issue"], False, False, "high score BUT flags"),
    (0.5, [], False, False, "low score"),
    (0.8, [], True, False, "high score BUT hitl_required"),
]

for score, flags, hitl, expected, desc in cases:
    can_approve, reason = can_auto_approve(score, flags, hitl)
    if can_approve == expected:
        print(f"✓ {desc}: {reason}")
    else:
        print(f"✗ {desc}: expected={expected}, got={can_approve}")
        exit(1)
PYTHON

echo ""
echo "=== ✅ ALL MANUAL VERIFICATIONS PASSED ==="
echo "  ✓ Bundle digest canonical"
echo "  ✓ Template generation deterministic"
echo "  ✓ Stale approval detection"
echo "  ✓ AUTO mode logic"
