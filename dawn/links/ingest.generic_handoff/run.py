import os
import json
from pathlib import Path

def run(context, config):
    project_id = context["project_id"]
    inputs_dir = Path(context["project_root"]) / "inputs"
    
    print(f"Starting Generic handoff for project: {project_id}")
    
    # 1. Look for input files to describe the project
    input_files = []
    if inputs_dir.exists():
        input_files = [f.name for f in inputs_dir.iterdir() if f.is_file()]
    
    # 2. Generate Descriptor
    descriptor = {
        "project_id": project_id,
        "created_at": "2026-01-17T00:00:00Z",
        "source_bundle": {
            "files": input_files,
            "digest": "generic-sha256"
        },
        "handoff": {
            "version": "1.0",
            "engine": "generic_ingest"
        }
    }
    
    # 3. Generate a simple Project IR that matches the schema
    project_ir = {
        "name": f"Project {project_id}",
        "description": f"A generic project based on inputs: {input_files}",
        "nodes": [
            {
                "name": "GenericNode-01",
                "role": "application",
                "node_type": "instance",
                "operating_system": "linux",
                "interfaces": [],
                "services": []
            }
        ],
        "connections": [],
        "groups": [
            {
                "name": "DefaultGroup",
                "member_nodes": ["GenericNode-01"],
                "group_type": "enclave"
            }
        ],
        "metadata": {"source": "ingest.generic_handoff"}
    }
    
    # 4. Save artifacts via sandbox
    context["sandbox"].write_json("project_descriptor.json", descriptor)
    context["sandbox"].write_json("project_ir.json", project_ir)
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "input_file_count": len(input_files),
            "node_count": len(project_ir["nodes"])
        }
    }
