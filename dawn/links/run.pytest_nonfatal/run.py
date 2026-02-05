"""
run.pytest_nonfatal - Non-failing pytest executor for autofix workflows

This link runs pytest but returns SUCCEEDED even when tests fail.
This allows the pipeline to continue to the healing link.

Test failure information is captured in the execution_report artifact.
"""

import json
import subprocess
import tempfile
import shutil
from pathlib import Path


def run(context, config):
    """Execute pytest and capture results WITHOUT failing the pipeline."""
    
    # Reuse the logic from run.pytest
    config = config or {}
    
    artifact_index = context.get("artifact_index", {})
    bundle_artifact = artifact_index.get("dawn.project.bundle")
    
    if not bundle_artifact:
        return {
            "status": "FAILED",
            "errors": {
                "type": "MISSING_REQUIRED_ARTIFACT",
                "message": "dawn.project.bundle artifact not found",
                "step_id": "run"
            }
        }
    
    bundle_path = Path(bundle_artifact["path"])
    if not bundle_path.exists():
        return {
            "status": "FAILED",
            "errors": {
                "type": "RUNTIME_ERROR",
                "message": f"Bundle file not found: {bundle_path}",
                "step_id": "run"
            }
        }
    
    # Load bundle manifest
    try:
        with open(bundle_path) as f:
            bundle = json.load(f)
    except Exception as e:
        return {
            "status": "FAILED",
            "errors": {
                "type": "RUNTIME_ERROR",
                "message": f"Failed to load bundle: {str(e)}",
                "step_id": "run"
            }
        }
    
    # Create temp directory for test execution
    temp_dir = Path(tempfile.mkdtemp(prefix="dawn_pytest_nonfatal_"))
    
    try:
        # Extract Python files from bundle
        project_root = bundle_path.parent.parent.parent
        inputs_dir = project_root / "inputs"
        
        py_files_found = 0
        test_files_found = 0
        
        for file_info in bundle.get("files", []):
            file_path = Path(file_info["path"])
            if file_path.suffix == ".py":
                src_path = inputs_dir / file_path.name
                if src_path.exists():
                    dest_path = temp_dir / file_path.name
                    shutil.copy(src_path, dest_path)
                    py_files_found += 1
                    if file_path.name.startswith("test_"):
                        test_files_found += 1
        
        print(f"run.pytest_nonfatal: Extracted {py_files_found} Python files ({test_files_found} test files)")
        
        # Execute pytest
        pytest_cmd = [
            "pytest",
            "--tb=short",
            "--no-header",
            "-v",
            str(temp_dir)
        ]
        
        print(f"run.pytest_nonfatal: Executing: {' '.join(pytest_cmd)}")
        
        result = subprocess.run(
            pytest_cmd,
            capture_output=True,
            text=True,
            timeout=150,
            cwd=str(temp_dir)
        )
        
        exit_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
        
        # Count test results
        passed_count = stdout.count(" PASSED")
        failed_count = stdout.count(" FAILED")
        error_count = stdout.count(" ERROR")
        
        # Build execution report
        report = {
            "exit_code": exit_code,
            "passed": passed_count,
            "failed": failed_count,
            "errors": error_count,
            "total": passed_count + failed_count + error_count,
            "stdout": stdout[-2000:] if len(stdout) > 2000 else stdout,
            "stderr": stderr[-1000:] if len(stderr) > 1000 else stderr,
            "summary": ""
        }
        
        # Generate summary
        if exit_code == 0:
            report["summary"] = f"All {passed_count} tests passed"
        elif exit_code == 5:
            report["summary"] = "No tests collected"
        elif exit_code == 1:
            report["summary"] = f"{failed_count} test(s) failed, {passed_count} passed"
        elif exit_code == 2:
            report["summary"] = "Test collection failed (syntax error or import error)"
        else:
            report["summary"] = f"pytest exited with code {exit_code}"
        
        # Write report artifact
        context["sandbox"].write_json("pytest_report.json", report)
        
        print(f"run.pytest_nonfatal: {report['summary']}")
        
        # KEY DIFFERENCE: Always return SUCCEEDED, even if tests failed
        # The healing link will check the report and decide what to do
        return {
            "status": "SUCCEEDED",  # Always succeed to allow pipeline continuation
            "metrics": {
                "tests_passed": passed_count,
                "tests_failed": failed_count,
                "tests_error": error_count,
                "pytest_exit_code": exit_code,
                "tests_actually_passed": exit_code == 0
            }
        }
    
    except subprocess.TimeoutExpired:
        context["sandbox"].write_json("pytest_report.json", {
            "exit_code": -1,
            "error": "pytest execution timed out (150s)",
            "passed": 0,
            "failed": 0,
            "errors": 0
        })
        return {
            "status": "SUCCEEDED",  # Still succeed to allow healing
            "metrics": {
                "tests_passed": 0,
                "tests_failed": 1,
                "timeout": True
            }
        }
    except Exception as e:
        context["sandbox"].write_json("pytest_report.json", {
            "exit_code": -1,
            "error": str(e),
            "passed": 0,
            "failed": 0,
            "errors": 0
        })
        return {
            "status": "FAILED",  # Only fail on execution errors, not test failures
            "errors": {
                "type": "RUNTIME_ERROR",
                "message": f"pytest execution failed: {str(e)}",
                "step_id": "run"
            }
        }
    finally:
        # Cleanup temp directory
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
