#!/bin/bash
# Manual Verification Script for Console Bootstrap Fix
# This script provides step-by-step instructions for manual testing

set -e

echo "======================================="
echo "Console Bootstrap Fix - Manual Verification"
echo "======================================="
echo ""

echo "Prerequisites:"
echo "1. Server should be running at http://127.0.0.1:3434"
echo "2. Browser should be ready for testing"
echo ""

read -p "Press Enter to continue..."

echo ""
echo "Test 1: API Response Structure"
echo "--------------------------------------"
echo "Testing that /api/projects returns correct structure..."
echo ""

# Create a test project via API
RESPONSE=$(curl -s -X POST http://localhost:3434/api/projects \
  -H "Content-Type: application/json" \
  -d '{"project_id": "manual_test_verify", "pipeline_id": "handoff_min", "profile": "normal"}')

echo "Response:"
echo "$RESPONSE" | python3 -m json.tool

# Check if response contains required fields
if echo "$RESPONSE" | grep -q '"status"' && echo "$RESPONSE" | grep -q '"success"'; then
    echo "✅ Response contains 'status: success'"
else
    echo "❌ Response missing 'status: success'"
    exit 1
fi

if echo "$RESPONSE" | grep -q '"project_id"' && echo "$RESPONSE" | grep -q '"manual_test_verify"'; then
    echo "✅ Response contains project_id"
else
    echo "❌ Response missing project_id"
    exit 1
fi

if echo "$RESPONSE" | grep -q '"index"'; then
    echo "✅ Response contains index"
else
    echo "❌ Response missing index"
    exit 1
fi

echo ""
echo "Test 2: Project Files Created"
echo "--------------------------------------"

if [ -d "projects/manual_test_verify" ]; then
    echo "✅ Project directory created"
else
    echo "❌ Project directory not found"
    exit 1
fi

if [ -f "projects/manual_test_verify/project_index.json" ]; then
    echo "✅ project_index.json created"
else
    echo "❌ project_index.json not found"
    exit 1
fi

if [ -d "projects/manual_test_verify/inputs" ]; then
    echo "✅ inputs directory created"
else
    echo "❌ inputs directory not found"
    exit 1
fi

echo ""
echo "Test 3: Index Content"
echo "--------------------------------------"

INDEX_CONTENT=$(cat projects/manual_test_verify/project_index.json)
echo "$INDEX_CONTENT" | python3 -m json.tool | head -20

if echo "$INDEX_CONTENT" | grep -q '"schema_version"'; then
    echo "✅ Index contains schema_version"
else
    echo "❌ Index missing schema_version"
    exit 1
fi

if echo "$INDEX_CONTENT" | grep -q '"pipeline"'; then
    echo "✅ Index contains pipeline"
else
    echo "❌ Index missing pipeline"
    exit 1
fi

echo ""
echo "======================================="
echo "API Tests: PASSED ✅"
echo "======================================="
echo ""

echo "Now perform manual UI testing:"
echo ""
echo "Step 1: Open http://127.0.0.1:3434 in browser"
echo "Step 2: Click 'New Project' button"
echo "Step 3: Fill in:"
echo "        - Project ID: ui_test_calc"
echo "        - Pipeline: handoff_min (v1.0.0)"
echo "        - Profile: Normal (Local Dev)"
echo "Step 4: Click 'Bootstrap Project'"
echo ""
echo "Expected Results:"
echo "✅ Modal closes"
echo "✅ Project 'ui_test_calc' appears in left panel WITH SELECTION HIGHLIGHT"
echo "✅ Right panel shows project details:"
echo "   - Project name: ui_test_calc"
echo "   - Pipeline: handoff_min"
echo "   - Profile: normal"
echo "   - Status: PENDING or READY"
echo "✅ Inputs section shows 'idea.md'"
echo ""
echo "If ALL of the above are true, the bootstrap auto-selection is working!"
echo ""

# Cleanup
echo "Cleaning up test project..."
rm -rf projects/manual_test_verify
echo "✅ Cleanup complete"

echo ""
echo "Manual verification script complete!"
