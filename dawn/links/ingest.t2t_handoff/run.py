import os
import json
from datetime import datetime
from pathlib import Path
from dawn.integrations.t2t_adapter import run_t2t

def run(context, config):
    project_id = context["project_id"]
    project_root = context["project_root"]
    
    # DAWN Project Input Convention: projects/<project_id>/inputs/
    inputs_dir = os.path.join(project_root, "inputs")
    out_dir = os.path.join(project_root, "artifacts", "ingest.t2t_handoff")
    os.makedirs(out_dir, exist_ok=True)
    
    # Resolve input directory and verify content
    if not os.path.exists(inputs_dir) or not any(Path(inputs_dir).iterdir()):
        error_msg = f"Project input directory {inputs_dir} is missing or empty. Please drop source material into 'inputs/'."
        print(f"Error: {error_msg}")
        return {
            "status": "FAILED",
            "errors": {"type": "INPUT_ERROR", "message": error_msg}
        }
        
    print(f"Starting T2T handoff for project: {project_id}")
    print(f"Reading inputs from: {inputs_dir}")
    
    # Call T2T Adapter
    try:
        metadata = run_t2t(
            inputs_dir=inputs_dir,
            output_dir=out_dir,
            enable_vision=False,
            layout_mode="tiered",
            hitl_mode="off"
        )
    except Exception as e:
        print(f"T2T Adapter failed: {str(e)}")
        return {
            "status": "FAILED",
            "errors": {"type": "ADAPTER_ERROR", "message": str(e)}
        }
    
    # Build project_descriptor.json (Required output)
    source_bundle = []
    inputs_path = Path(inputs_dir)
    for f in inputs_path.iterdir():
        if f.is_file():
            # Calculate digest for audit ledger
            digest = context["artifact_store"].get_digest(f)
            source_bundle.append({
                "path": f"inputs/{f.name}",
                "sha256": digest
            })
            
    descriptor = {
        "project_id": project_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "source_bundle": source_bundle,
        "handoff": {
            "engine": "T2T",
            "engine_path": "/Users/vinsoncornejo/DAWN/T2T",
            "enable_vision": False,
            "layout_mode": "tiered",
            "hitl_mode": "off"
        },
        "artifacts": {
            "dawn.project.ir": {"path": "project_ir.json"},
            "dawn.project.export.primary": {"path": "export_primary.json", "optional": True},
            "dawn.project.export.workflow": {"path": "export_workflow.json", "optional": True}
        },
        "intent_summary": "", # To be populated if needed
        "confidence": metadata.get("confidence"),
        "flags": metadata.get("flags", []),
        "hitl_status": "pending"
    }
    
    descriptor_path = os.path.join(out_dir, "project_descriptor.json")
    with open(descriptor_path, "w") as f:
        json.dump(descriptor, f, indent=2)
        
    print(f"T2T handoff complete items found: {metadata.get('counts')}")
        
    return {
        "status": "SUCCEEDED",
        "metrics": metadata.get("counts", {})
    }
