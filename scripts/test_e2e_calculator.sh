#!/bin/bash
# End-to-End Acceptance Test for DAWN Calculator Workflow
# Tests: Requirements -> Patchset -> Applied Code -> Running Tests

set -e  # Exit on any error

PROJECT_ID="calc_e2e_test"
PROJECT_DIR="projects/$PROJECT_ID"

echo "========================================="
echo "DAWN E2E Acceptance Test: Calculator CLI"
echo "========================================="
echo ""

# Cleanup previous test
rm -rf "$PROJECT_DIR"

# Step 1: Create project with calculator requirements
echo "✓ Step 1: Creating project with calculator requirements..."
mkdir -p "$PROJECT_DIR/inputs"

cat > "$PROJECT_DIR/inputs/idea.md" << 'EOF'
# Project: Calculator CLI Tool

## Objective
Create a simple command-line calculator tool.

## Functional Requirements
- Provide a CLI command: `calc "<expression>"`
- Accept expressions like:
  - `2+2`
  - `12 * (3 + 4)`
  - `10/4`
- Support operators: +, -, *, /
- Support parentheses.
- Show helpful errors for invalid expressions.
- Output should be a single line result.

## Non-Functional Requirements
- Must be deterministic.
- Must include basic unit tests.
- Must include a short README with usage examples.
- Avoid unsafe eval. If expression parsing is needed, use a safe parser approach.

## Packaging
- Provide a Python package structure OR a single-file script + tests.
- Provide a run command in README.

## Success Criteria
- Running:
  - `calc "2+2"` prints `4`
  - `calc "12*(3+4)"` prints `84`
- Tests pass.
EOF

echo "  ✓ Created idea.md"

# Step 2: Run app_mvp pipeline
echo ""
echo "✓ Step 2: Running app_mvp pipeline..."
if ! python3 -m dawn.runtime.main \
    --project "$PROJECT_ID" \
    --pipeline dawn/pipelines/golden/app_mvp.yaml > /tmp/dawn_e2e.log 2>&1; then
    echo "  ✗ Pipeline FAILED"
    echo "  Log tail:"
    tail -20 /tmp/dawn_e2e.log
    exit 1
fi
echo "  ✓ Pipeline succeeded"

# Step 3: Verify src/calculator_cli exists
echo ""
echo "✓ Step 3: Verifying code materialization..."
if [ ! -d "$PROJECT_DIR/src/calculator_cli" ]; then
    echo "  ✗ FAILED: src/calculator_cli directory does not exist"
    echo "  Directory contents:"
    ls -la "$PROJECT_DIR/src/" || echo "  (src/ does not exist)"
    exit 2
fi
echo "  ✓ src/calculator_cli exists"

# Verify key files exist
REQUIRED_FILES=(
    "src/calculator_cli/__init__.py"
    "src/calculator_cli/parser.py"
    "src/calculator_cli/cli.py"
    "src/tests/test_calculator.py"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$PROJECT_DIR/$file" ]; then
        echo "  ✗ FAILED: Missing required file: $file"
        exit 2
    fi
done
echo "  ✓ All required Python files present"

# Step 4: Run pytest on generated code
echo ""
echo "✓ Step 4: Running pytest on generated code..."
cd "$PROJECT_DIR/src"
if ! python3 -m pytest tests/test_calculator.py -v > /tmp/pytest_e2e.log 2>&1; then
    echo "  ✗ FAILED: Pytest failed"
    cat /tmp/pytest_e2e.log
    exit 3
fi

# Count passed tests
PASSED=$(grep -c "PASSED" /tmp/pytest_e2e.log || echo "0")
echo "  ✓ Pytest passed ($PASSED tests)"

cd - > /dev/null

# Step 5: Validate calc examples from requirements
echo ""
echo "✓ Step 5: Validating calculator examples..."

# Test: calc "2+2" == 4
RESULT=$(cd "$PROJECT_DIR/src" && python3 -m calculator_cli "2+2" 2>&1)
if [ "$RESULT" != "4" ]; then
    echo "  ✗ FAILED: calc \"2+2\" returned \"$RESULT\", expected \"4\""
    exit 3
fi
echo "  ✓ calc \"2+2\" == 4"

# Test: calc "12*(3+4)" == 84
RESULT=$(cd "$PROJECT_DIR/src" && python3 -m calculator_cli "12*(3+4)" 2>&1)
if [ "$RESULT" != "84" ]; then
    echo "  ✗ FAILED: calc \"12*(3+4)\" returned \"$RESULT\", expected \"84\""
    exit 3
fi
echo "  ✓ calc \"12*(3+4)\" == 84"

# Step 6: Verify artifacts
echo ""
echo "✓ Step 6: Verifying artifacts..."
if [ ! -f "$PROJECT_DIR/artifacts/impl.apply_patchset/applied.json" ]; then
    echo "  ✗ FAILED: apply_receipt artifact missing"
    exit 2
fi
echo "  ✓ apply_receipt artifact exists"

# Success!
echo ""
echo "========================================="
echo "✅ ALL TESTS PASSED"
echo "========================================="
echo ""
echo "Summary:"
echo "  - Requirements parsed from idea.md"
echo "  - Calculator code generated"
echo "  - Code materialized to src/"
echo "  - Pytest: $PASSED tests passed"
echo "  - calc \"2+2\" == 4 ✓"
echo "  - calc \"12*(3+4)\" == 84 ✓"
echo ""
echo "DAWN end-to-end workflow: VERIFIED ✅"
exit 0
