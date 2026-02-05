import json
import hashlib
import os
from pathlib import Path

def run(context, config):
    project_id = context["project_id"]
    project_root = Path(context["project_root"])
    
    # 1. Get the current patchset digest
    artifacts = context["artifact_index"]
    patchset_path = Path(artifacts["dawn.patchset"]["path"])
    
    with open(patchset_path, "r") as f:
        patchset_content = f.read()
        
    patchset_digest = hashlib.sha256(patchset_content.encode()).hexdigest()
    
    # 2. Check for approval in inputs
    approval_input = project_root / "inputs" / "patch_approval.json"
    
    if not approval_input.exists():
        # Generate a template to help the user
        template = {
            "decision": "PENDING",
            "patchset_digest": patchset_digest,
            "instructions": f"Review the generated patchset at {patchset_path}. To approve, change 'decision' to 'APPROVED' and ensure 'patchset_digest' matches."
        }
        context["sandbox"].write_json("patch_decision_template.json", template)
        
        return {
            "status": "FAILED",
            "errors": {
                "type": "GATE_BLOCKED",
                "message": f"Patch approval required. Template created at projects/{project_id}/artifacts/gate.patch_approval/patch_decision_template.json. Please copy to projects/{project_id}/inputs/patch_approval.json after approval."
            }
        }

    with open(approval_input, "r") as f:
        try:
            approval_data = json.load(f)
        except Exception as e:
            return {
                "status": "FAILED",
                "errors": {"type": "INPUT_ERROR", "message": f"Malformed patch_approval.json: {str(e)}"}
            }

    if approval_data.get("decision") != "APPROVED":
        return {
            "status": "FAILED",
            "errors": {"type": "GATE_REJECTED", "message": "Patch decision is not APPROVED."}
        }

    if approval_data.get("patchset_digest") != patchset_digest:
        return {
            "status": "FAILED",
            "errors": {
                "type": "DIGEST_MISMATCH", 
                "message": f"Approval digest mismatch! Input: {approval_data.get('patchset_digest')}, Actual: {patchset_digest}"
            }
        }

    # 3. Decision recorded
    context["sandbox"].copy_in(str(approval_input), "patch_approval.json")
    
    return {
        "status": "SUCCEEDED"
    }
