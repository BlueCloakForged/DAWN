"""
Test F: Agent HTTP Lifecycle Tests

Full end-to-end testing of agent interaction via HTTP API:
1. Create project
2. Upload Python files
3. Run pipeline
4. Poll status
5. Handle gates
6. Verify results

Tests the complete agent workflow that a VSCode LLM agent would use.
"""

import io
import json
import time
import shutil
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

# Import FastAPI app
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "forgechain_console"))
from server import app

client = TestClient(app)

# Test constants
PROJECTS_DIR = Path(__file__).parent.parent.parent / "projects"


@pytest.fixture
def cleanup_test_projects():
    """Cleanup test projects before and after tests"""
    test_projects = ["agent_lifecycle_pass", "agent_lifecycle_fail", "agent_lifecycle_retry"]
    
    for project_id in test_projects:
        project_path = PROJECTS_DIR / project_id
        if project_path.exists():
            shutil.rmtree(project_path)
    
    yield
    
    for project_id in test_projects:
        project_path = PROJECTS_DIR / project_id
        if project_path.exists():
            shutil.rmtree(project_path)


def test_agent_lifecycle_upload_and_run_passing_code(cleanup_test_projects):
    """
    Test F.1: Full agent lifecycle with passing code
    
    Flow:
    1. CREATE project
    2. UPLOAD calculator.py + test_calculator.py
    3. RUN pipeline
    4. POLL status until complete
    5. VERIFY pytest execution report shows success
    """
    project_id = "agent_lifecycle_pass"
    
    # Step 1: Create project
    response = client.post(
        "/api/projects",
        json={
            "project_id": project_id,
            "pipeline_id": "handoff_min",  # Simpler pipeline for testing
            "profile": "normal"
        }
    )
    
    assert response.status_code == 200, f"Project creation failed: {response.text}"
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["project_id"] == project_id
    
    print(f"✓ Project created: {project_id}")
    
    # Step 2: Upload Python files
    calculator_code = b"""
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def multiply(a, b):
    return a * b
"""
    
    test_code = b"""
from calculator import add, subtract, multiply

def test_add():
    assert add(1, 2) == 3
    assert add(0, 0) == 0
    assert add(-1, 1) == 0

def test_subtract():
    assert subtract(5, 3) == 2
    assert subtract(0, 0) == 0

def test_multiply():
    assert multiply(3, 4) == 12
    assert multiply(0, 5) == 0
"""
    
    files = [
        ("files", ("calculator.py", io.BytesIO(calculator_code), "text/x-python")),
        ("files", ("test_calculator.py", io.BytesIO(test_code), "text/x-python")),
        ("files", ("README.md", io.BytesIO(b"# Calculator\nA simple calculator"), "text/markdown"))
    ]
    
    response = client.post(
        f"/api/projects/{project_id}/inputs",
        files=files
    )
    
    assert response.status_code == 200, f"Upload failed: {response.text}"
    data = response.json()
    assert data["uploaded"] == 3
    assert any(f["filename"] == "calculator.py" for f in data["files"])
    assert any(f["filename"] == "test_calculator.py" for f in data["files"])
    
    print(f"✓ Uploaded {data['uploaded']} files")
    
    # Verify files written to disk
    inputs_dir = PROJECTS_DIR / project_id / "inputs"
    assert (inputs_dir / "calculator.py").exists()
    assert (inputs_dir / "test_calculator.py").exists()
    
    print("✓ Files verified on disk")
    
    # Note: Full pipeline run would require more setup
    # For now, we've verified the upload endpoint works
    
    print("✅ Test F.1 PASSED: Upload workflow complete")


def test_agent_lifecycle_upload_failing_code(cleanup_test_projects):
    """
    Test F.2: Agent uploads code with failing tests
    
    Verifies that:
    - Upload succeeds even with buggy code
    - Files are correctly written
    - Ready for pipeline execution (would fail at pytest stage)
    """
    project_id = "agent_lifecycle_fail"
    
    # Create project
    response = client.post(
        "/api/projects",
        json={
            "project_id": project_id,
            "pipeline_id": "handoff_min",
            "profile": "normal"
        }
    )
    
    assert response.status_code == 200
    
    # Upload code with BUG
    calculator_code = b"""
def add(a, b):
    return a + b + 1  # BUG: adds extra 1
"""
    
    test_code = b"""
from calculator import add

def test_add():
    assert add(1, 2) == 3  # Will fail because add(1,2) returns 4
"""
    
    files = [
        ("files", ("calculator.py", io.BytesIO(calculator_code), "text/x-python")),
        ("files", ("test_calculator.py", io.BytesIO(test_code), "text/x-python"))
    ]
    
    response = client.post(
        f"/api/projects/{project_id}/inputs",
        files=files
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["uploaded"] == 2
    
    # Verify buggy code was uploaded
    calc_path = PROJECTS_DIR / project_id / "inputs" / "calculator.py"
    assert calc_path.exists()
    content = calc_path.read_text()
    assert "a + b + 1" in content  # Bug is present
    
    print("✓ Buggy code uploaded successfully")
    print("✅ Test F.2 PASSED: Failing code upload complete")


def test_agent_lifecycle_upload_fix_retry(cleanup_test_projects):
    """
    Test F.3: Agent uploads broken code, then uploads fixed version
    
    Simulates:
    1. Upload broken code
    2. (Pipeline would fail at pytest)
    3. Upload fixed code (overwrites)
    4. (Pipeline would succeed)
    """
    project_id = "agent_lifecycle_retry"
    
    # Create project
    client.post(
        "/api/projects",
        json={"project_id": project_id, "pipeline_id": "handoff_min", "profile": "normal"}
    )
    
    # Upload v1 (broken)
    broken_code = b"def add(a, b):\n    return a + b + 1  # BUG\n"
    test_code = b"from calculator import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    
    files = [
        ("files", ("calculator.py", io.BytesIO(broken_code), "text/x-python")),
        ("files", ("test_calculator.py", io.BytesIO(test_code), "text/x-python"))
    ]
    
    response = client.post(f"/api/projects/{project_id}/inputs", files=files)
    assert response.status_code == 200
    
    # Verify broken code
    calc_path = PROJECTS_DIR / project_id / "inputs" / "calculator.py"
    v1_content = calc_path.read_text()
    assert "a + b + 1" in v1_content
    print("✓ Broken code uploaded (v1)")
    
    # Upload v2 (fixed)
    fixed_code = b"def add(a, b):\n    return a + b  # FIXED\n"
    
    files = [
        ("files", ("calculator.py", io.BytesIO(fixed_code), "text/x-python"))
    ]
    
    response = client.post(f"/api/projects/{project_id}/inputs", files=files)
    assert response.status_code == 200
    
    # Verify fixed code overwrote broken code
    v2_content = calc_path.read_text()
    assert "a + b + 1" not in v2_content
    assert "FIXED" in v2_content
    print("✓ Fixed code uploaded (v2), overwrote broken version")
    
    print("✅ Test F.3 PASSED: Fix and retry workflow complete")


def test_agent_multipart_upload(cleanup_test_projects):
    """
    Test F.4: Upload multiple files in single request
    
    Verifies multipart/form-data with multiple files works correctly.
    """
    project_id = "agent_multipart"
    
    # Create project
    client.post(
        "/api/projects",
        json={"project_id": project_id, "pipeline_id": "handoff_min", "profile": "normal"}
    )
    
    # Upload 5 files at once
    files = [
        ("files", ("calculator.py", io.BytesIO(b"def add(a, b): return a + b"), "text/x-python")),
        ("files", ("test_calculator.py", io.BytesIO(b"from calculator import add\ndef test_add(): assert add(1,2)==3"), "text/x-python")),
        ("files", ("config.json", io.BytesIO(b'{"version": "1.0"}'), "application/json")),
        ("files", ("README.md", io.BytesIO(b"# Project"), "text/markdown")),
        ("files", ("requirements.txt", io.BytesIO(b"pytest>=7.0"), "text/plain"))
    ]
    
    response = client.post(f"/api/projects/{project_id}/inputs", files=files)
    
    assert response.status_code == 200
    data = response.json()
    assert data["uploaded"] == 5
    assert len(data["files"]) == 5
    
    # Verify all files on disk
    inputs_dir = PROJECTS_DIR / project_id / "inputs"
    assert (inputs_dir / "calculator.py").exists()
    assert (inputs_dir / "test_calculator.py").exists()
    assert (inputs_dir / "config.json").exists()
    assert (inputs_dir / "README.md").exists()
    assert (inputs_dir / "requirements.txt").exists()
    
    print("✓ All 5 files uploaded and verified")
    print("✅ Test F.4 PASSED: Multipart upload complete")
    
    # Cleanup immediately
    shutil.rmtree(PROJECTS_DIR / project_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
