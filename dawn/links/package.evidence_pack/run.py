import os
import zipfile
import shutil
from pathlib import Path

def run(context, config):
    project_root = Path(context["project_root"])
    
    # Files to include
    targets = [
        ("ledger/events.jsonl", "ledger/events.jsonl"),
        ("artifact_index.json", "artifact_index.json"),
        ("pipeline.yaml", "pipeline.yaml")
    ]
    
    output_zip = Path(context["sandbox"].sandbox_root) / "evidence_pack.zip"
    
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add core metadata
        for src_rel, arc_name in targets:
            src_path = project_root / src_rel
            if src_path.exists():
                zipf.write(src_path, arc_name)
        
        # Add all link artifacts
        artifacts_base = project_root / "artifacts"
        if artifacts_base.exists():
            for root, dirs, files in os.walk(artifacts_base):
                for file in files:
                    full_path = Path(root) / file
                    # Avoid adding the evidence pack itself if it's already there (it shouldn't be yet)
                    if "package.evidence_pack" in str(full_path):
                        continue
                    arc_name = os.path.join("artifacts", full_path.relative_to(artifacts_base))
                    zipf.write(full_path, arc_name)

    return {
        "status": "SUCCEEDED",
        "metrics": {
            "evidence_size_kb": os.path.getsize(output_zip) // 1024
        }
    }
