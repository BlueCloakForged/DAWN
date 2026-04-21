"""Executes the thalamus.salience_filter step in the DAWN pipeline."""
import json
from pathlib import Path

def run(context, config):
    """
    THALAMUS Salience Filter.
    Calculation: Salience = (Delta * Source_Weight) / (1.0 + Focus_Modulator).
    """
    print("THALAMUS: Running Salience Filter...")
    
    artifact_store = context["artifact_store"]
    
    # 1. Load LIGAND Pool Snapshot
    pool_data = artifact_store.read_artifact("meta.bundle", "ligand.pool.snapshot.json")
    if not pool_data:
        print("THALAMUS: Missing ligand.pool.snapshot.json. Proceeding with default focus.")
        focus_modulator = 0.0
    else:
        # focus_modulator corresponds to 'alpha' (Focus)
        focus_modulator = pool_data.get("vector", {}).get("alpha", 0.0)
    
    # 2. Extract Metadata from ephemeral_input (The Meta-Bundle Context)
    ephemeral = context.get("ephemeral_input", {})
    delta = ephemeral.get("delta", 1.0) # Delta from last state, default to 1.0
    source = ephemeral.get("origin_source", "system")
    
    # 3. Define Source Weights (Dynamic mapping)
    source_weights = {
        "user_command": 2.0,
        "environment_critical": 1.5,
        "system": 1.0,
        "background_noise": 0.1
    }
    weight = source_weights.get(source, 1.0)
    
    # 4. Calculate Salience
    salience = (delta * weight) / (1.0 + focus_modulator)
    
    # 5. Determine Threshold (Can be fixed or dynamic based on modulation)
    # If alpha is high, threshold requirement increases
    base_threshold = config.get("config", {}).get("threshold", 0.5)
    
    print(f"THALAMUS: Salience={salience:.3f} (Delta={delta}, Weight={weight}, Focus={focus_modulator})")
    print(f"THALAMUS: Threshold={base_threshold}")
    
    if salience < base_threshold:
        print("THALAMUS: Salience below threshold. Status: FILTERED_AS_NOISE.")
        context["sandbox"].publish("thalamus.filter_status", "filter_status.json", {
            "status": "FILTERED_AS_NOISE",
            "salience": salience,
            "threshold": base_threshold,
            "timestamp": ephemeral.get("timestamp")
        })
        return {"status": "SUCCEEDED", "metrics": {"salience": salience, "decision": "FILTERED"}}
    else:
        print("THALAMUS: Salience above threshold. Status: PROCEED.")
        context["sandbox"].publish("thalamus.filter_status", "filter_status.json", {
            "status": "PROCEED",
            "salience": salience,
            "threshold": base_threshold,
            "timestamp": ephemeral.get("timestamp")
        })
        return {"status": "SUCCEEDED", "metrics": {"salience": salience, "decision": "PROCEED"}}
