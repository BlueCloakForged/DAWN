import os
import json
import shutil
import subprocess
from pathlib import Path

# Calculate paths relative to this script's location
SCRIPT_DIR = Path(__file__).resolve().parent
DAWN_ROOT = SCRIPT_DIR.parent
PROJECTS_DIR = DAWN_ROOT / "projects"
PIPELINE = str(DAWN_ROOT / "dawn" / "pipelines" / "golden" / "meaning_gate_v1.yaml")

def run_verify():
    project_id = "test_meaning_gates"
    project_root = PROJECTS_DIR / project_id
    
    # 1. Cleanup
    if project_root.exists():
        shutil.rmtree(project_root)
    
    # 2. Setup Inputs
    inputs_dir = project_root / "inputs"
    inputs_dir.mkdir(parents=True)
    
    # source file
    src_dir = project_root / "src"
    src_dir.mkdir(parents=True)
    with open(src_dir / "app.py", "w") as f:
        f.write('print("Hello Meaning Gates")\n')
    
    # Contract Proposal
    contract = {
        "intent": {
            "summary": "Demo project",
            "goals": ["Verify Meaning Gates"],
            "constraints": [{"type": "security", "text": "No external requests"}]
        },
        "decision_rights": {
            "allowed_paths": ["src/**", "tests/**"],
            "forbidden_paths": ["auth/**"]
        },
        "definition_of_done": {
            "tests": {"must_pass": True},
            "invariants": [{"id": "INV-001", "statement": "No forbidden writes"}]
        },
        "acceptance": {
            "scenarios": ["SCN-001"]
        }
    }
    with open(inputs_dir / "contract.json", "w") as f:
        json.dump(contract, f, indent=2)

    # 3. Run Pipeline (Expect Blocked at HITL)
    print("--- Running Pipeline (Initial Intake) ---")
    result = subprocess.run([
        "python3", "-m", "dawn.runtime.main",
        "--project", project_id,
        "--pipeline", PIPELINE
    ], capture_output=True, text=True)
    
    if "BLOCKED" not in result.stderr and "BLOCKED" not in result.stdout:
        print("FAIL: Expected pipeline to block at HITL")
        print("--- STDOUT ---")
        print(result.stdout)
        print("--- STDERR ---")
        print(result.stderr)
        return False
        
    print("SUCCESS: Pipeline blocked as expected.")
    
    # 4. Approve Contract
    # Load template
    approval_template_path = inputs_dir / "hitl_approval.json"
    if not approval_template_path.exists():
        print("FAIL: hitl_approval.json not generated")
        return False
        
    with open(approval_template_path) as f:
        approval = json.load(f)
        
    approval["approved"] = True
    approval["operator"] = "Verifier Agent"
    
    with open(approval_template_path, "w") as f:
        json.dump(approval, f, indent=2)
        
    print(f"DEBUG: Approved bundle={approval['bundle_sha256'][:8]}, contract={approval['contract_sha256'][:8]}")

    # 5. Run Pipeline Again (Should Succeed)
    print("--- Running Pipeline (Post-Approval) ---")
    result = subprocess.run([
        "python3", "-m", "dawn.runtime.main",
        "--project", project_id,
        "--pipeline", PIPELINE
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"FAIL: Pipeline failed post-approval: {result.stderr}")
        return False
        
    print("SUCCESS: Pipeline completed.")

    # 6. Verify Audit Artifacts
    audit_path = project_root / "artifacts" / "quality.release_verifier" / "release_audit.json"
    receipt_path = project_root / "artifacts" / "quality.release_verifier" / "trust_receipt.md"
    diff_path = project_root / "artifacts" / "quality.project_diff" / "project_diff.json"
    
    if not audit_path.exists():
        print("FAIL: release_audit.json not found")
        return False
    if not receipt_path.exists():
        print("FAIL: trust_receipt.md not found")
        return False
    if not diff_path.exists():
        print("FAIL: project_diff.json not found")
        return False
        
    with open(audit_path) as f:
        audit = json.load(f)
    with open(diff_path) as f:
        diff = json.load(f)
        
    print(f"Audit Status: {audit['status']}")
    print(f"Diff Summary: {diff['summary']}")
    
    for check, status in audit["checks"].items():
        print(f"  {check}: {status}")
        
    if audit["status"] != "PASS":
        print("FAIL: Release audit failed")
        return False
        
    print("🎉 ALL MEANING GATES (PHASE 2) VERIFIED!")
    return True

if __name__ == "__main__":
    if run_verify():
        exit(0)
    else:
        exit(1)
