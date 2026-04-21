"""Executes the thalamus.fuse_context step in the DAWN pipeline."""
import json
from pathlib import Path

def run(context, config):
    """
    THALAMUS Sensory Fusion Hub.
    Merges multimodal data into a single unified transaction object.
    """
    print("THALAMUS: Fusing context into Unified Event...")
    
    artifact_store = context["artifact_store"]
    ephemeral = context.get("ephemeral_input", {})
    
    # 1. Load Filter Status (Salience Score)
    filter_status = artifact_store.read_artifact("thalamus.salience_filter", "filter_status.json")
    salience_score = filter_status.get("salience", 0.0) if filter_status else 0.0
    
    # 2. Load LIGAND Modulation Snapshot
    pool_data = artifact_store.read_artifact("meta.bundle", "ligand.pool.snapshot.json")
    modulation_snapshot = pool_data.get("vector", {}) if pool_data else {}
    
    # 3. Gather Multimodal Signals (Media Digests from Ephemeral Input)
    media_digests = ephemeral.get("media_digests", {})
    primary_signal = media_digests.get("primary")
    secondary_signals = media_digests.get("secondary", [])
    
    # 4. Construct Unified Event
    unified_event = {
        "transaction_id": context.get("pipeline_run_id"),
        "meta_bundle_ref": context.get("ephemeral_input", {}).get("environment_hash"),
        "fused_context": {
            "primary_signal": primary_signal,
            "secondary_signals": secondary_signals,
            "modulation_snapshot": modulation_snapshot
        },
        "salience_score": salience_score,
        "timestamp": ephemeral.get("timestamp")
    }
    
    # 5. Publish to Ledger Context and File System
    context["sandbox"].publish("thalamus.unified_event", "unified_event.json", unified_event)
    
    # Phase 2 audit requirement: Log to DAWN Ledger
    context["ledger"].log_event(
        context.get("project_id"),
        context.get("pipeline_id"),
        "thalamus.fuse_context",
        context.get("pipeline_run_id"),
        "ground_truth_established",
        "SUCCEEDED",
        outputs={"unified_event": unified_event}
    )
    
    print(f"THALAMUS: Unified Event established. ID: {unified_event['transaction_id']}")
    return {"status": "SUCCEEDED", "metrics": {"salience": salience_score}}
