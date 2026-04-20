import os
import json
import shutil
from pathlib import Path

def run(context, config):
    project_root = context["project_root"]
    project_id = context["project_id"]
    link_id = "gate.human_review"
    
    out_dir = os.path.join(project_root, "artifacts", link_id)
    os.makedirs(out_dir, exist_ok=True)
    
    inputs_dir = os.path.join(project_root, "inputs")
    decision_input_path = os.path.join(inputs_dir, "human_decision.json")
    artifact_path = os.path.join(out_dir, "human_decision.json")
    
    # Template decision
    template = {
        "project_id": project_id,
        "decision": "PENDING", # APPROVED, REJECTED, PENDING
        "reviewer": "USER",
        "notes": "Please change decision to APPROVED to proceed.",
        "timestamp": ""
    }
    
    if not os.path.exists(decision_input_path):
        # Create template if missing so user knows what to fill
        artifact_path = context["sandbox"].write_json("human_decision.json", template)
            
        error_msg = f"Missing human_decision.json in projects/{project_id}/inputs/. A template has been created at {artifact_path}."
        print(f"Gate BLOCKED: {error_msg}")
        return {
            "status": "FAILED",
            "errors": {"type": "GATE_BLOCKED", "message": error_msg}
        }
    
    # Read the decision
    try:
        with open(decision_input_path, "r") as f:
            decision_data = json.load(f)
            
        # Copy to artifacts for lineage
        artifact_path = context["sandbox"].copy_in(decision_input_path, "human_decision.json")
        
        decision = decision_data.get("decision", "PENDING").upper()
        if decision == "APPROVED":
            print(f"Gate PASSED: Human review approved for project {project_id}")
            return {
                "status": "SUCCEEDED",
                "metrics": {"decision": "APPROVED", "reviewer": decision_data.get("reviewer")}
            }
        else:
            error_msg = f"Human review decision is {decision} for project {project_id}."
            print(f"Gate BLOCKED: {error_msg}")
            return {
                "status": "FAILED",
                "errors": {"type": "GATE_REJECTED", "message": error_msg}
            }
            
    except Exception as e:
        error_msg = f"Failed to read human_decision.json: {str(e)}"
        print(f"Gate ERROR: {error_msg}")
        return {
            "status": "FAILED",
            "errors": {"type": "FORMAT_ERROR", "message": error_msg}
        }
