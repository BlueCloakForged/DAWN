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

def run_verify_stale():
    project_id = "test_meaning_gates_stale"
    project_root = PROJECTS_DIR / project_id
    
    # 1. Cleanup
    if project_root.exists():
        shutil.rmtree(project_root)
    
    # 2. Setup Inputs
    inputs_dir = project_root / "inputs"
    inputs_dir.mkdir(parents=True)
    
    src_dir = project_root / "src"
    src_dir.mkdir(parents=True)
    with open(src_dir / "app.py", "w") as f:
        f.write('print("Hello Stale Check")\n')
    
    contract = {
        "intent": {"summary": "Stale test", "goals": ["Goal 1"]},
        "decision_rights": {"allowed_paths": ["src/**"]},
        "definition_of_done": {"tests": {"must_pass": True}}
    }
    with open(inputs_dir / "contract.json", "w") as f:
        json.dump(contract, f, indent=2)

    # 3. Initial Run (Blocks)
    subprocess.run(["python3", "-m", "dawn.runtime.main", "--project", project_id, "--pipeline", PIPELINE], capture_output=True)
    
    # 4. Approve
    with open(inputs_dir / "hitl_approval.json") as f:
        approval = json.load(f)
    approval["approved"] = True
    approval["operator"] = "Verifier"
    with open(inputs_dir / "hitl_approval.json", "w") as f:
        json.dump(approval, f, indent=2)
        
    print(f"DEBUG: Initial approval bound to contract {approval['contract_sha256'][:8]}")

    # 5. Modify Contract SLIGHTLY (add a goal)
    contract["intent"]["goals"].append("Goal 2")
    with open(inputs_dir / "contract.json", "w") as f:
        json.dump(contract, f, indent=2)
    print("DEBUG: Contract modified after approval.")

    # 6. Run Again (Should BLOCK again with stale_contract)
    print("--- Running Pipeline (Post-Modification) ---")
    result = subprocess.run([
        "python3", "-m", "dawn.runtime.main",
        "--project", project_id,
        "--pipeline", PIPELINE
    ], capture_output=True, text=True)
    
    if "STALE_BUNDLE mismatch" not in result.stdout and "STALE_CONTRACT mismatch" not in result.stdout:
        print("FAIL: Expected STALE_BUNDLE or STALE_CONTRACT mismatch error")
        print(result.stdout)
        print(result.stderr)
        return False
        
    print("SUCCESS: Detected stale contract and blocked pipeline.")
    
    # 7. Check that new template exists and has NEW contract_sha
    with open(inputs_dir / "hitl_approval.json") as f:
        new_approval = json.load(f)
    
    if new_approval["contract_sha256"] == approval["contract_sha256"]:
        print("FAIL: hitl_approval.json not updated with new contract SHA")
        return False
        
    print(f"DEBUG: New template bound to contract {new_approval['contract_sha256'][:8]}")
    print("🎉 STALE CONTRACT DETECTION VERIFIED!")
    return True

if __name__ == "__main__":
    if run_verify_stale():
        exit(0)
    else:
        exit(1)
