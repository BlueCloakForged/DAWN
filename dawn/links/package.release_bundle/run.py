import os
import zipfile
import json
import hashlib
from pathlib import Path

def run(context, config):
    project_root = Path(context["project_root"])
    src_dir = project_root / "src"
    
    # 1. Resolve required artifacts
    artifacts = context["artifact_index"]
    evidence_pack = artifacts["dawn.evidence.pack"]["path"]
    spec_api = artifacts["dawn.spec.api"]["path"]
    spec_reqs = artifacts["dawn.spec.srs"]["path"]
    
    output_zip = Path(context["sandbox"].sandbox_root) / "release_bundle.zip"
    
    manifest = {
        "project_id": context["project_id"],
        "pipeline_id": context["pipeline_id"],
        "artifacts": {}
    }
    
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add src/ snapshot
        if src_dir.exists():
            for root, dirs, files in os.walk(src_dir):
                for file in files:
                    full_path = Path(root) / file
                    arc_name = os.path.join("src", full_path.relative_to(src_dir))
                    zipf.write(full_path, arc_name)
                    
        # Add Evidence Pack
        zipf.write(evidence_pack, "evidence_pack.zip")
        manifest["artifacts"]["evidence_pack"] = {
            "path": "evidence_pack.zip",
            "digest": artifacts["dawn.evidence.pack"]["digest"]
        }
        
        # Add Specs
        zipf.write(spec_api, "api_contracts.json")
        manifest["artifacts"]["api_contracts"] = {
            "path": "api_contracts.json",
            "digest": artifacts["dawn.spec.api"]["digest"]
        }
        
        zipf.write(spec_reqs, "srs.md")
        manifest["artifacts"]["requirements"] = {
            "path": "srs.md",
            "digest": artifacts["dawn.spec.srs"]["digest"]
        }
        
        # Build integrity manifest
        manifest_json = json.dumps(manifest, indent=2)
        zipf.writestr("release_manifest.json", manifest_json)
        
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "bundle_size_kb": os.path.getsize(output_zip) // 1024
        }
    }
