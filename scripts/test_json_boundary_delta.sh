#!/bin/bash
# Test 2: Requirements Delta Must Fail Before Apply
# Framework-level acceptance test

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=== Test 2: Requirements Delta Must Fail Before Apply ==="

# Test with exponent operator
rm -rf projects/test_delta_boundary
mkdir -p projects/test_delta_boundary/inputs

cat > projects/test_delta_boundary/inputs/idea.md << 'EOF'
# Calculator
## Functional Requirements
- Support operators: +, -, *, /, ^

## Success Criteria
- `calc "2+2"` prints `4`
- `calc "2^8"` prints `256`
EOF

# Run pipeline (should fail at validate.requirements_coverage)
echo "Running pipeline (expecting failure)..."
python3 -m dawn.runtime.main \
    --project test_delta_boundary \
    --pipeline dawn/pipelines/golden/app_mvp.yaml \
    2>&1 | tee /tmp/delta_boundary_test.log

EXIT_CODE=$?

# Assert: non-zero exit
if [ $EXIT_CODE -eq 0 ]; then
    echo "❌ FAILED: Pipeline should have failed"
    exit 1
fi

echo "✓ Pipeline failed (EXIT_CODE=$EXIT_CODE)"

# Assert: applied.json does NOT exist
if [ -f "projects/test_delta_boundary/artifacts/impl.apply_patchset/applied.json" ]; then
    echo "❌ FAILED: Code was applied despite validation failure"
    exit 1
fi

echo "✓ Code was NOT applied (no applied.json)"

# Assert: Failed at validate.requirements_coverage
if grep -q "validate.requirements_coverage" /tmp/delta_boundary_test.log; then
    echo "✓ Failed at validate.requirements_coverage"
else
    echo "❌ FAILED: Did not fail at expected link"
    exit 1
fi

# Assert: JSON artifacts were validated
if [ -f "projects/test_delta_boundary/artifacts/validate.json_artifacts" ]; then
    echo "Note: validate.json_artifacts was not reached (expected)"
fi

echo ""
echo "=== ✅ TEST 2 PASSED ==="
echo "Pipeline correctly failed at requirements coverage before apply_patchset"
