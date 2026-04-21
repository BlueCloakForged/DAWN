"""Executes the thalamus.switchboard step in the DAWN pipeline."""
import json
from pathlib import Path

def run(context, config):
    """
    THALAMUS Switchboard.
    Intent-to-Category mapper.
    """
    print("THALAMUS: Determining routing path...")
    
    artifact_store = context["artifact_store"]
    ephemeral = context.get("ephemeral_input", {})
    
    # 1. Load Unified Event
    unified_event = artifact_store.read_artifact("thalamus.fuse_context", "unified_event.json")
    if not unified_event:
        print("THALAMUS: Warning - Unified Event missing. Routing to 'default'.")
        category = "default"
        signal_type = "UNKNOWN"
    else:
        # Determine signal type from fused context
        fused = unified_event.get("fused_context", {})
        primary = fused.get("primary_signal")
        
        # Fallback to origin_source if primary_signal is missing (for testing)
        if not primary:
            primary = ephemeral.get("origin_source", "unknown")
            
        # Simple intent mapping logic
        if "calc" in primary.lower() or "math" in primary.lower() or primary == "user_command":
            signal_type = "CALCULATION"
            category = "math"
        elif "env" in primary.lower() or "change" in primary.lower():
            signal_type = "ENVIRONMENT_CHANGE"
            category = "evolution"
        elif "command" in primary.lower() or "do" in primary.lower():
            signal_type = "COMMAND"
            category = "action"
        else:
            signal_type = "GENERAL"
            category = "standard"
            
    # 2. Publish Routing Decision
    routing_decision = {
        "status": "ROUTED",
        "signal_type": signal_type,
        "selected_category": category,
        "timestamp": unified_event.get("timestamp") if unified_event else None
    }
    
    context["sandbox"].publish("thalamus.routing_decision", "routing_decision.json", routing_decision)
    
    print(f"THALAMUS: Routing to category '{category}' based on intent '{signal_type}'.")
    return {"status": "SUCCEEDED", "metrics": {"category": category}}
