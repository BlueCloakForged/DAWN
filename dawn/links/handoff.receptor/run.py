"""Executes the handoff.receptor step in the DAWN pipeline."""
import json
from pathlib import Path

def run(context, config):
    """
    Handoff Receptor Link - Ingests external growth packages for surgery.
    """
    project_root = Path(context["project_root"])
    package_path = config.get("growth_package_path", "inputs/growth_package.json")
    
    full_path = project_root / package_path
    if not full_path.exists():
        raise FileNotFoundError(f"Growth package not found: {full_path}")
    
    with open(full_path, "r") as f:
        package_data = json.load(f)
    
    # Support loading code from external source_file (prevents JSON escaping issues)
    proposed_link = package_data.get("proposed_link", {})
    if "source_file" in proposed_link:
        source_path = project_root / proposed_link["source_file"]
        if source_path.exists():
            with open(source_path, "r") as f:
                proposed_link["run_py"] = f.read()
            print(f"Handoff: Loaded code from {proposed_link['source_file']}")
    
    # Register the transplant artifact
    sandbox = context["sandbox"]
    sandbox.publish(
        artifact="dawn.evolution.transplant",
        filename="transplant.json",
        obj=package_data,
        schema="json"
    )
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "intent": package_data.get("evolution_metadata", {}).get("intent"),
            "feature": package_data.get("evolution_metadata", {}).get("feature_name")
        }
    }
