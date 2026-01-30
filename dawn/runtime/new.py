import argparse
import os
import yaml
import json
import time
from pathlib import Path

MANIFEST_PATH = "dawn/pipelines/pipeline_manifest.json"

TEMPLATES = {
    "idea.md": "# Project Idea\n\nDescribe the application you want DAWN to build here.",
    "human_decision.json": "{\n  \"decision\": \"PENDING\",\n  \"by\": \"operator\",\n  \"timestamp\": \"\"\n}",
    "patch_approval.json": "{\n  \"decision\": \"PENDING\",\n  \"patchset_digest\": \"\",\n  \"instructions\": \"Set decision to APPROVED and paste the digest from the generated patchset.\"\n}",
}

README_TEMPLATE = """# DAWN Project: {project_id}

Pipeline: **{pipeline_id}** (v{version})
Profile: {profile}

## Description
{description}

## What to do next:

{next_steps}

## Quick Commands

```bash
# Check status
python3 -m dawn.runtime.runbook --project {project_id}

# Run pipeline
python3 -m dawn.runtime.pipelines run --id {pipeline_id} --project {project_id}

# View results
python3 -m dawn.runtime.inspect --project {project_id}
```
"""

def load_pipeline_metadata(pipeline_id_or_path):
    """Load pipeline metadata from manifest or path."""
    # Check if it's a pipeline ID from the catalog
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r") as f:
            manifest = json.load(f)
        
        entry = next((p for p in manifest if p["id"] == pipeline_id_or_path), None)
        if entry:
            return entry, entry["path"]
    
    # Otherwise treat as direct path
    if os.path.exists(pipeline_id_or_path):
        with open(pipeline_id_or_path, "r") as f:
            pipeline_spec = yaml.safe_load(f)
        return {
            "id": pipeline_spec.get("pipelineId", "custom"),
            "version": "custom",
            "description": "Custom pipeline",
            "required_inputs": [],
            "profile": "normal"
        }, pipeline_id_or_path
    
    return None, None

def bootstrap_project(project_id, pipeline, profile="normal", projects_dir="projects", metadata=None):
    """Bootstrap a new DAWN project with pipeline-aware templates."""
    project_root = Path(projects_dir) / project_id
    if project_root.exists():
        print(f"Error: Project directory {project_root} already exists.")
        return False

    print(f"Bootstrapping project '{project_id}'...")
    
    # Load pipeline metadata
    pipeline_meta, pipeline_path = load_pipeline_metadata(pipeline)
    if not pipeline_meta:
        print(f"Error: Pipeline '{pipeline}' not found in catalog or as file path.")
        return False
    
    # Create directories
    dirs = ["inputs", "config", "docs", "src", "tests"]
    for d in dirs:
        (project_root / d).mkdir(parents=True, exist_ok=True)

    # Write only required input templates based on pipeline
    required_inputs = pipeline_meta.get("required_inputs", [])
    created_inputs = []
    
    for inp in required_inputs:
        input_name = inp["name"]
        if input_name in TEMPLATES:
            with open(project_root / "inputs" / input_name, "w") as f:
                f.write(TEMPLATES[input_name])
            created_inputs.append(f"✓ {input_name}: {inp['description']}")
    
    # Generate deterministic next steps
    next_steps = []
    if any(inp["name"] == "idea.md" for inp in required_inputs):
        next_steps.append("1. Edit `inputs/idea.md` with your project requirements")
    
    if any(inp["name"] == "patch_approval.json" for inp in required_inputs):
        next_steps.append("2. Run pipeline to generate patchset, then approve it in `inputs/patch_approval.json`")
    
    next_steps.append(f"{len(next_steps)+1}. Run: `python3 -m dawn.runtime.runbook --project {project_id}`")
    next_steps.append(f"{len(next_steps)+1}. Execute: `python3 -m dawn.runtime.pipelines run --id {pipeline_meta['id']} --project {project_id}`")
    
    # Generate README
    readme_content = README_TEMPLATE.format(
        project_id=project_id,
        pipeline_id=pipeline_meta["id"],
        version=pipeline_meta.get("version", "unknown"),
        profile=profile,
        description=pipeline_meta.get("description", "No description"),
        next_steps="\n".join(next_steps)
    )
    
    with open(project_root / "README.md", "w") as f:
        f.write(readme_content)

    # Save project metadata for inference
    config_data = {
        "project_id": project_id,
        "pipeline_id": pipeline_meta["id"],
        "profile": profile,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    if metadata:
        config_data["metadata"] = metadata

    with open(project_root / "config" / "project.json", "w") as f:
        json.dump(config_data, f, indent=2)

    # Update project index
    try:
        from dawn.runtime.project_index import update_project_index
        update_project_index(project_root, pipeline_meta={
            "id": pipeline_meta["id"],
            "path": pipeline_path,
            "version": pipeline_meta.get("version"),
            "profile": profile
        })
    except: pass

    # Summary
    print(f"\nProject '{project_id}' created successfully!")
    print(f"Pipeline: {pipeline_meta['id']} (v{pipeline_meta.get('version', 'unknown')})")
    print(f"Profile: {profile}")
    print(f"\nCreated input templates:")
    for inp in created_inputs:
        print(f"  {inp}")
    
    print(f"\nNext steps:")
    for step in next_steps:
        print(f"  {step}")
    
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DAWN Project Bootstrapper")
    parser.add_argument("--project", "-p", required=True, help="Project ID")
    parser.add_argument("--pipeline", "-l", help="Pipeline file path (deprecated)")
    parser.add_argument("--pipeline-id", help="Pipeline ID from golden catalog")
    parser.add_argument("--profile", default="normal", choices=["normal", "isolation"], help="Execution profile")
    parser.add_argument("--projects-dir", default="projects", help="Base projects directory")
    parser.add_argument("--metadata", help="Metadata as JSON string")
    
    args = parser.parse_args()
    
    # Accept either --pipeline or --pipeline-id
    pipeline = args.pipeline_id or args.pipeline or "dawn/pipelines/golden/handoff_min.yaml"
    
    metadata = json.loads(args.metadata) if args.metadata else None
    bootstrap_project(args.project, pipeline, args.profile, args.projects_dir, metadata=metadata)
