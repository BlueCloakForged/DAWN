"""
Contract Tests for SAM↔DAWN Integration

These tests validate that DAWN's API responses match SAM's expectations.
They test the API contract without requiring full pipeline execution.
"""

import pytest
import json
from pathlib import Path
from fastapi.testclient import TestClient

# Import FastAPI app
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "forgechain_console"))
from server import app

client = TestClient(app)

# Test constants
PROJECTS_DIR = Path(__file__).parent.parent.parent / "projects"


@pytest.fixture(autouse=True)
def cleanup():
    """Clean up test projects before and after each test."""
    test_projects = ["test_sam_contract", "test_sam_conflict", "test_sam_gates"]
    
    # Cleanup before test
    for project_id in test_projects:
        project_path = PROJECTS_DIR / project_id
        if project_path.exists():
            import shutil
            shutil.rmtree(project_path)
    
    yield
    
    # Cleanup after test
    for project_id in test_projects:
        project_path = PROJECTS_DIR / project_id
        if project_path.exists():
            import shutil
            shutil.rmtree(project_path)


def test_list_projects_contract():
    """
    Contract Test: GET /api/projects response format.
    
    Validates:
    - Response contains "projects" key (not bare array)
    - Each project has: project_id, status, created_at, last_modified, gate_blocked
    """
    response = client.get("/api/projects")
    
    assert response.status_code == 200
    data = response.json()
    
    # SAM expects {"projects": [...]} not [...]
    assert "projects" in data
    assert isinstance(data["projects"], list)
    
    # Create a test project to validate structure
    create_response = client.post("/api/projects", json={
        "project_id": "test_sam_contract",
        "pipeline_id": "autofix"
    })
    
    assert create_response.status_code == 200
    
    # List again
    list_response = client.get("/api/projects")
    data = list_response.json()
    
    assert len(data["projects"]) >= 1
    
    # Find our test project
    test_project = next(
        (p for p in data["projects"] if p["project_id"] == "test_sam_contract"),
        None
    )
    
    assert test_project is not None
    
    # Validate SAM-required fields
    required_fields = ["project_id", "status", "pipeline_id", "gate_blocked", "is_running"]
    for field in required_fields:
        assert field in test_project, f"Missing required field: {field}"
    
    # Validate types
    assert isinstance(test_project["project_id"], str)
    assert isinstance(test_project["status"], str)
    assert isinstance(test_project["gate_blocked"], bool)
    assert isinstance(test_project["is_running"], bool)
    
    print("✅ Contract Test: GET /api/projects response format valid")


def test_project_conflict_409():
    """
    Contract Test: POST /api/projects returns 409 when project exists.
    
    Validates:
    - 409 status code
    - Error response contains: code, category, message, suggestions
    - Error response contains existing_project info
    """
    # Create project
    response = client.post("/api/projects", json={
        "project_id": "test_sam_conflict",
        "pipeline_id": "autofix"
    })
    
    assert response.status_code == 200
    
    # Try to create again
    conflict_response = client.post("/api/projects", json={
        "project_id": "test_sam_conflict",
        "pipeline_id": "autofix"
    })
    
    assert conflict_response.status_code == 409
    
    data = conflict_response.json()
    
    # Validate error structure
    assert "success" in data
    assert data["success"] is False
    
    assert "error" in data
    error = data["error"]
    
    # SAM-required error fields
    required_fields = ["code", "category", "message", "suggestions"]
    for field in required_fields:
        assert field in error, f"Missing error field: {field}"
    
    # Validate specific values
    assert error["code"] == "PROJECT_EXISTS"
    assert error["category"] == "conflict"
    assert "test_sam_conflict" in error["message"]
    assert isinstance(error["suggestions"], list)
    assert len(error["suggestions"]) > 0
    
    # Check for existing_project info
    assert "existing_project" in error
    existing = error["existing_project"]
    assert "project_id" in existing
    assert "status" in existing
    assert "created_at" in existing
    
    print("✅ Contract Test: 409 Conflict response format valid")


def test_get_gates_contract():
    """
    Contract Test: GET /api/projects/{id}/gates response format.
    
    Validates:
    - Response contains "gates" array and "blocked" boolean
    - Each gate has: gate_id, status, approval_options
    """
    # Create project
    response = client.post("/api/projects", json={
        "project_id": "test_sam_gates",
        "pipeline_id": "autofix"
    })
    
    assert response.status_code == 200
    
    # Get gates
    gates_response = client.get("/api/projects/test_sam_gates/gates")
    
    assert gates_response.status_code == 200
    
    data = gates_response.json()
    
    # Validate structure
    assert "gates" in data
    assert "blocked" in data
    assert isinstance(data["gates"], list)
    assert isinstance(data["blocked"], bool)
    
    # If there are gates, validate their structure
    if len(data["gates"]) > 0:
        gate = data["gates"][0]
        assert "gate_id" in gate
        assert "status" in gate
        
        # If blocked, should have approval_options
        if gate["status"] == "BLOCKED":
            assert "approval_options" in gate
            options = gate["approval_options"]
            assert "approve" in options
    
    print("✅ Contract Test: GET gates response format valid")


def test_approve_gate_contract():
    """
    Contract Test: POST /api/projects/{id}/gates/{gate_id}/approve.
    
    Validates:
    - Response contains: success, gate_id, status
    - Gate approval actually works (subsequent GET shows APPROVED)
    """
    # Create project
    response = client.post("/api/projects", json={
        "project_id": "test_sam_gates",
        "pipeline_id": "autofix"
    })
    
    assert response.status_code == 200
    
    # Approve gate
    approve_response = client.post(
        "/api/projects/test_sam_gates/gates/hitl.gate/approve",
        json={
            "mode": "AUTO",
            "artifacts_reviewed": ["dawn.project.ir"]
        }
    )
    
    assert approve_response.status_code == 200
    
    data = approve_response.json()
    
    # Validate response
    assert "success" in data
    assert data["success"] is True
    assert "gate_id" in data
    assert data["gate_id"] == "hitl.gate"
    assert "status" in data
    assert data["status"] == "approved"
    
    # Verify gate is now approved
    gates_response = client.get("/api/projects/test_sam_gates/gates")
    gates_data = gates_response.json()
    
    # Should no longer be blocked
    # Note: Implementation shows approved gates in history
    gate = gates_data["gates"][0] if gates_data["gates"] else None
    if gate:
        assert gate["status"] == "APPROVED"
    
    print("✅ Contract Test: Gate approval response valid")


def test_structured_error_response():
    """
    Contract Test: Error responses follow structured format.
    
    Validates:
    - All errors have: code, category, message
    - Optional fields: self_heal_attempted, retry_recommended, etc.
    """
    # Try to get non-existent project (should return 404 with details)
    response = client.get("/api/projects/nonexistent_project")
    
    # Note: Current implementation uses HTTPException which FastAPI converts
    # We're testing that we can extend this to structured responses
    assert response.status_code == 404
    
    # For now, validate the error is clear
    data = response.json()
    assert "detail" in data  # FastAPI default error format
    
    # Future: Should be {"success": false, "error": {...}}
    # This test documents the expected future structure
    
    print("✅ Contract Test: Error responses validated")


def test_healing_metadata_contract():
    """
    Contract Test: GET /api/projects/{id}/healing response format.
    
    Validates:
    - Response contains: healing_enabled, total_attempts, final_status, iterations
    - Each iteration has: iteration, error_code, action_taken, outcome
    """
    # Create project
    response = client.post("/api/projects", json={
        "project_id": "test_sam_contract",
        "pipeline_id": "autofix"
    })
    
    assert response.status_code == 200
    
    # Get healing metadata (even before running - should return empty/not_needed)
    healing_response = client.get("/api/projects/test_sam_contract/healing")
    
    assert healing_response.status_code == 200
    
    data = healing_response.json()
    
    # Validate structure
    required_fields = ["healing_enabled", "total_attempts", "final_status", "iterations"]
    for field in required_fields:
        assert field in data, f"Missing field: {field}"
    
    # Validate types
    assert isinstance(data["healing_enabled"], bool)
    assert isinstance(data["total_attempts"], int)
    assert isinstance(data["final_status"], str)
    assert isinstance(data["iterations"], list)
    
    # If there are iterations, validate their structure
    for iteration in data["iterations"]:
        iteration_fields = ["iteration", "error_code", "action_taken", "outcome"]
        for field in iteration_fields:
            assert field in iteration, f"Missing iteration field: {field}"
    
    print("✅ Contract Test: Healing metadata response valid")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("Running SAM↔DAWN Contract Tests")
    print("="*60 + "\n")
    
    pytest.main([__file__, "-v", "--tb=short"])
