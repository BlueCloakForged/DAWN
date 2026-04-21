"""Executes the ligand.synapse_threshold step in the DAWN pipeline."""
import json
from pathlib import Path

def run(context, config):
    """
    Weighted Summation Link (The Soma Pattern).
    Agnostic Logic: Sums numeric fields from source artifacts.
    """
    print("LIGAND: Running Synapse Threshold (Summation)...")
    
    # Config parameters
    # source_artifacts: List of artifact names or IDs
    # target_field: The numeric field to sum (defaults to 'value' or 'score')
    # weights: Dict of artifact_id -> multiplier
    # threshold: The value required to fire
    
    # LIGAND: Extract params from link_config["config"] if present, else top-level
    link_params = config.get("config", config)
    
    source_artifacts = link_params.get("source_artifacts", [])
    target_field = link_params.get("target_field", "score")
    weights = link_params.get("weights", {})
    threshold = link_params.get("threshold", 1.0)
    
    total_potential = 0.0
    artifact_store = context["artifact_store"]
    
    for art_id in source_artifacts:
        art_meta = artifact_store.get(art_id)
        if not art_meta:
            print(f"LIGAND: Source artifact {art_id} not found.")
            continue
            
        path = Path(art_meta["path"])
        if not path.exists():
            continue
            
        try:
            with open(path, "r") as f:
                data = json.load(f)
            
            val = data.get(target_field, 0.0)
            weight = weights.get(art_id, 1.0)
            
            potential = val * weight
            total_potential += potential
            print(f"LIGAND: Added {potential:.3f} from {art_id} (val={val}, weight={weight})")
        except Exception as e:
            print(f"LIGAND: Error reading {art_id}: {e}")

    print(f"LIGAND: Total Potential: {total_potential:.3f} / Threshold: {threshold:.3f}")
    
    if total_potential >= threshold:
        print("LIGAND: Threshold met. Firing GATE_OPEN.")
        context["sandbox"].publish("ligand.gate_open", "gate_status.json", {
            "status": "OPEN",
            "potential": total_potential,
            "threshold": threshold,
            "timestamp": context["ephemeral_input"]["timestamp"]
        })
        return {"status": "SUCCEEDED"}
    else:
        print("LIGAND: Threshold not met. Gating.")
        return {"status": "SUCCEEDED", "metrics": {"fire_status": "GATED", "potential": total_potential}}
