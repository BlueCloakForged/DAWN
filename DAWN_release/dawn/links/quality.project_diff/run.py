import json
import hashlib
import fnmatch
from pathlib import Path
from typing import List, Dict, Any

def run(context, config):
    """
    quality.project_diff - Computes diff against original bundle.
    """
    project_root = Path(context["project_root"])
    inputs_dir = project_root / "inputs"
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    
    # 1. Load Original Bundle
    bundle_meta = artifact_store.get("dawn.project.bundle")
    if not bundle_meta:
        raise Exception("INPUT_MISSING: dawn.project.bundle required for diff computation.")
    
    with open(bundle_meta["path"]) as f:
        original_manifest = json.load(f)
    
    original_files = {f["path"]: f["sha256"] for f in original_manifest.get("files", [])}
    
    # 2. Scan Current State (Reusable logic from ingest.project_bundle)
    # Excludes control-plane files
    excludes = [
        "hitl_*.json", ".dawn_*", ".DS_Store", "Thumbs.db", "._*", "*.tmp", "*.swp"
    ]
    
    current_files = {}
    for file_path in sorted(inputs_dir.rglob("*")):
        if not file_path.is_file():
            continue
        rel_path = file_path.relative_to(inputs_dir).as_posix()
        
        should_exclude = False
        for pattern in excludes:
            if fnmatch.fnmatch(file_path.name, pattern) or fnmatch.fnmatch(rel_path, pattern):
                should_exclude = True
                break
        if should_exclude: continue
        
        file_bytes = file_path.read_bytes()
        file_sha256 = hashlib.sha256(file_bytes).hexdigest()
        current_files[rel_path] = file_sha256
        
    # 3. Compute Diff
    added = []
    modified = []
    deleted = []
    unchanged = []
    
    for path, sha in current_files.items():
        if path not in original_files:
            added.append(path)
        elif original_files[path] != sha:
            modified.append(path)
        else:
            unchanged.append(path)
            
    for path in original_files:
        if path not in current_files:
            deleted.append(path)
            
    diff_report = {
        "summary": {
            "added": len(added),
            "modified": len(modified),
            "deleted": len(deleted),
            "unchanged": len(unchanged)
        },
        "details": {
            "added": added,
            "modified": modified,
            "deleted": deleted
        },
        "base_bundle_sha256": original_manifest["bundle_sha256"]
    }
    
    # 4. Optional: Contract Compliance Check (Decision Rights)
    contract_meta = artifact_store.get("dawn.project.contract")
    if contract_meta:
        with open(contract_meta["path"]) as f:
            contract = json.load(f)
        allowed_paths = contract.get("decision_rights", {}).get("allowed_paths", [])
        
        violations = []
        for path in added + modified + deleted:
            # Simple prefix check for compliance
            if not any(path.startswith(p.replace("**", "").replace("*", "")) for p in allowed_paths):
                violations.append(path)
        
        diff_report["compliance"] = {
            "status": "PASS" if not violations else "FAIL",
            "unauthorized_changes": violations
        }
    
    # 5. Publish
    sandbox.publish(
        artifact="dawn.project.diff",
        filename="project_diff.json",
        obj=diff_report,
        schema="json"
    )
    
    return {
        "status": "SUCCEEDED",
        "metrics": diff_report["summary"]
    }
