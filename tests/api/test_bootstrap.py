"""
API tests for the Bootstrap project endpoint.

Tests verify that:
1. POST /api/projects returns correct structure with full project index
2. Project files are created on disk with proper structure
3. Error handling works correctly
"""

import os
import json
import pytest
import shutil
from pathlib import Path
from fastapi.testclient import TestClient

# Import the FastAPI app
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "forgechain_console"))
from server import app
from starlette.testclient import TestClient

client = TestClient(app)

# Test constants
TEST_PROJECT_ID = "pytest_test_project"
TEST_PIPELINE_ID = "handoff_min"
PROJECTS_DIR = Path(__file__).parent.parent.parent / "projects"


@pytest.fixture(autouse=True)
def cleanup_test_project():
    """Clean up test project before and after each test"""
    test_project_path = PROJECTS_DIR / TEST_PROJECT_ID
    if test_project_path.exists():
        shutil.rmtree(test_project_path)
    yield
    if test_project_path.exists():
        shutil.rmtree(test_project_path)


def test_bootstrap_returns_correct_structure():
    """Test that POST /api/projects returns correct response structure"""
    response = client.post(
        "/api/projects",
        json={
            "project_id": TEST_PROJECT_ID,
            "pipeline_id": TEST_PIPELINE_ID,
            "profile": "normal"
        }
    )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    data = response.json()
    
    # Verify top-level structure
    assert "status" in data
    assert data["status"] == "success"
    assert "data" in data
    
    # Verify data structure
    assert "project_id" in data["data"]
    assert data["data"]["project_id"] == TEST_PROJECT_ID
    assert "index" in data["data"]
    
    # Verify index structure
    index = data["data"]["index"]
    assert "schema_version" in index
    assert "project_id" in index
    assert index["project_id"] == TEST_PROJECT_ID
    assert "pipeline" in index
    assert index["pipeline"]["id"] == TEST_PIPELINE_ID
    assert index["pipeline"]["profile"] == "normal"


def test_project_files_created_on_disk():
    """Test that project files are created with proper structure"""
    response = client.post(
        "/api/projects",
        json={
            "project_id": TEST_PROJECT_ID,
            "pipeline_id": TEST_PIPELINE_ID,
            "profile": "normal"
        }
    )
    
    assert response.status_code == 200
    
    # Verify project directory exists
    project_path = PROJECTS_DIR / TEST_PROJECT_ID
    assert project_path.exists(), f"Project directory not found: {project_path}"
    
    # Verify project_index.json exists
    index_path = project_path / "project_index.json"
    assert index_path.exists(), "project_index.json not found"
    
    # Verify inputs directory exists
    inputs_path = project_path / "inputs"
    assert inputs_path.exists(), "inputs directory not found"
    
    # Load and verify index content
    with open(index_path, "r") as f:
        index = json.load(f)
    
    assert index["schema_version"] == "1.0.0"
    assert "created_at" in index
    assert "pipeline" in index
    assert index["pipeline"]["id"] == TEST_PIPELINE_ID


def test_duplicate_project_returns_error():
    """Test that creating a duplicate project returns 400 error"""
    # Create first project
    response1 = client.post(
        "/api/projects",
        json={
            "project_id": TEST_PROJECT_ID,
            "pipeline_id": TEST_PIPELINE_ID,
            "profile": "normal"
        }
    )
    assert response1.status_code == 200
    
    # Try to create duplicate
    response2 = client.post(
        "/api/projects",
        json={
            "project_id": TEST_PROJECT_ID,
            "pipeline_id": TEST_PIPELINE_ID,
            "profile": "normal"
        }
    )
    
    assert response2.status_code == 400
    data = response2.json()
    assert "detail" in data


def test_invalid_pipeline_returns_error():
    """Test that invalid pipeline ID returns 400 error"""
    response = client.post(
        "/api/projects",
        json={
            "project_id": TEST_PROJECT_ID,
            "pipeline_id": "nonexistent_pipeline",
            "profile": "normal"
        }
    )
    
    # Should fail during bootstrap
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data


def test_missing_project_id_returns_error():
    """Test that missing project_id returns 422 validation error"""
    response = client.post(
        "/api/projects",
        json={
            "pipeline_id": TEST_PIPELINE_ID,
            "profile": "normal"
        }
    )
    
    assert response.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
