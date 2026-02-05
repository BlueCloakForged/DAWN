"""
run.pytest Link - Execute pytest on uploaded Python code

Contract:
- Requires: dawn.project.bundle
- Produces: dawn.test.execution_report (pytest_report.json)

Security:
- Runs in isolation profile (no src/ writes)
- Subprocess whitelist: python3, pytest only
- 300s timeout (150s effective with 0.5x multiplier)

Exit Code Logic:
- 0: All tests passed → SUCCEEDED
- 1: Tests failed → FAILED (with details)
- 2: Test collection error → FAILED
- 5: No tests collected → SUCCEEDED (warning)
"""

import json
import subprocess
import tempfile
import shutil
from pathlib import Path


def run(context, config):
    """Execute pytest and capture results."""
    
    # Safety: ensure config is usable even if Orchestrator passes None
    config = config or {}
    
    # Resolve dawn.project.bundle artifact
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
    temp_dir = Path(tempfile.mkdtemp(prefix="dawn_pytest_"))
    
    try:
        # Extract Python files from bundle
        project_root = bundle_path.parent.parent.parent  # artifacts/link_id/file.json → project root
        inputs_dir = project_root / "inputs"
        
        py_files_found = 0
        test_files_found = 0
        
        for file_info in bundle.get("files", []):
            file_path = Path(file_info["path"])
            if file_path.suffix == ".py":
                # Copy to temp directory
                src_path = inputs_dir / file_path.name
                if src_path.exists():
                    dest_path = temp_dir / file_path.name
                    shutil.copy(src_path, dest_path)
                    py_files_found += 1
                    if file_path.name.startswith("test_"):
                        test_files_found += 1
        
        print(f"run.pytest: Extracted {py_files_found} Python files ({test_files_found} test files)")
        
        # Execute pytest with JSON report
        pytest_cmd = [
            "pytest",
            "--tb=short",  # Short traceback format
            "--no-header",  # No pytest header
            "-v",  # Verbose output
            str(temp_dir)
        ]
        
        print(f"run.pytest: Executing: {' '.join(pytest_cmd)}")
        
        result = subprocess.run(
            pytest_cmd,
            capture_output=True,
            text=True,
            timeout=150,  # 150s (effective timeout with 0.5x multiplier)
            cwd=str(temp_dir)
        )
        
        # Parse pytest exit code
        # 0: All tests passed
        # 1: Tests failed
        # 2: Test execution error (collection failed)
        # 3: Internal error
        # 4: pytest command line usage error
        # 5: No tests collected
        
        exit_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
        
        # Count test results from stdout
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
            "stdout": stdout[-2000:] if len(stdout) > 2000 else stdout,  # Last 2000 chars
            "stderr": stderr[-1000:] if len(stderr) > 1000 else stderr,  # Last 1000 chars
            "summary": ""
        }
        
        # Determine status and summary
        if exit_code == 0:
            report["summary"] = f"All {passed_count} tests passed"
            status = "SUCCEEDED"
        elif exit_code == 5:
            report["summary"] = "No tests collected (warning)"
            status = "SUCCEEDED"  # Not a failure, just no tests
        elif exit_code == 1:
            report["summary"] = f"{failed_count} test(s) failed, {passed_count} passed"
            status = "FAILED"
        elif exit_code == 2:
            report["summary"] = "Test collection failed (syntax error or import error)"
            status = "FAILED"
        else:
            report["summary"] = f"pytest exited with code {exit_code}"
            status = "FAILED"
        
        # Write pytest_report.json artifact
        context["sandbox"].write_json("pytest_report.json", report)
        
        print(f"run.pytest: {report['summary']}")
        
        if status == "FAILED":
            return {
                "status": "FAILED",
                "metrics": {
                    "tests_passed": passed_count,
                    "tests_failed": failed_count,
                    "tests_error": error_count
                },
                "errors": {
                    "type": "RUNTIME_ERROR",
                    "message": report["summary"],
                    "step_id": "run"
                }
            }
        else:
            return {
                "status": "SUCCEEDED",
                "metrics": {
                    "tests_passed": passed_count,
                    "tests_failed": failed_count,
                    "tests_error": error_count
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
            "status": "FAILED",
            "errors": {
                "type": "BUDGET_TIMEOUT",
                "message": "pytest execution timed out after 150 seconds",
                "step_id": "run"
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
            "status": "FAILED",
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
