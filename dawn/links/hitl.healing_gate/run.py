"""
HITL Healing Gate - Manual intervention when self-healing exhausts

Blocks pipeline execution until human reviews healing history 
and decides to:
1. Override and continue (manual code fix applied)
2. Reject the build
"""

import json
from pathlib import Path
from typing import Dict, Any


class HealingBlockedError(Exception):
    """Raised when healing is exhausted and requires human intervention."""
    pass


def run(context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    HITL gate for exhausted healing cycles.
    
    Requires human to review healing history and manually resolve.
    """
    project_root = Path(context["project_root"])
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    
    # Load exhausted gate artifact
    gate_artifact = artifact_store.get("dawn.healing.exhausted_gate")
    if not gate_artifact:
        return {
            "status": "FAILED",
            "errors": {
                "type": "MISSING_REQUIRED_ARTIFACT",
                "message": "dawn.healing.exhausted_gate not found",
                "step_id": "validate_inputs"
            }
        }
    
    with open(gate_artifact["path"]) as f:
        gate_data = json.load(f)
    
    # Load healing metrics for history
    metrics_artifact = artifact_store.get("dawn.healing.metrics")
    if metrics_artifact:
        with open(metrics_artifact["path"]) as f:
            healing_metrics = json.load(f)
    else:
        healing_metrics = {}
    
    # Extract context
    project_id = gate_data["project_id"]
    total_cycles = gate_data["context"]["total_cycles"]
    final_error_count = gate_data["context"]["final_error_count"]
    convergence_trend = gate_data["context"]["convergence_trend"]
    abort_reason = gate_data["context"]["abort_reason"]
    
    # Check for resolution file
    resolution_file = project_root / "inputs" / "healing_resolution.json"
    
    if not resolution_file.exists():
        # First time - create template and block
        template = {
            "project_id": project_id,
            "resolution": "",  # "override" or "reject"
            "operator": "",
            "comment": "",
            "timestamp_utc": "",
            "_context": {
                "healing_status": abort_reason,
                "total_cycles": total_cycles,
                "final_error_count": final_error_count,
                "convergence_trend": convergence_trend
            },
            "_instructions": [
                "Set 'resolution' to 'override' (manual fix applied) or 'reject' (abort build)",
                "Add your name to 'operator'",
                "Add comment explaining resolution",
                "Re-run pipeline after resolving"
            ]
        }
        
        resolution_file.parent.mkdir(parents=True, exist_ok=True)
        with open(resolution_file, 'w') as f:
            json.dump(template, f, indent=2, sort_keys=True)
        
        # Log to diagnostic if available
        print(f"\n{'='*80}")
        print(f"  HEALING EXHAUSTED - HUMAN INTERVENTION REQUIRED")
        print(f"{'='*80}")
        print(f"Project: {project_id}")
        print(f"Status: {abort_reason.upper()}")
        print(f"Healing Cycles: {total_cycles}")
        print(f"Remaining Errors: {final_error_count}")
        print(f"Convergence Trend: {convergence_trend}")
        print(f"\nHealing History:")
        print(f"  Location: {project_root / 'healing' / 'cycle_*'}")
        print(f"\nAction Required:")
        print(f"  1. Review healing attempts: {project_root / 'healing'}")
        print(f"  2. Review final errors in latest pytest report")
        print(f"  3. Manually fix code in {project_root / 'inputs'}")
        print(f"  4. Edit resolution file: {resolution_file}")
        print(f"  5. Set 'resolution': 'override' (or 'reject')")
        print(f"  6. Re-run pipeline")
        print(f"{'='*80}\n")
        
        # Write blocked status artifact
        blocked_status = {
            "status": "blocked",
            "reason": "healing_exhausted",
            "resolution_file": str(resolution_file),
            "healing_metrics": healing_metrics
        }
        sandbox.publish("dawn.hitl.healing_resolution", "healing_resolution.json", blocked_status, "json")
        
        raise HealingBlockedError(
            f"HEALING EXHAUSTED: {total_cycles} cycles failed to fix code.\\n\\n"
            f"Status: {abort_reason}\\n"
            f"Remaining Errors: {final_error_count}\\n"
            f"Convergence: {convergence_trend}\\n\\n"
            f"Action Required:\\n"
            f"  1. Review healing history: {project_root / 'healing'}\\n"
            f"  2. Manually fix code in: {project_root / 'inputs'}\\n"
            f"  3. Update resolution: {resolution_file}\\n"
            f"  4. Set 'resolution': 'override' or 'reject'\\n"
            f"  5. Re-run pipeline\\n\\n"
            f"Template created at: {resolution_file}"
        )
    
    # Resolution file exists - read decision
    with open(resolution_file) as f:
        resolution_data = json.load(f)
    
    resolution = resolution_data.get("resolution", "").lower()
    operator = resolution_data.get("operator", "unknown")
    comment = resolution_data.get("comment", "")
    
    if resolution == "override":
        # Human manually fixed code - continue pipeline
        print(f"\n[hitl.healing_gate] OVERRIDE: Human intervention by {operator}")
        print(f"  Comment: {comment}")
        
        approval_status = {
            "status": "override",
            "operator": operator,
            "comment": comment,
            "healing_cycles": total_cycles
        }
        sandbox.publish("dawn.hitl.healing_resolution", "healing_resolution.json", approval_status, "json")
        
        return {
            "status": "SUCCEEDED",
            "metrics": {
                "resolution": "override",
                "operator": operator,
                "healing_cycles": total_cycles
            }
        }
    
    elif resolution == "reject":
        # Human rejected build
        print(f"\n[hitl.healing_gate] REJECTED: Build rejected by {operator}")
        print(f"  Comment: {comment}")
        
        rejection_status = {
            "status": "rejected",
            "operator": operator,
            "comment": comment
        }
        sandbox.publish("dawn.hitl.healing_resolution", "healing_resolution.json", rejection_status, "json")
        
        return {
            "status": "FAILED",
            "errors": {
                "type": "HEALING_REJECTED",
                "message": f"Build rejected by {operator}: {comment}",
                "step_id": "hitl_resolution"
            }
        }
    
    else:
        # Invalid resolution
        return {
            "status": "FAILED",
            "errors": {
                "type": "INVALID_RESOLUTION",
                "message": f"Invalid resolution '{resolution}'. Must be 'override' or 'reject'.",
                "step_id": "validate_resolution"
            }
        }
