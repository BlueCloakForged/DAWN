"""
HITL Gate Link - Policy-Driven File-Based Approval

Modes:
  BLOCKED: Fail-fast until human approval file exists with matching bundle_sha256
  AUTO: Auto-approve if confidence.score >= threshold AND no flags AND hitl_required=false
  SKIP: Bypass gate (still emits approval bound to bundle_sha256)

Stale Approval Prevention:
  - Approval file must reference current bundle_sha256
  - Rejects approvals bound to old/modified inputs
  - Template generation is deterministic

Determinism:
  - Template shape is stable (same IR → same template)
  - Approval decision is deterministic (given file + config)
  - Human approval is inherently non-deterministic (that's the point)
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any


# Assuming BlockedError is defined elsewhere or needs to be added
class BlockedError(Exception):
    pass


def run(context, link_config):
    """
    HITL gate with AUTO/BLOCKED/SKIP modes.
    
    Must enforce strict bundle_sha256 binding to prevent stale approvals.
    """
    # Extract runtime config (handle nested link.yaml structure)
    if "config" in link_config and isinstance(link_config["config"], dict):
        config = link_config["config"]
    else:
        config = link_config
    
    mode = config.get("mode", "BLOCKED")
    auto_threshold = config.get("auto_threshold", 0.7)
    require_no_flags = config.get("require_no_flags", True)
    
    # Load project IR
    project_root = Path(context["project_root"])
    artifact_store = context["artifact_store"]
    
    # Try loading Project Contract first (Meaning Gates v1)
    # Then fall back to Project IR (Legacy/Generic)
    contract_meta = artifact_store.get("dawn.project.contract")
    ir_meta = artifact_store.get("dawn.project.ir")
    
    if contract_meta:
        with open(contract_meta["path"]) as f:
            project_data = json.load(f)
            contract_sha256 = project_data.get("contract_sha256")
            bundle_sha256 = project_data.get("bundle_sha256")
            confidence = project_data.get("confidence", {})
    elif ir_meta:
        with open(ir_meta["path"]) as f:
            project_data = json.load(f)
            contract_sha256 = None
            bundle_sha256 = project_data.get("bundle_sha256")
            confidence = project_data.get("confidence", {})
    else:
        raise Exception("INPUT_MISSING: Neither dawn.project.contract nor dawn.project.ir found. Run spec.requirements or ingest.handoff first.")
    
    # DEBUG: Log decision values
    print(f"[DEBUG hitl.gate] mode={mode}, auto_threshold={auto_threshold}, require_no_flags={require_no_flags}")
    print(f"[DEBUG hitl.gate] confidence.overall={confidence.get('overall')}, confidence.flags={confidence.get('flags')}")
    print(f"[DEBUG hitl.gate] bundle_sha256={bundle_sha256}, contract_sha256={contract_sha256}")
    
    # Get sandbox
    sandbox = context["sandbox"]
    
    # 1. SKIP mode - auto-approve without checks
    if mode == "SKIP":
        return handle_skip_mode(sandbox, bundle_sha256, contract_sha256)
    
    # 2. AUTO mode - approve if confidence meets criteria
    if mode == "AUTO":
        overall = confidence.get("overall", 0)
        flags = confidence.get("flags", [])
        
        # Check AUTO criteria
        meets_threshold = overall >= auto_threshold
        meets_flags = not require_no_flags or len(flags) == 0
        
        print(f"[DEBUG AUTO] meets_threshold={meets_threshold} ({overall} >= {auto_threshold})")
        print(f"[DEBUG AUTO] meets_flags={meets_flags} (require_no_flags={require_no_flags}, flags={flags})")
        
        if meets_threshold and meets_flags:
            # AUTO approve!
            approval = {
                "schema_version": "1.0.0",
                "status": "approved",
                "mode": "AUTO",
                "bundle_sha256": bundle_sha256,
                "contract_sha256": contract_sha256,
                "notes": f"AUTO approved: confidence {overall}, flags {flags}"
            }
            sandbox.publish("dawn.hitl.approval", "approval.json", approval, "json")
            return {"status": "SUCCEEDED", "metrics": {"mode": "AUTO", "confidence": overall}}
        
        # AUTO criteria not met - fallthrough to BLOCKED
        print(f"[DEBUG AUTO] Criteria not met - falling through to BLOCKED")
    
    # 3. BLOCKED mode (default or fallthrough)
    return handle_blocked_mode(
        sandbox=sandbox,
        project_root=project_root,
        bundle_sha256=bundle_sha256,
        contract_sha256=contract_sha256,
        confidence=confidence,
        project_data=project_data
    )


def handle_skip_mode(sandbox, bundle_sha256: str, contract_sha256: str = None) -> Dict[str, Any]:
    """SKIP mode: bypass gate but still emit approval."""
    approval = {
        "schema_version": "1.0.0",
        "status": "skipped",
        "bundle_sha256": bundle_sha256,
        "contract_sha256": contract_sha256,
        "mode": "SKIP",
        "notes": "Gate bypassed via SKIP mode"
    }
    sandbox.publish("dawn.hitl.approval", "approval.json", approval, "json")
    
    return {
        "status": "SUCCEEDED",
        "metrics": {"gate_mode": "SKIP", "result": "skipped"}
    }


def handle_auto_mode(
    sandbox,
    project_root: Path,
    bundle_sha256: str,
    confidence_score: float,
    flags: list,
    hitl_required: bool,
    auto_threshold: float,
    require_no_flags: bool,
    project_ir: Dict
) -> Dict[str, Any]:
    """AUTO mode: auto-approve if conditions met, otherwise fall through to BLOCKED."""
    # Check if auto-approve conditions are met
    can_auto_approve = False
    deny_reason = None
    
    if confidence_score < auto_threshold:
        deny_reason = f"confidence {confidence_score} < threshold {auto_threshold}"
    elif require_no_flags and flags:
        deny_reason = f"flags present (require_no_flags=True): {flags}"
    elif hitl_required:
        deny_reason = "hitl_required=true in IR"
    else:
        can_auto_approve = True
    
    if can_auto_approve:
        # Auto-approve
        approval = {
            "schema_version": "1.0.0",
            "status": "approved",
            "bundle_sha256": bundle_sha256,
            "mode": "AUTO",
            "notes": f"Auto-approved: score={confidence_score}, threshold={auto_threshold}"
        }
        sandbox.publish("dawn.hitl.approval", "approval.json", approval, "json")
        
        return {
            "status": "SUCCEEDED",
            "metrics": {
                "gate_mode": "AUTO",
                "result": "approved",
                "confidence_score": confidence_score
            }
        }
    
    else:
        # Fall through to BLOCKED
        print(f"AUTO mode denied: {deny_reason}")
        print("Falling back to BLOCKED mode behavior")
        
        return handle_blocked_mode(
            artifact_store=artifact_store,
            project_root=project_root,
            bundle_sha256=bundle_sha256,
            project_ir=project_ir
        )


def handle_blocked_mode(
    sandbox,
    project_root: Path,
    bundle_sha256: str,
    contract_sha256: str,
    confidence: Dict,
    project_data: Dict
) -> Dict[str, Any]:
    """BLOCKED mode: require human approval file with matching bundle_sha256 and contract_sha256."""
    approval_file = project_root / "inputs" / "hitl_approval.json"
    
    # Load approval from template
    approval_path = project_root / "inputs" / "hitl_approval.json"
    
    if not approval_path.exists():
        # First-time block (no approval exists yet)
        # Generate template
        template = {
            "bundle_sha256": bundle_sha256,
            "contract_sha256": contract_sha256,
            "approved": False,
            "operator": "",
            "comment": "",
            "timestamp_utc": ""
        }
        
        approval_path.parent.mkdir(parents=True, exist_ok=True) # Ensure directory exists
        
        with open(approval_path, 'w') as f:
            json.dump(template, f, indent=2, sort_keys=True)
        
        # Write blocked status to artifact
        approval = {
            "schema_version": "1.0.0",
            "status": "blocked",
            "bundle_sha256": bundle_sha256,
            "contract_sha256": contract_sha256,
            "mode": "BLOCKED",
            "notes": "Awaiting human approval"
        }
        sandbox.publish("dawn.hitl.approval", "approval.json", approval, "json")
        
        raise BlockedError(
            f"BLOCKED: HITL approval required.\n\n"
            f"Confidence: {confidence.get('overall', 0)}\n"
            f"Flags: {', '.join(confidence.get('flags', []))}\n\n"
            f"Action Required:\n"
            f"  1. Review: {approval_path}\n"
            f"  2. Set 'approved': true (or false to reject)\n"
            f"  3. Add your name to 'operator'\n"
            f"  4. Optionally add 'comment'\n"
            f"  5. Re-run pipeline\n\n"
            f"Template created at: {approval_path}"
        )
    
    
    with open(approval_path) as f:
        approval_input = json.load(f)
    
    # STALE APPROVAL CHECK
    approval_bundle_sha = approval_input.get("bundle_sha256")
    approval_contract_sha = approval_input.get("contract_sha256")
    
    bundle_stale = approval_bundle_sha and approval_bundle_sha != bundle_sha256
    contract_stale = approval_contract_sha and approval_contract_sha != contract_sha256
    
    if bundle_stale or contract_stale:
        # Approval is stale
        reason = "stale_bundle" if bundle_stale else "stale_contract"
        blocked = {
            "schema_version": "1.0.0",
            "status": "blocked",
            "mode": "BLOCKED",
            "reason": reason,
            "bundle_sha256": bundle_sha256,
            "contract_sha256": contract_sha256,
            "notes": f"Inputs or Contract changed ({reason}); approval is stale. Please re-approve."
        }
        sandbox.publish("dawn.hitl.approval", "approval.json", blocked, "json")
        
        # Regenerate template bound to new state
        template = {
            "bundle_sha256": bundle_sha256,
            "contract_sha256": contract_sha256,
            "approved": False,
            "operator": "",
            "comment": "",
            "timestamp_utc": ""
        }
        with open(approval_path, 'w') as f:
            json.dump(template, f, indent=2, sort_keys=True)
        
        raise Exception(
            f"APPROVAL_STALE: {reason.upper()} mismatch. "
            f"Physical state or Meaning state has changed. Re-approve required.\n\n"
            f"Template regenerated at: {approval_path}"
        )
    
    approved = approval_input.get("approved", False)
    
    if not approved:
        # Rejection
        approval = {
            "schema_version": "1.0.0",
            "status": "rejected",
            "bundle_sha256": bundle_sha256,
            "mode": "BLOCKED",
            "notes": approval_input.get("comment", "")
        }
        sandbox.publish("dawn.hitl.approval", "approval.json", approval, "json")
        
        raise RejectedError(
            f"REJECTED: HITL approval denied.\n\n"
            f"Rejected by: {approval_input.get('operator', 'unknown')}\n"
            f"Comment: {approval_input.get('comment', 'none')}\n\n"
            f"To proceed:\n"
            f"  - Address issues and set 'approved': true\n"
            f"  - Or delete approval file to regenerate template"
        )
    
    # 5. Approved - emit approval artifact
    approval = {
        "schema_version": "1.0.0",
        "status": "approved",
        "bundle_sha256": bundle_sha256,
        "contract_sha256": contract_sha256,
        "mode": "BLOCKED",
        "notes": approval_input.get("comment", "")
    }
    sandbox.publish("dawn.hitl.approval", "approval.json", approval, "json")
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "gate_mode": "BLOCKED",
            "result": "approved",
            "operator": approval.get("operator", "unknown")
        }
    }


def create_approval_template(
    bundle_sha256: str,
    project_data: Dict,
    confidence: Dict
) -> Dict[str, Any]:
    """Create deterministic approval template."""
    payload = project_data.get("payload", {}) or project_data.get("ir", {}).get("payload", {})
    
    return {
        "schema_version": "1.0.0",
        "bundle_sha256": bundle_sha256,
        "approved": False,
        "operator": "",
        "comment": "",
        "_context": {
            "parser": project_data.get("parser", {}),
            "ir_type": project_data.get("ir", {}).get("type") or project_data.get("type"),
            "confidence_score": confidence.get("overall", 0),
            "flags": sorted(confidence.get("flags", [])),
            "summary": {
                "nodes": payload.get("nodes", 0),
                "groups": payload.get("groups", 0),
                "connections": payload.get("connections", 0)
            }
        },
        "_instructions": [
            "Set 'approved' to true or false",
            "Add your name to 'operator'",
            "Optionally add 'comment'",
            "DO NOT modify 'bundle_sha256' or 'contract_sha256' - it binds this approval to current inputs and intent"
        ]
    }


def load_artifact_json(artifact_index: Dict, artifact_id: str) -> Dict:
    """Load and parse JSON artifact."""
    artifact = artifact_index.get(artifact_id)
    if not artifact:
        raise FileNotFoundError(f"{artifact_id} not found in artifact index")
    
    artifact_path = Path(artifact["path"])
    if not artifact_path.exists():
        raise FileNotFoundError(f"{artifact_id} file not found: {artifact_path}")
    
    with open(artifact_path, 'r') as f:
        return json.load(f)


class BlockedError(Exception):
    """Raised when pipeline is blocked waiting for approval."""
    pass


class RejectedError(Exception):
    """Raised when HITL approval is rejected."""
    pass


class StaleApprovalError(Exception):
    """Raised when approval file references old bundle_sha256."""
    pass
