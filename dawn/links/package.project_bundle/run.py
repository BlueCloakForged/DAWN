import os
import json
import zipfile
from datetime import datetime
from pathlib import Path

def run(context, config):
    project_id = context["project_id"]
    artifacts = context["artifact_index"]
    out_dir = os.path.join(context["project_root"], "artifacts", "package.project_bundle")
    os.makedirs(out_dir, exist_ok=True)
    
    # Files to include in the bundle
    # Required
    include_map = {
        "dawn.project.descriptor": "project_descriptor.json",
        "dawn.project.ir": "project_ir.json",
        "validate.project_handoff.report": "handoff_validation_report.json"
    }
    # Optional
    if "dawn.project.export.primary" in artifacts:
        include_map["dawn.project.export.primary"] = "export_primary.json"
    if "dawn.project.export.workflow" in artifacts:
        include_map["dawn.project.export.workflow"] = "export_workflow.json"
        
    # Build Manifest
    manifest = {
        "project_id": project_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "files": [],
        "validation_summary": {},
        "export_presence": {}
    }
    
    # Get validation summary if available
    val_report_entry = artifacts.get("validate.project_handoff.report")
    if val_report_entry:
        try:
            with open(val_report_entry["path"], "r") as f:
                val_data = json.load(f)
                manifest["validation_summary"] = {
                    "pass": val_data.get("pass"),
                    "errors": len(val_data.get("errors", [])),
                    "warnings": len(val_data.get("warnings", []))
                }
        except:
            pass
            
    # Assemble ZIP and Manifest Entries
    zip_path = os.path.join(out_dir, "project_bundle.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for art_id, bundle_name in include_map.items():
            entry = artifacts.get(art_id)
            if entry and os.path.exists(entry["path"]):
                # Add to ZIP
                zipf.write(entry["path"], bundle_name)
                # Add to Manifest
                manifest["files"].append({
                    "artifactId": art_id,
                    "filename": bundle_name,
                    "sha256": entry.get("digest")
                })
                # Metadata exports
                if art_id.startswith("dawn.project.export"):
                    target = art_id.split(".")[-1]
                    manifest["export_presence"][target] = True

    # Save Manifest
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
        
    # Add manifest itself to the zip? 
    # Usually manifest is inside. Let's append it.
    with zipfile.ZipFile(zip_path, 'a', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(manifest_path, "manifest.json")
        
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "bundled_files": len(manifest["files"]) + 1, # +1 for manifest
            "zip_size_bytes": os.path.getsize(zip_path)
        }
    }
