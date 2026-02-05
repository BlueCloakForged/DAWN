from typing import Dict, Any

def run(project_context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    project_id = project_context["project_id"]
    ledger = project_context["ledger"]
    
    print(f"Running chain.validator for project {project_id}")
    
    # Invariant: quality.gates must SUCCEED
    events = ledger.get_events(link_id="quality.gates")
    succeeded = any(e["status"] == "SUCCEEDED" for e in events)
    
    if not succeeded:
        raise Exception("INVARIANT_VIOLATION: quality.gates MUST succeed before chain.validator")
    
    return {
        "status": "SUCCEEDED",
        "outputs": {},
        "metrics": {
            "duration": 0.1,
            "invariants_checked": 1
        },
        "errors": {
            "invariant_results": [
                {"id": "quality_gates_passed", "passed": succeeded, "message": "quality.gates must succeed"}
            ]
        }
    }
