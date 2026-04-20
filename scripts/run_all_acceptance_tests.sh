#!/bin/bash
# Master Acceptance Test Runner
# Runs all 5 acceptance tests in sequence

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "DAWN Bundle + HITL Acceptance Test Suite"
echo "=========================================="
echo ""

TESTS=(
    "test_hitl_baseline_blocked.sh"
    "test_hitl_approval_happy.sh"
    "test_hitl_stale_rejection.sh"
    "test_hitl_auto_mode.sh"
    "test_bundle_determinism.sh"
)

PASSED=0
FAILED=0
SKIPPED=0

for test in "${TESTS[@]}"; do
    echo ""
    echo "Running: $test"
    echo "------------------------------------------"
    
    if "$SCRIPT_DIR/$test"; then
        ((PASSED++))
        echo "✓ PASSED: $test"
    else
        EXIT_CODE=$?
        if [ $EXIT_CODE -eq 77 ]; then
            ((SKIPPED++))
            echo "⊘ SKIPPED: $test (dependencies not met)"
        else
            ((FAILED++))
            echo "✗ FAILED: $test"
        fi
    fi
done

echo ""
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo "Passed:  $PASSED / ${#TESTS[@]}"
echo "Failed:  $FAILED / ${#TESTS[@]}"
echo "Skipped: $SKIPPED / ${#TESTS[@]}"
echo "=========================================="

if [ $FAILED -gt 0 ]; then
    exit 1
fi

exit 0
