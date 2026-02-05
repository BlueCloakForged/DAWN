import json
from pathlib import Path

def run(context, config):
    project_root = Path(context["project_root"])
    src_dir = project_root / "src"
    
    # 1. Load the approved patchset
    artifacts = context["artifact_index"]
    patchset_path = Path(artifacts["dawn.patchset"]["path"])
    
    with open(patchset_path, "r") as f:
        patchset_data = json.load(f)
        
    # 2. Apply patches
    applied_files = []
    for rel_path, patch_info in patchset_data.items():
        file_path = src_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, "w") as f:
            f.write(patch_info["content"])
            
        applied_files.append({
            "path": rel_path,
            "sha256": patch_info["sha256"]
        })
        
    context["sandbox"].write_json("applied.json", applied_files)
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "applied_count": len(applied_files)
        }
    }
