import os
import hashlib
from pathlib import Path

def run(context, config):
    project_root = Path(context["project_root"])
    src_dir = project_root / "src"
    
    diff_report = []
    
    if src_dir.exists():
        for root, dirs, files in os.walk(src_dir):
            for file in files:
                full_path = Path(root) / file
                rel_path = str(full_path.relative_to(project_root))
                
                with open(full_path, "rb") as f:
                    content = f.read()
                    digest = hashlib.sha256(content).hexdigest()
                    
                diff_report.append({
                    "path": rel_path,
                    "sha256": digest
                })
                
    context["sandbox"].write_json("src_diff.json", diff_report)
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "source_file_count": len(diff_report)
        }
    }
