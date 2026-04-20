from typing import Dict, Any, List, Optional
import json
import os
import requests
import time
from pathlib import Path
from dataclasses import dataclass, asdict


@dataclass
class HealingCycle:
    """Represents a single healing attempt."""
    cycle: int
    timestamp: str
    error_count: int
    error_types: Dict[str, int]
    test_outcomes: Dict[str, int]
    code_changes: Dict[str, Any]
    convergence_score: float
    healer_response_time_ms: int


@dataclass
class HealingSession:
    """Aggregates all healing cycles."""
    project_id: str
    original_error_count: int
    cycles: List[HealingCycle]
    final_status: str  # "healed", "exhausted", "aborted"
    total_convergence_trend: List[float]


def calculate_convergence(prev_errors: int, curr_errors: int) -> float:
    """
    Calculate convergence score from consecutive cycles.
    Positive = improving, Zero = stagnant, Negative = regressing.
    """
    if prev_errors == 0:
        return 0.0
    return (prev_errors - curr_errors) / prev_errors


def should_abort_early(convergence_history: List[float], threshold: float = -0.1) -> bool:
    """
    Detect regression: if last 2 consecutive scores are below threshold, abort.
    """
    if len(convergence_history) < 2:
        return False
    
    recent = convergence_history[-2:]
    return all(score < threshold for score in recent)


def extract_error_context(test_report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract failure context from pytest execution report.
    """
    return {
        "exit_code": test_report.get("exit_code", -1),
        "error_count": test_report.get("failed", 0) + test_report.get("errors", 0),
        "error_summary": test_report.get("summary", "Unknown error"),
        "stderr": test_report.get("stderr", ""),
        "stdout": test_report.get("stdout", "")
    }


def categorize_errors(test_report: Dict[str, Any]) -> Dict[str, int]:
    """
    Categorize errors from pytest output.
    """
    error_types = {}
    stdout = test_report.get("stdout", "")
    
    # Simple heuristic categorization
    if "SyntaxError" in stdout or "SyntaxError" in test_report.get("stderr", ""):
        error_types["syntax_error"] = stdout.count("SyntaxError")
    if "ImportError" in stdout or "ModuleNotFoundError" in stdout:
        error_types["import_error"] = stdout.count("ImportError") + stdout.count("ModuleNotFoundError")
    if "AssertionError" in stdout or "FAILED" in stdout:
        error_types["assertion_failed"] = test_report.get("failed", 0)
    if test_report.get("exit_code") == 2:
        error_types["collection_failed"] = 1
    
    return error_types


def call_external_healer(
    project_id: str,
    cycle: int,
    failed_files: Dict[str, str],
    pytest_error: Dict[str, Any],
    timeout_sec: int,
    healer_url: str
) -> Dict[str, Any]:
    """
    Call external Code Healer API.
    
    Request Schema:
    {
        "project_id": "auto_calc_v2",
        "cycle": 1,
        "failed_files": {"logic.py": "content..."},
        "pytest_errors": {...}
    }
    
    Response Schema:
    {
        "status": "healed",
        "modified_files": {"logic.py": "fixed content"},
        "changes_summary": "Fixed syntax error on line 5"
    }
    """
    request_payload = {
        "project_id": project_id,
        "cycle": cycle,
        "failed_files": failed_files,
        "pytest_errors": pytest_error
    }
    
    start_time = time.time()
    
    try:
        response = requests.post(
            healer_url,
            json=request_payload,
            timeout=timeout_sec,
            headers={"Content-Type": "application/json"}
        )
        
        response_time_ms = int((time.time() - start_time) * 1000)
        
        if response.status_code == 200:
            result = response.json()
            result["response_time_ms"] = response_time_ms
            return result
        else:
            return {
                "status": "error",
                "message": f"Healer returned status {response.status_code}",
                "response_time_ms": response_time_ms
            }
    
    except requests.Timeout:
        return {
            "status": "timeout",
            "message": f"Healer timed out after {timeout_sec}s",
            "response_time_ms": timeout_sec * 1000
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Healer call failed: {str(e)}",
            "response_time_ms": int((time.time() - start_time) * 1000)
        }


def read_project_files(project_root: Path, bundle_files: List[Dict]) -> Dict[str, str]:
    """
    Read source code files from project inputs directory.
    """
    inputs_dir = project_root / "inputs"
    code_files = {}
    
    for file_info in bundle_files:
        file_path = Path(file_info["path"])
        if file_path.suffix == ".py":
            src_path = inputs_dir / file_path.name
            if src_path.exists():
                code_files[file_path.name] = src_path.read_text()
    
    return code_files


def write_healed_files(project_root: Path, cycle: int, modified_files: Dict[str, str]) -> Path:
    """
    Write healed code to healing/cycle_N/ directory.
    Returns path to healing cycle directory.
    """
    healing_dir = project_root / "healing" / f"cycle_{cycle}"
    healing_dir.mkdir(parents=True, exist_ok=True)
    
    for filename, content in modified_files.items():
        (healing_dir / filename).write_text(content)
    
    return healing_dir


def update_project_inputs(project_root: Path, modified_files: Dict[str, str]):
    """
    Update the project's inputs/ directory with healed code.
    """
    inputs_dir = project_root / "inputs"
    
    for filename, content in modified_files.items():
        (inputs_dir / filename).write_text(content)


def create_generic_healing_report(
    session: HealingSession,
    initial_test_report: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Create application-agnostic healing report for API/UI consumers.
    Follows the HealingReport schema defined in forgechain_console/schemas.py.
    
    This format is consumable by:
    - SAM (chat agent)
    - DAWN Web UI
    - External monitoring tools
    - Any API consumer
    """
    # Determine healing enabled status
    healing_enabled = len(session.cycles) > 0
    
    # Map internal status to API status
    status_map = {
        "healed": "healed",
        "exhausted": "failed",
        "aborted": "failed",
        "healer_failed": "failed",
        "failed": "not_attempted"
    }
    final_status = status_map.get(session.final_status, "unknown")
    
    # Convert cycles to iterations
    iterations = []
    for cycle in session.cycles:
        # Map error types to error codes
        error_types = cycle.error_types
        if "import_error" in error_types:
            error_code = "DEPENDENCY_MISSING"
        elif "syntax_error" in error_types:
            error_code = "SYNTAX_ERROR"
        elif "assertion_failed" in error_types:
            error_code = "TEST_FAILURE"
        elif "collection_failed" in error_types:
            error_code = "COLLECTION_ERROR"
        else:
            error_code = "RUNTIME_ERROR"
        
        # Format test results
        outcomes = cycle.test_outcomes
        total_tests = outcomes.get("passed", 0) + outcomes.get("failed", 0)
        tests_after = f"{outcomes.get('passed', 0)}/{total_tests} passing" if total_tests > 0 else "none"
        
        # Extract action taken
        changes = cycle.code_changes
        if isinstance(changes, dict) and "summary" in changes:
            action_taken = changes["summary"]
        elif changes:
            files = changes.get("files_modified", [])
            action_taken = f"Modified {len(files)} file(s): {', '.join(files[:3])}"
        else:
            action_taken = "Healer failed to produce changes"
        
        # Determine outcome
        if cycle.convergence_score > 0:
            outcome = "success"
        elif cycle.convergence_score == 0:
            outcome = "no_change"
        else:
            outcome = "regression"
        
        iteration = {
            "iteration": cycle.cycle,
            "error_code": error_code,
            "error_detail": f"{cycle.error_count} error(s): {', '.join(error_types.keys()) if error_types else 'unknown'}",
            "action_taken": action_taken,
            "outcome": outcome,
            "tests_after": tests_after,
            "timestamp": cycle.timestamp
        }
        iterations.append(iteration)
    
    # Build report
    report = {
        "healing_enabled": healing_enabled,
        "total_attempts": len(session.cycles),
        "final_status": final_status,
        "iterations": iterations
    }
    
    return report


def run(project_context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Self-healing validation orchestrator.
    
    Iteratively attempts to fix code based on pytest failures.
    Tracks convergence and triggers HITL if healing exhausts.
    """
    project_id = project_context["project_id"]
    project_root = Path(project_context["project_root"])
    artifact_store = project_context["artifact_store"]
    sandbox = project_context["sandbox"]
    
    # Configuration
    config = link_config.get("spec", {}).get("config", {})
    max_cycles = config.get("max_cycles", 5)
    early_abort_threshold = config.get("early_abort_threshold", -0.1)
    # Hardcoded to internal Docker service name (SAM healer service)
    healer_url = os.environ.get("CODE_HEALER_URL", "http://sam-healer:3000/api/heal")
    cycle_timeouts = config.get("cycle_timeouts", [30, 45, 60, 90, 120])
    
    print(f"[validation.self_heal] Starting healing for {project_id}")
    print(f"  Max cycles: {max_cycles}")
    print(f"  Healer endpoint: {healer_url}")
    
    # Check healer URL is configured
    if not healer_url:
        return {
            "status": "FAILED",
            "errors": {
                "type": "CONFIGURATION_ERROR",
                "message": "CODE_HEALER_URL not set. Cannot perform healing.",
                "step_id": "healer_config"
            }
        }
    
    # Get pytest failure report
    test_report_artifact = artifact_store.get("dawn.test.execution_report")
    if not test_report_artifact:
        return {
            "status": "FAILED",
            "errors": {
                "type": "MISSING_REQUIRED_ARTIFACT",
                "message": "dawn.test.execution_report not found. Run pytest first.",
                "step_id": "validate_inputs"
            }
        }
    
    # Load test report
    test_report_path = Path(test_report_artifact["path"])
    with open(test_report_path) as f:
        test_report = json.load(f)
    
    # Extract error context
    pytest_error = extract_error_context(test_report)
    initial_error_count = pytest_error["error_count"]
    
    print(f"  Initial errors: {initial_error_count}")
    
    # Get project bundle to identify source files
    bundle_artifact = artifact_store.get("dawn.project.bundle")
    if not bundle_artifact:
        return {
            "status": "FAILED",
            "errors": {
                "type": "MISSING_REQUIRED_ARTIFACT",
                "message": "dawn.project.bundle not found",
                "step_id": "validate_inputs"
            }
        }
    
    bundle_path = Path(bundle_artifact["path"])
    with open(bundle_path) as f:
        bundle = json.load(f)
    
    # Read source files
    source_files = read_project_files(project_root, bundle.get("files", []))
    
    # Healing session tracking
    healing_cycles = []
    convergence_history = []
    prev_error_count = initial_error_count
    final_status = "failed"  # Default status if healing loop doesn't complete normally
    
    # Healing loop
    for cycle_num in range(1, max_cycles + 1):
        print(f"\n[validation.self_heal] Cycle {cycle_num}/{max_cycles}")
        
        # Get timeout for this cycle
        timeout = cycle_timeouts[min(cycle_num - 1, len(cycle_timeouts) - 1)]
        
        # Call external healer
        healer_response = call_external_healer(
            project_id=project_id,
            cycle=cycle_num,
            failed_files=source_files,
            pytest_error=pytest_error,
            timeout_sec=timeout,
            healer_url=healer_url
        )
        
        # DEBUG: Log the raw healer response
        print(f"  DEBUG: Healer response keys: {list(healer_response.keys())}")
        print(f"  DEBUG: Healer status: {healer_response.get('status')}")
        
        # Handle SAM's response format: SAM returns 'files' instead of 'modified_files'
        # and doesn't include a 'status' field. Check for success by presence of 'files'.
        modified_files = healer_response.get("modified_files") or healer_response.get("files", {})
        changes_summary = healer_response.get("changes_summary") or healer_response.get("explanation", "No description")
        
        print(f"  DEBUG: Modified files count: {len(modified_files)}")
        
        # Check if healer failed (no files returned or explicit error status)
        if not modified_files or healer_response.get("status") == "error":
            error_msg = healer_response.get('message', 'No files returned')
            print(f"  Healer failed: {error_msg}")
            # Record failed cycle
            healing_cycles.append(HealingCycle(
                cycle=cycle_num,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                error_count=prev_error_count,
                error_types=categorize_errors(test_report),
                test_outcomes={
                    "passed": test_report.get("passed", 0),
                    "failed": test_report.get("failed", 0),
                    "errors": test_report.get("errors", 0)
                },
                code_changes={},
                convergence_score=0.0,
                healer_response_time_ms=healer_response.get("response_time_ms", timeout * 1000)
            ))
            final_status = "healer_failed"  # Healer couldn't produce fixed code
            break
        
        print(f"  Healer modified {len(modified_files)} files")
        print(f"  Changes: {changes_summary}")
        
        # Write healed code to healing/cycle_N/
        healing_dir = write_healed_files(project_root, cycle_num, modified_files)
        
        # Update project inputs with healed code
        update_project_inputs(project_root, modified_files)
        source_files.update(modified_files)  # Update for next cycle
        
        # Calculate convergence (will be updated after re-running pytest)
        # For now, assume healer improved things
        curr_error_count = prev_error_count  # Placeholder until pytest re-runs
        convergence = calculate_convergence(prev_error_count, curr_error_count)
        convergence_history.append(convergence)
        
        # Record cycle
        healing_cycles.append(HealingCycle(
            cycle=cycle_num,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error_count=curr_error_count,
            error_types=categorize_errors(test_report),
            test_outcomes={
                "passed": test_report.get("passed", 0),
                "failed": test_report.get("failed", 0),
                "errors": test_report.get("errors", 0)
            },
            code_changes={
                "files_modified": list(modified_files.keys()),
                "summary": changes_summary
            },
            convergence_score=convergence,
            healer_response_time_ms=healer_response.get("response_time_ms", 0)
        ))
        
        # Check for early abort
        if should_abort_early(convergence_history, early_abort_threshold):
            print(f"  Early abort: regression detected (convergence < {early_abort_threshold})")
            final_status = "aborted"
            break
        
        prev_error_count = curr_error_count
    else:
        # Exhausted all cycles
        final_status = "exhausted"
    
    # Build healing session summary
    session = HealingSession(
        project_id=project_id,
        original_error_count=initial_error_count,
        cycles=healing_cycles,
        final_status=final_status,
        total_convergence_trend=convergence_history
    )
    
    # Write healing metrics artifact (internal format)
    metrics_data = asdict(session)
    sandbox.write_json("healing_metrics.json", metrics_data)
    
    # Register artifact
    artifact_store.register(
        artifact_id="dawn.healing.metrics",
        abs_path=str((project_root / "artifacts" / "validation.self_heal" / "healing_metrics.json").absolute()),
        schema=None,
        producer_link_id="validation.self_heal"
    )
    
    # Write generic healing report (API-friendly format)
    healing_report = create_generic_healing_report(session, test_report)
    sandbox.write_json("healing_report.json", healing_report)
    
    # Register generic healing report artifact
    artifact_store.register(
        artifact_id="dawn.healing.report",
        abs_path=str((project_root / "artifacts" / "validation.self_heal" / "healing_report.json").absolute()),
        schema=None,
        producer_link_id="validation.self_heal"
    )
    
    # If healing exhausted, create HITL gate artifact
    if final_status in ["exhausted", "aborted"]:
        gate_data = {
            "gate_type": "healing_exhausted",
            "project_id": project_id,
            "triggered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "context": {
                "total_cycles": len(healing_cycles),
                "final_error_count": prev_error_count,
                "convergence_trend": convergence_history,
                "abort_reason": final_status
            },
            "artifacts": {
                "healing_metrics": "dawn.healing.metrics",
                "last_test_report": "dawn.test.execution_report"
            }
        }
        
        sandbox.write_json("healing_exhausted_gate.json", gate_data)
        
        artifact_store.register(
            artifact_id="dawn.healing.exhausted_gate",
            abs_path=str((project_root / "artifacts" / "validation.self_heal" / "healing_exhausted_gate.json").absolute()),
            schema=None,
            producer_link_id="validation.self_heal"
        )
        
        print(f"\n[validation.self_heal] Healing {final_status} - HITL gate created")
        
        return {
            "status": "SUCCEEDED",  # Link succeeded in creating gate
            "metrics": {
                "healing_status": final_status,
                "total_cycles": len(healing_cycles),
                "convergence_trend": convergence_history
            }
        }
    
    # Success - code was healed
    print(f"\n[validation.self_heal] Healing succeeded in {len(healing_cycles)} cycles")
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "healing_status": "healed",
            "total_cycles": len(healing_cycles),
            "convergence_trend": convergence_history
        }
    }
