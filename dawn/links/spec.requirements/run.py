import json
import hashlib
from pathlib import Path
from typing import Dict, Any, List

def run(context, config):
    """
    spec.requirements - The "Meaning Gate" Intake Link
    
    Converts inputs/contract.json (or requirements.md) into dawn.project.contract.
    Enforces schema validation, normalizing list orders, and computing contract_sha256.
    """
    project_root = Path(context["project_root"])
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    
    # 1. Get Bundle SHA256 (for binding)
    bundle_meta = artifact_store.get("dawn.project.bundle")
    if not bundle_meta:
        raise Exception("INPUT_MISSING: dawn.project.bundle required for contract binding.")
    
    with open(bundle_meta["path"]) as f:
        bundle_manifest = json.load(f)
    bundle_sha256 = bundle_manifest["bundle_sha256"]
    
    # 2. Load Intake Contract
    contract_input_path = project_root / "inputs" / "contract.json"
    raw_input = {}
    
    if contract_input_path.exists():
        with open(contract_input_path) as f:
            raw_input = json.load(f)
    else:
        # Fallback/Template mode if no contract.json exists
        raw_input = generate_template(bundle_sha256)
        print(f"[WARN] No contract.json found in inputs. Generated template.")

    # 3. Normalize and Validate
    contract, confidence = normalize_contract(raw_input, bundle_sha256)
    
    # 4. Compute Contract SHA256
    # Strip volatile fields or metadata before hashing
    hashable_contract = contract.copy()
    hashable_contract.pop("provenance", None)
    hashable_contract.pop("confidence", None)
    
    contract_json = json.dumps(hashable_contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    contract_sha256 = hashlib.sha256(contract_json.encode("utf-8")).hexdigest()
    
    # Add metadata back
    contract["contract_sha256"] = contract_sha256
    contract["provenance"] = {
        "producer": "spec.requirements",
        "inputs": ["dawn.project.bundle", "inputs/contract.json"]
    }
    contract["confidence"] = confidence
    
    # 5. Publish Artifact
    sandbox.publish(
        artifact="dawn.project.contract",
        filename="contract.json",
        obj=contract,
        schema="json"
    )
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "bundle_sha256": bundle_sha256,
            "contract_sha256": contract_sha256,
            "confidence_overall": confidence["overall"],
            "hitl_required": confidence["hitl_required"]
        }
    }

def normalize_contract(raw: Dict, bundle_sha256: str) -> tuple[Dict, Dict]:
    """Normalize and validate the contract schema."""
    # Base structure
    contract = {
        "contract_version": "1.0",
        "bundle_sha256": bundle_sha256,
        "intent": raw.get("intent", {}),
        "decision_rights": raw.get("decision_rights", {}),
        "definition_of_done": raw.get("definition_of_done", {}),
        "acceptance": raw.get("acceptance", {}),
    }
    
    # Normalize Intent
    intent = contract["intent"]
    intent["goals"] = sorted(intent.get("goals", []))
    intent["non_goals"] = sorted(intent.get("non_goals", []))
    # Constraints normalized by sorting by text if list of dicts
    constraints = intent.get("constraints", [])
    if isinstance(constraints, list):
        intent["constraints"] = sorted(constraints, key=lambda x: str(x))
    
    # Normalize Decision Rights
    dr = contract["decision_rights"]
    dr["allowed_paths"] = sorted(dr.get("allowed_paths", []))
    dr["forbidden_paths"] = sorted(dr.get("forbidden_paths", []))
    dr["allowed_change_types"] = sorted(dr.get("allowed_change_types", []))
    dr["forbidden_change_types"] = sorted(dr.get("forbidden_change_types", []))
    
    # Normalize DoD
    dod = contract["definition_of_done"]
    dod["deliverables"] = sorted(dod.get("deliverables", []))
    invariants = dod.get("invariants", [])
    if isinstance(invariants, list):
        dod["invariants"] = sorted(invariants, key=lambda x: str(x))
    
    # Normalize Acceptance
    acceptance = contract["acceptance"]
    scenarios = acceptance.get("scenarios", [])
    if isinstance(scenarios, list):
        acceptance["scenarios"] = sorted(scenarios, key=lambda x: str(x))
    
    # Validation / Confidence Logic
    flags = []
    if not intent.get("goals"): flags.append("no_goals_defined")
    if not dr.get("allowed_paths"): flags.append("no_allowed_paths_defined")
    if not dod.get("invariants") and not dod.get("tests"): flags.append("no_verification_checks_defined")
    
    score = 1.0 - (len(flags) * 0.3)
    hitl_required = len(flags) > 0 or score < 0.7
    
    confidence = {
        "overall": max(0.0, score),
        "flags": flags,
        "hitl_required": hitl_required
    }
    
    return contract, confidence

def generate_template(bundle_sha256: str) -> Dict:
    """Generate a minimal contract template if none exists."""
    return {
        "bundle_sha256": bundle_sha256,
        "intent": {
            "summary": "Project implementation",
            "goals": ["Implement requested feature"],
            "non_goals": [],
            "constraints": []
        },
        "decision_rights": {
            "allowed_paths": ["src/**", "tests/**"],
            "forbidden_paths": []
        },
        "definition_of_done": {
            "tests": {"must_pass": True},
            "invariants": [],
            "deliverables": ["patchset"]
        }
    }
