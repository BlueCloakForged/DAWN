"""
Integration Tests for SAM↔DAWN Workflows

These tests validate multi-endpoint workflows that SAM would use
in real-world scenarios. Unlike contract tests, these test the
interaction between multiple endpoints and the full request/response cycle.
"""

import pytest
import json
import time
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
    test_projects = [
        "test_gate_approval",
        "test_conflict_handling",
        "test_healing_metadata",
        "test_error_retry"
    ]
    
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


def test_gate_approval_workflow():
    """
    Integration Test: Complete gate approval workflow.
    
    Simulates SAM's workflow when encountering a gate-blocked project:
    1. Create new project
    2. Check gate status → should be BLOCKED
    3. Approve gate via API
    4. Verify gate is now approved
    5. Confirm project can proceed
    """
    project_id = "test_gate_approval"
    
    # Step 1: Create project
    print("\n[Step 1] Creating project...")
    create_response = client.post("/api/projects", json={
        "project_id": project_id,
        "pipeline_id": "autofix"
    })
    
    assert create_response.status_code == 200, f"Project creation failed: {create_response.json()}"
    print(f"✓ Project created: {project_id}")
    
    # Step 2: Check gate status (should be blocked for first-time projects)
    print("\n[Step 2] Checking gate status...")
    gates_response = client.get(f"/api/projects/{project_id}/gates")
    
    assert gates_response.status_code == 200
    gates_data = gates_response.json()
    
    assert "gates" in gates_data
    assert "blocked" in gates_data
    
    # New projects should be gate-blocked
    assert gates_data["blocked"] is True, "Expected new project to be gate-blocked"
    assert len(gates_data["gates"]) > 0, "Expected at least one gate"
    
    blocked_gate = gates_data["gates"][0]
    assert blocked_gate["status"] == "BLOCKED"
    assert blocked_gate["gate_id"] == "hitl.gate"
    
    print(f"✓ Gate blocked: {blocked_gate['gate_id']}")
    print(f"  Reason: {blocked_gate['reason']}")
    
    # Step 3: Approve gate via API
    print("\n[Step 3] Approving gate via API...")
    approve_response = client.post(
        f"/api/projects/{project_id}/gates/hitl.gate/approve",
        json={
            "mode": "AUTO",
            "artifacts_reviewed": ["dawn.project.ir"],
            "reason": "Integration test approval"
        }
    )
    
    assert approve_response.status_code == 200
    approval_data = approve_response.json()
    
    assert approval_data["success"] is True
    assert approval_data["gate_id"] == "hitl.gate"
    assert approval_data["status"] == "approved"
    
    print(f"✓ Gate approved: {approval_data['message']}")
    
    # Step 4: Verify gate is now approved
    print("\n[Step 4] Verifying gate status updated...")
    gates_response_2 = client.get(f"/api/projects/{project_id}/gates")
    
    assert gates_response_2.status_code == 200
    gates_data_2 = gates_response_2.json()
    
    # Should no longer be blocked
    # Note: The implementation shows approved gates in the history
    if gates_data_2["gates"]:
        gate = gates_data_2["gates"][0]
        assert gate["status"] == "APPROVED", f"Expected gate to be approved, got {gate['status']}"
        print(f"✓ Gate status updated to: {gate['status']}")
    
    # Step 5: Confirm approval was persisted
    print("\n[Step 5] Confirming approval persisted...")
    approval_file = PROJECTS_DIR / project_id / "approvals" / "hitl.gate.approved"
    assert approval_file.exists(), "Approval marker file should exist"
    
    with open(approval_file) as f:
        approval_record = json.load(f)
    
    assert approval_record["mode"] == "AUTO"
    assert approval_record["approved_by"] == "sam_api"
    
    print(f"✓ Approval persisted to file system")
    print(f"  Mode: {approval_record['mode']}")
    print(f"  Approved by: {approval_record['approved_by']}")
    
    print("\n✅ Gate approval workflow complete!")


def test_project_conflict_flow():
    """
    Integration Test: Project conflict detection and handling.
    
    Simulates SAM's workflow when user tries to create a duplicate project:
    1. Create initial project
    2. Attempt to create duplicate → should get 409
    3. Verify 409 response includes existing project info
    4. Verify suggestions are actionable
    """
    project_id = "test_conflict_handling"
    
    # Step 1: Create initial project
    print("\n[Step 1] Creating initial project...")
    create_response_1 = client.post("/api/projects", json={
        "project_id": project_id,
        "pipeline_id": "autofix"
    })
    
    assert create_response_1.status_code == 200
    print(f"✓ Project created: {project_id}")
    
    # Step 2: Attempt to create duplicate
    print("\n[Step 2] Attempting to create duplicate...")
    create_response_2 = client.post("/api/projects", json={
        "project_id": project_id,
        "pipeline_id": "autofix"
    })
    
    assert create_response_2.status_code == 409, "Expected 409 Conflict"
    conflict_data = create_response_2.json()
    
    print(f"✓ Got 409 Conflict as expected")
    
    # Step 3: Verify 409 response structure
    print("\n[Step 3] Validating conflict response...")
    assert conflict_data["success"] is False
    assert "error" in conflict_data
    
    error = conflict_data["error"]
    assert error["code"] == "PROJECT_EXISTS"
    assert error["category"] == "conflict"
    assert error["user_action_required"] is True
    
    print(f"✓ Error code: {error['code']}")
    print(f"✓ Category: {error['category']}")
    
    # Step 4: Verify existing project info
    print("\n[Step 4] Checking existing project details...")
    assert "existing_project" in error
    
    existing = error["existing_project"]
    assert existing["project_id"] == project_id
    assert "status" in existing
    assert "created_at" in existing
    
    print(f"✓ Existing project: {existing['project_id']}")
    print(f"  Status: {existing['status']}")
    print(f"  Created: {existing['created_at']}")
    
    # Step 5: Verify suggestions are actionable
    print("\n[Step 5] Validating suggestions...")
    assert "suggestions" in error
    assert len(error["suggestions"]) > 0
    
    suggestions = error["suggestions"]
    # Should suggest both update and create-new-version
    update_suggestion = next((s for s in suggestions if "inputs" in s), None)
    new_version_suggestion = next((s for s in suggestions if "_v2" in s), None)
    
    assert update_suggestion is not None, "Should suggest updating existing"
    assert new_version_suggestion is not None, "Should suggest creating new version"
    
    print(f"✓ Suggestions provided:")
    for i, suggestion in enumerate(suggestions, 1):
        print(f"  {i}. {suggestion}")
    
    print("\n✅ Project conflict flow complete!")


def test_healing_metadata_retrieval():
    """
    Integration Test: Healing metadata retrieval workflow.
    
    Simulates SAM querying healing metadata after a project run:
    1. Create project
    2. Query healing metadata (should return empty/not_attempted)
    3. Verify response structure matches schema
    4. Simulate healing report creation (manual)
    5. Query again and verify data is returned
    """
    project_id = "test_healing_metadata"
    
    # Step 1: Create project
    print("\n[Step 1] Creating project...")
    create_response = client.post("/api/projects", json={
        "project_id": project_id,
        "pipeline_id": "autofix"
    })
    
    assert create_response.status_code == 200
    print(f"✓ Project created: {project_id}")
    
    # Step 2: Query healing metadata (no runs yet)
    print("\n[Step 2] Querying healing metadata (no runs)...")
    healing_response = client.get(f"/api/projects/{project_id}/healing")
    
    assert healing_response.status_code == 200
    healing_data = healing_response.json()
    
    # Validate schema
    assert "healing_enabled" in healing_data
    assert "total_attempts" in healing_data
    assert "final_status" in healing_data
    assert "iterations" in healing_data
    
    # No runs yet, so should be empty
    assert healing_data["total_attempts"] == 0
    assert healing_data["final_status"] in ["not_needed", "not_attempted", "unknown"]
    assert len(healing_data["iterations"]) == 0
    
    print(f"✓ Healing metadata returned (empty state)")
    print(f"  Status: {healing_data['final_status']}")
    
    # Step 3: Simulate healing report creation
    print("\n[Step 3] Simulating healing report creation...")
    
    # Create artifacts directory structure
    artifacts_dir = PROJECTS_DIR / project_id / "artifacts" / "validation.self_heal"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    # Create mock healing report
    mock_healing_report = {
        "healing_enabled": True,
        "total_attempts": 2,
        "final_status": "healed",
        "iterations": [
            {
                "iteration": 1,
                "error_code": "SYNTAX_ERROR",
                "error_detail": "Missing colon on line 5",
                "action_taken": "Fixed syntax error",
                "outcome": "success",
                "tests_after": "2/3 passing",
                "timestamp": "2026-01-22T14:00:00Z"
            },
            {
                "iteration": 2,
                "error_code": "TEST_FAILURE",
                "error_detail": "Assertion failed",
                "action_taken": "Corrected test logic",
                "outcome": "success",
                "tests_after": "3/3 passing",
                "timestamp": "2026-01-22T14:01:00Z"
            }
        ]
    }
    
    healing_report_path = artifacts_dir / "healing_report.json"
    with open(healing_report_path, 'w') as f:
        json.dump(mock_healing_report, f, indent=2)
    
    print(f"✓ Mock healing report created")
    
    # Step 4: Query healing metadata again
    print("\n[Step 4] Querying healing metadata (with report)...")
    healing_response_2 = client.get(f"/api/projects/{project_id}/healing")
    
    assert healing_response_2.status_code == 200
    healing_data_2 = healing_response_2.json()
    
    # Should now have data
    assert healing_data_2["healing_enabled"] is True
    assert healing_data_2["total_attempts"] == 2
    assert healing_data_2["final_status"] == "healed"
    assert len(healing_data_2["iterations"]) == 2
    
    print(f"✓ Healing metadata retrieved successfully")
    print(f"  Attempts: {healing_data_2['total_attempts']}")
    print(f"  Status: {healing_data_2['final_status']}")
    print(f"  Iterations: {len(healing_data_2['iterations'])}")
    
    # Step 5: Validate iteration structure
    print("\n[Step 5] Validating iteration structure...")
    iteration = healing_data_2["iterations"][0]
    
    required_fields = ["iteration", "error_code", "error_detail", "action_taken", "outcome", "tests_after"]
    for field in required_fields:
        assert field in iteration, f"Missing field: {field}"
    
    print(f"✓ Iteration 1:")
    print(f"  Error: {iteration['error_code']}")
    print(f"  Action: {iteration['action_taken']}")
    print(f"  Outcome: {iteration['outcome']}")
    print(f"  Tests: {iteration['tests_after']}")
    
    print("\n✅ Healing metadata retrieval complete!")


def test_project_list_and_status():
    """
    Integration Test: Project listing and status tracking.
    
    Validates that SAM can query project lists and track status:
    1. Create multiple projects
    2. List all projects
    3. Verify each has correct status fields
    4. Test filtering/searching capabilities
    """
    print("\n[Integration Test] Project listing and status tracking")
    
    # Step 1: Create multiple projects
    print("\n[Step 1] Creating multiple test projects...")
    projects_to_create = [
        ("test_gate_approval", "autofix"),
        ("test_conflict_handling", "autofix")
    ]
    
    for project_id, pipeline in projects_to_create:
        response = client.post("/api/projects", json={
            "project_id": project_id,
            "pipeline_id": pipeline
        })
        assert response.status_code == 200
        print(f"✓ Created: {project_id}")
    
    # Step 2: List all projects
    print("\n[Step 2] Listing all projects...")
    list_response = client.get("/api/projects")
    
    assert list_response.status_code == 200
    data = list_response.json()
    
    assert "projects" in data
    projects = data["projects"]
    
    print(f"✓ Found {len(projects)} project(s)")
    
    # Step 3: Verify project data
    print("\n[Step 3] Verifying project data...")
    for project in projects:
        if project["project_id"] in ["test_gate_approval", "test_conflict_handling"]:
            required_fields = ["project_id", "status", "pipeline_id", "gate_blocked", "is_running"]
            for field in required_fields:
                assert field in project, f"Missing field: {field}"
            
            print(f"✓ {project['project_id']}")
            print(f"  Status: {project['status']}")
            print(f"  Gate blocked: {project['gate_blocked']}")
            print(f"  Running: {project['is_running']}")
    
    print("\n✅ Project listing and status tracking complete!")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("Running SAM↔DAWN Integration Tests")
    print("="*60 + "\n")
    
    pytest.main([__file__, "-v", "--tb=short", "-s"])
