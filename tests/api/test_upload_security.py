"""
Security tests for POST /api/projects/{project_id}/inputs endpoint.

Tests verify mandatory security constraints:
1. Blocks hitl_*.json files (agents cannot write approvals)
2. Blocks .dawn_* files (internal manifests)
3. Validates file extensions
4. Prevents path traversal
5. Enforces file size limits
"""

import os
import io
import pytest
import shutil
from pathlib import Path
from fastapi.testclient import TestClient

# Import the FastAPI app
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "forgechain_console"))
from server import app

client = TestClient(app)

# Test constants
TEST_PROJECT_ID = "pytest_upload_test"
PROJECTS_DIR = Path(__file__).parent.parent.parent / "projects"


@pytest.fixture(autouse=True)
def setup_test_project():
    """Create and cleanup test project"""
    project_path = PROJECTS_DIR / TEST_PROJECT_ID
    
    # Create minimal project structure
    project_path.mkdir(parents=True, exist_ok=True)
    inputs_dir = project_path / "inputs"
    inputs_dir.mkdir(exist_ok=True)
    
    # Create minimal project_index.json
    index_path = project_path / "project_index.json"
    index_path.write_text('{"project_id": "' + TEST_PROJECT_ID + '", "schema_version": "1.0.0"}')
    
    yield
    
    # Cleanup
    if project_path.exists():
        shutil.rmtree(project_path)


def test_upload_blocked_hitl_approval_file():
    """Test: Reject hitl_approval.json (security violation)"""
    files = [
        ("files", ("hitl_approval.json", io.BytesIO(b'{"approved": true}'), "application/json"))
    ]
    
    response = client.post(
        f"/api/projects/{TEST_PROJECT_ID}/inputs",
        files=files
    )
    
    assert response.status_code == 400
    assert "Security violation" in response.json()["detail"]
    assert "hitl_*.json" in response.json()["detail"]
    
    # Verify file NOT written
    input_path = PROJECTS_DIR / TEST_PROJECT_ID / "inputs" / "hitl_approval.json"
    assert not input_path.exists()


def test_upload_blocked_hitl_patch_approval():
    """Test: Reject hitl_patch_approval.json"""
    files = [
        ("files", ("hitl_patch_approval.json", io.BytesIO(b'{"decision": "APPROVED"}'), "application/json"))
    ]
    
    response = client.post(
        f"/api/projects/{TEST_PROJECT_ID}/inputs",
        files=files
    )
    
    assert response.status_code == 400
    assert "Security violation" in response.json()["detail"]


def test_upload_blocked_dawn_manifest():
    """Test: Reject .dawn_artifacts.json (internal manifest)"""
    files = [
        ("files", (".dawn_artifacts.json", io.BytesIO(b'{}'), "application/json"))
    ]
    
    response = client.post(
        f"/api/projects/{TEST_PROJECT_ID}/inputs",
        files=files
    )
    
    assert response.status_code == 400
    assert "Security violation" in response.json()["detail"]
    assert ".dawn_*" in response.json()["detail"]


def test_upload_blocked_dawn_manifest_json():
    """Test: Reject .dawn_manifest.json"""
    files = [
        ("files", (".dawn_manifest.json", io.BytesIO(b'{}'), "application/json"))
    ]
    
    response = client.post(
        f"/api/projects/{TEST_PROJECT_ID}/inputs",
        files=files
    )
    
    assert response.status_code == 400
    assert "Security violation" in response.json()["detail"]


def test_upload_valid_python_file():
    """Test: Allow valid .py file upload"""
    python_code = b"def add(a, b):\n    return a + b\n"
    files = [
        ("files", ("calculator.py", io.BytesIO(python_code), "text/x-python"))
    ]
    
    response = client.post(
        f"/api/projects/{TEST_PROJECT_ID}/inputs",
        files=files
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["uploaded"] == 1
    assert data["files"][0]["filename"] == "calculator.py"
    assert data["files"][0]["size"] == len(python_code)
    
    # Verify file written correctly
    input_path = PROJECTS_DIR / TEST_PROJECT_ID / "inputs" / "calculator.py"
    assert input_path.exists()
    assert input_path.read_bytes() == python_code


def test_upload_multiple_files():
    """Test: Upload multiple files in single request"""
    files = [
        ("files", ("calculator.py", io.BytesIO(b"def add(a, b): return a + b"), "text/x-python")),
        ("files", ("test_calculator.py", io.BytesIO(b"def test_add(): assert add(1,2) == 3"), "text/x-python")),
        ("files", ("README.md", io.BytesIO(b"# Calculator"), "text/markdown"))
    ]
    
    response = client.post(
        f"/api/projects/{TEST_PROJECT_ID}/inputs",
        files=files
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["uploaded"] == 3
    assert len(data["files"]) == 3
    
    # Verify all files written
    inputs_dir = PROJECTS_DIR / TEST_PROJECT_ID / "inputs"
    assert (inputs_dir / "calculator.py").exists()
    assert (inputs_dir / "test_calculator.py").exists()
    assert (inputs_dir / "README.md").exists()


def test_upload_invalid_extension():
    """Test: Reject .sh file (not in allowed list)"""
    files = [
        ("files", ("malicious.sh", io.BytesIO(b"#!/bin/bash\nrm -rf /"), "application/x-sh"))
    ]
    
    response = client.post(
        f"/api/projects/{TEST_PROJECT_ID}/inputs",
        files=files
    )
    
    assert response.status_code == 400
    assert "File extension not allowed" in response.json()["detail"]


def test_upload_invalid_extension_exe():
    """Test: Reject .exe file"""
    files = [
        ("files", ("virus.exe", io.BytesIO(b"MZ"), "application/octet-stream"))
    ]
    
    response = client.post(
        f"/api/projects/{TEST_PROJECT_ID}/inputs",
        files=files
    )
    
    assert response.status_code == 400
    assert "File extension not allowed" in response.json()["detail"]


def test_upload_path_traversal_dotdot():
    """Test: Reject filename with .. (path traversal)"""
    files = [
        ("files", ("../etc/passwd", io.BytesIO(b"root:x:0:0"), "text/plain"))
    ]
    
    response = client.post(
        f"/api/projects/{TEST_PROJECT_ID}/inputs",
        files=files
    )
    
    assert response.status_code == 400
    assert "path traversal" in response.json()["detail"].lower()


def test_upload_path_traversal_slash():
    """Test: Reject filename with / (path traversal)"""
    files = [
        ("files", ("subdir/malicious.py", io.BytesIO(b"print('bad')"), "text/x-python"))
    ]
    
    response = client.post(
        f"/api/projects/{TEST_PROJECT_ID}/inputs",
        files=files
    )
    
    assert response.status_code == 400
    assert "path traversal" in response.json()["detail"].lower()


def test_upload_file_too_large():
    """Test: Reject file exceeding 10MB limit"""
    # Create 11MB file
    large_content = b"x" * (11 * 1024 * 1024)
    files = [
        ("files", ("large.txt", io.BytesIO(large_content), "text/plain"))
    ]
    
    response = client.post(
        f"/api/projects/{TEST_PROJECT_ID}/inputs",
        files=files
    )
    
    assert response.status_code == 413
    assert "File too large" in response.json()["detail"]


def test_upload_project_not_found():
    """Test: Return 404 for non-existent project"""
    files = [
        ("files", ("test.py", io.BytesIO(b"print('hello')"), "text/x-python"))
    ]
    
    response = client.post(
        "/api/projects/nonexistent_project/inputs",
        files=files
    )
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_upload_json_file():
    """Test: Allow .json file upload (but not hitl_*.json)"""
    files = [
        ("files", ("config.json", io.BytesIO(b'{"key": "value"}'), "application/json"))
    ]
    
    response = client.post(
        f"/api/projects/{TEST_PROJECT_ID}/inputs",
        files=files
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["files"][0]["filename"] == "config.json"


def test_upload_checksum_returned():
    """Test: Verify checksum is returned in response"""
    content = b"def test(): pass"
    files = [
        ("files", ("test.py", io.BytesIO(content), "text/x-python"))
    ]
    
    response = client.post(
        f"/api/projects/{TEST_PROJECT_ID}/inputs",
        files=files
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "checksum" in data["files"][0]
    assert len(data["files"][0]["checksum"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
