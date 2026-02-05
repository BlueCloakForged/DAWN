import json
import time
from pathlib import Path
from typing import Dict, Any

def run(context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Aggregate forensic signals into a DPO (Direct Preference Optimization) training artifact.
    """
    project_id = context["project_id"]
    project_root = Path(context["project_root"])
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    
    # 1. Collect Signals
    # Healing metrics (convergence trend)
    healing_art = artifact_store.get("dawn.healing.metrics")
    healing_data = {}
    if healing_art:
        with open(healing_art["path"]) as f:
            healing_data = json.load(f)
            
    # Judge score
    judge_art = artifact_store.get("dawn.judge.score")
    judge_data = {}
    if judge_art:
        with open(judge_art["path"]) as f:
            judge_data = json.load(f)
            
    # Project bundle (source code)
    bundle_art = artifact_store.get("dawn.project.bundle")
    bundle_data = {}
    if bundle_art:
        with open(bundle_art["path"]) as f:
            bundle_data = json.load(f)
            
    # 2. Format DPO Signal
    # A DPO signal typically consists of a prompt, a 'chosen' (winner), and a 'rejected' (loser).
    # In our evolutionary context:
    # - Chosen: The final healed code (if successful and high judge score).
    # - Rejected: The initial broken code (if healing improved it significantly).
    
    convergence = healing_data.get("total_convergence_trend", [])
    has_improvement = any(c > 0 for c in convergence)
    
    dpo_signal = {
        "project_id": project_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prompt": "Fix the following Python code according to the provided errors.",
        "chosen": None,
        "rejected": None,
        "metrics": {
            "judge_score": judge_data.get("score"),
            "convergence": convergence,
            "total_cycles": len(healing_data.get("cycles", []))
        }
    }
    
    # Attempt to extract chosen/rejected code pairs
    if has_improvement and judge_data.get("score", 0) > 0.7:
        # TODO: Implement actual diff/file extraction for DPO JSON
        # For now, we flag it as a valid training sample
        dpo_signal["status"] = "VALID_TRAINING_SAMPLE"
        dpo_signal["chosen_reason"] = "Healed code passed judge evaluation"
    else:
        dpo_signal["status"] = "FILTERED_OUT"
        dpo_signal["reason"] = "Low judge score or no convergence"

    # 3. Publish results
    sandbox.write_json("dpo_signal.json", dpo_signal)
    
    # Register artifact
    artifact_store.register(
        artifact_id="dawn.training.dpo_signal",
        abs_path=str((project_root / "artifacts" / "package.training_data" / "dpo_signal.json").absolute()),
        schema=None,
        producer_link_id="package.training_data"
    )
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "training_sample_valid": dpo_signal["status"] == "VALID_TRAINING_SAMPLE",
            "judge_score": judge_data.get("score")
        }
    }
