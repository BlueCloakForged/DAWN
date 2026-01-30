import os
import json
from pathlib import Path

def run(context, config):
    project_id = context["project_id"]
    artifacts = context["artifact_index"]
    out_dir = os.path.join(context["project_root"], "artifacts", "validate.project_handoff")
    os.makedirs(out_dir, exist_ok=True)
    
    report = {
        "pass": True,
        "checks_run": [],
        "warnings": [],
        "errors": [],
        "counts": {},
        "exports_validated": []
    }
    
    # 1. Validate Descriptor
    descriptor_entry = artifacts.get("dawn.project.descriptor")
    if not descriptor_entry:
        report["pass"] = False
        report["errors"].append("Missing required artifact: dawn.project.descriptor")
    else:
        try:
            with open(descriptor_entry["path"], "r") as f:
                desc = json.load(f)
                required_fields = ["project_id", "created_at", "source_bundle", "handoff"]
                missing = [f for f in required_fields if f not in desc]
                if missing:
                    report["pass"] = False
                    report["errors"].append(f"Descriptor missing fields: {missing}")
                report["checks_run"].append("project_descriptor_structural_check")
        except Exception as e:
            report["pass"] = False
            report["errors"].append(f"Failed to parse descriptor: {str(e)}")
            
    # 2. Validate IR
    ir_entry = artifacts.get("dawn.project.ir")
    if not ir_entry:
        report["pass"] = False
        report["errors"].append("Missing required artifact: dawn.project.ir")
    else:
        try:
            with open(ir_entry["path"], "r") as f:
                ir_data = json.load(f)
                
                # DAWN-generic Schema Enforcement
                try:
                    from jsonschema import validate
                    from dawn.runtime.schemas import PROJECT_IR_SCHEMA
                    validate(instance=ir_data, schema=PROJECT_IR_SCHEMA)
                    report["checks_run"].append("project_ir_schema_validation")
                except ImportError:
                    report["warnings"].append("jsonschema not found, skipping deep validation")
                except Exception as ve:
                    report["pass"] = False
                    report["errors"].append(f"IR Schema Violation: {str(ve)}")

                # Sanity check: at least one node or interesting object
                node_count = len(ir_data.get("nodes", []))
                report["counts"]["nodes"] = node_count
                if node_count == 0:
                    report["warnings"].append("Project IR is empty (0 nodes discovered)")
                
                report["checks_run"].append("project_ir_sanity_check")
        except Exception as e:
            report["pass"] = False
            report["errors"].append(f"Failed to parse IR: {str(e)}")
            
    # 3. Validate Exports if present
    for artifact_id in ["dawn.project.export.primary", "dawn.project.export.workflow"]:
        if artifact_id in artifacts:
            entry = artifacts[artifact_id]
            try:
                with open(entry["path"], "r") as f:
                    json.load(f)
                report["exports_validated"].append({
                    "artifactId": artifact_id,
                    "status": "VALID_JSON"
                })
            except Exception as e:
                report["warnings"].append(f"Export {artifact_id} failed JSON validation: {str(e)}")
                
    # Final Decision
    if report["errors"]:
        report["pass"] = False
        
    report_path = os.path.join(out_dir, "handoff_validation_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
        
    status = "SUCCEEDED" if report["pass"] else "FAILED"
    return {
        "status": status,
        "metrics": {
            "checks_passed": len(report["checks_run"]),
            "errors": len(report["errors"]),
            "warnings": len(report["warnings"])
        }
    }
