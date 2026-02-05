import os
import json
from pathlib import Path

def run(context, config):
    project_root = context["project_root"]
    link_id = "scaffold.project"
    
    out_dir = os.path.join(project_root, "artifacts", link_id)
    os.makedirs(out_dir, exist_ok=True)
    
    # Define scaffold dirs
    dirs = ["src", "docs", "tests", "data", "config"]
    created = []
    
    for d in dirs:
        d_path = os.path.join(project_root, d)
        if not os.path.exists(d_path):
            os.makedirs(d_path, exist_ok=True)
            created.append(d)
            
    manifest = {
        "scaffold_version": "1.0",
        "directories": dirs,
        "created_this_run": created
    }
    
    manifest_path = os.path.join(out_dir, "scaffold_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
        
    print(f"Project scaffold created: {dirs}")
    
    return {
        "status": "SUCCEEDED",
        "metrics": {"directories_created": len(created)}
    }
