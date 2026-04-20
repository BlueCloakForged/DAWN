"""
Test run.pytest link in isolation.

Creates a minimal test scenario with passing and failing tests
to verify the link correctly executes pytest and reports results.
"""

import json
import shutil
import tempfile
from pathlib import Path
import importlib.util

# Load run.py module directly
link_path = Path(__file__).parent.parent / "dawn" / "links" / "run.pytest" / "run.py"
spec = importlib.util.spec_from_file_location("run_pytest", link_path)
run_pytest_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_pytest_module)
run_pytest = run_pytest_module.run


def test_pytest_link_passing_tests():
    """Test: run.pytest with all tests passing"""
    
    # Create temp project structure
    temp_project = Path(tempfile.mkdtemp(prefix="test_pytest_"))
    
    try:
        inputs_dir = temp_project / "inputs"
        inputs_dir.mkdir()
        
        artifacts_dir = temp_project / "artifacts" / "ingest.project_bundle"
        artifacts_dir.mkdir(parents=True)
        
        # Create Python files
        (inputs_dir / "calculator.py").write_text("""
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b
""")
        
        (inputs_dir / "test_calculator.py").write_text("""
from calculator import add, subtract

def test_add():
    assert add(1, 2) == 3
    assert add(0, 0) == 0

def test_subtract():
    assert subtract(5, 3) == 2
""")
        
        # Create bundle manifest
        bundle = {
            "bundle_sha256": "test123",
            "files": [
                {"path": "calculator.py", "sha256": "abc123"},
                {"path": "test_calculator.py", "sha256": "def456"}
            ]
        }
        
        bundle_path = artifacts_dir / "dawn.project.bundle.json"
        with open(bundle_path, 'w') as f:
            json.dump(bundle, f)
        
        # Create sandbox mock
        class MockSandbox:
            def __init__(self, artifact_dir):
                self.artifact_dir = Path(artifact_dir)
                self.artifact_dir.mkdir(parents=True, exist_ok=True)
            
            def write_json(self, filename, data):
                with open(self.artifact_dir / filename, 'w') as f:
                    json.dump(data, f, indent=2)
        
        sandbox_dir = temp_project / "artifacts" / "run.pytest"
        
        # Create context
        context = {
            "artifact_index": {
                "dawn.project.bundle": {
                    "path": str(bundle_path)
                }
            },
            "sandbox": MockSandbox(sandbox_dir)
        }
        
        # Execute link
        result = run_pytest(context)
        
        print("Result:", json.dumps(result, indent=2))
        
        # Verify result
        assert result["status"] == "SUCCEEDED", f"Expected SUCCEEDED, got {result['status']}"
        assert result["metrics"]["tests_passed"] >= 2, "Expected at least 2 passing tests"
        
        # Verify artifact was created
        report_path = sandbox_dir / "pytest_report.json"
        assert report_path.exists(), "pytest_report.json not created"
        
        with open(report_path) as f:
            report = json.load(f)
        
        assert report["exit_code"] == 0, f"Expected exit code 0, got {report['exit_code']}"
        assert report["passed"] >= 2, f"Expected >= 2 passed, got {report['passed']}"
        assert report["failed"] == 0, f"Expected 0 failed, got {report['failed']}"
        
        print("✓ run.pytest link working correctly")
        print(f"  Tests passed: {report['passed']}")
        print(f"  Exit code: {report['exit_code']}")
        print(f"  Summary: {report['summary']}")
        
        return True
    
    finally:
        # Cleanup
        if temp_project.exists():
            shutil.rmtree(temp_project)


def test_pytest_link_failing_tests():
    """Test: run.pytest with failing tests"""
    
    temp_project = Path(tempfile.mkdtemp(prefix="test_pytest_fail_"))
    
    try:
        inputs_dir = temp_project / "inputs"
        inputs_dir.mkdir()
        
        artifacts_dir = temp_project / "artifacts" / "ingest.project_bundle"
        artifacts_dir.mkdir(parents=True)
        
        # Create Python files with failing test
        (inputs_dir / "calculator.py").write_text("""
def add(a, b):
    return a + b + 1  # BUG: adds 1 extra
""")
        
        (inputs_dir / "test_calculator.py").write_text("""
from calculator import add

def test_add():
    assert add(1, 2) == 3  # Will fail
""")
        
        # Create bundle
        bundle = {
            "bundle_sha256": "test456",
            "files": [
                {"path": "calculator.py", "sha256": "abc"},
                {"path": "test_calculator.py", "sha256": "def"}
            ]
        }
        
        bundle_path = artifacts_dir / "dawn.project.bundle.json"
        with open(bundle_path, 'w') as f:
            json.dump(bundle, f)
        
        # Mock sandbox
        class MockSandbox:
            def __init__(self, artifact_dir):
                self.artifact_dir = Path(artifact_dir)
                self.artifact_dir.mkdir(parents=True, exist_ok=True)
            
            def write_json(self, filename, data):
                with open(self.artifact_dir / filename, 'w') as f:
                    json.dump(data, f, indent=2)
        
        sandbox_dir = temp_project / "artifacts" / "run.pytest"
        
        context = {
            "artifact_index": {
                "dawn.project.bundle": {
                    "path": str(bundle_path)
                }
            },
            "sandbox": MockSandbox(sandbox_dir)
        }
        
        # Execute link (should FAIL)
        result = run_pytest(context)
        
        print("Result:", json.dumps(result, indent=2))
        
        # Verify failure detected
        assert result["status"] == "FAILED", f"Expected FAILED, got {result['status']}"
        assert result["metrics"]["tests_failed"] >= 1, "Expected at least 1 failing test"
        
        # Verify report
        report_path = sandbox_dir / "pytest_report.json"
        with open(report_path) as f:
            report = json.load(f)
        
        assert report["exit_code"] == 1, f"Expected exit code 1, got {report['exit_code']}"
        assert report["failed"] >= 1, f"Expected >= 1 failed, got {report['failed']}"
        
        print("✓ run.pytest correctly detects test failures")
        print(f"  Tests failed: {report['failed']}")
        print(f"  Summary: {report['summary']}")
        
        return True
    
    finally:
        if temp_project.exists():
            shutil.rmtree(temp_project)


if __name__ == "__main__":
    print("Testing run.pytest link...\n")
    
    print("=== Test 1: Passing Tests ===")
    test_pytest_link_passing_tests()
    
    print("\n=== Test 2: Failing Tests ===")
    test_pytest_link_failing_tests()
    
    print("\n✅ All run.pytest link tests passed!")
