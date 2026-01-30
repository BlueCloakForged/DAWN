import argparse
import json
import os
import yaml
from pathlib import Path

MANIFEST_PATH = "dawn/pipelines/pipeline_manifest.json"

def list_pipelines():
    if not os.path.exists(MANIFEST_PATH):
        print("Pipeline manifest not found.")
        return
    
    with open(MANIFEST_PATH, "r") as f:
        manifest = json.load(f)
    
    print(f"\nDAWN GOLDEN PIPELINES")
    print("=" * 80)
    print(f"{'ID':<20} {'Version':<10} {'Profile':<10} {'Description'}")
    print("-" * 80)
    for p in manifest:
        profile = p.get('profile', 'normal')
        print(f"{p['id']:<20} {p['version']:<10} {profile:<10} {p['description']}")
    print("-" * 80 + "\n")

def describe_pipeline(pipeline_id):
    if not os.path.exists(MANIFEST_PATH):
        print("Pipeline manifest not found.")
        return None
    
    with open(MANIFEST_PATH, "r") as f:
        manifest = json.load(f)
    
    entry = next((p for p in manifest if p["id"] == pipeline_id), None)
    if not entry:
        print(f"Error: Pipeline '{pipeline_id}' not found in manifest.")
        return None

    print(f"\nPIPELINE: {entry['id']} (v{entry['version']})")
    print(f"Description: {entry['description']}")
    print(f"Intended Use: {entry['intended_use']}")
    print(f"Profile: {entry.get('profile', 'normal')}")
    print(f"Est. Duration: {entry.get('estimated_duration_seconds', 'unknown')}s")
    print("-" * 40)
    
    # Required inputs
    print("Required Inputs:")
    for inp in entry.get('required_inputs', []):
        opt = " (optional)" if inp.get('optional', False) else ""
        print(f"  • {inp['name']}{opt}: {inp['description']}")
    
    print("\nExpected Outputs (artifactIds):")
    for art in entry.get('expected_outputs', []):
        print(f"  • {art}")
    
    # Links
    if os.path.exists(entry["path"]):
        with open(entry["path"], "r") as f:
            spec = yaml.safe_load(f)
            links = spec.get("links", [])
            print("\nPipeline Links:")
            for l in links:
                l_id = l if isinstance(l, str) else l.get("id")
                print(f"  • {l_id}")
    else:
        print(f"Error: Pipeline file not found at {entry['path']}")
    print("-" * 40 + "\n")
    
    return entry

def run_pipeline(pipeline_id, project_id, executor_name="local", profile_override=None):
    """Run a pipeline by ID."""
    entry = describe_pipeline(pipeline_id)
    if not entry:
        return
    
    pipeline_path = entry['path']
    profile = profile_override or entry.get('profile', 'normal')
    
    # Use Executor abstraction
    from dawn.runtime.executors import get_executor
    
    print(f"\nStarting pipeline {pipeline_id} for project {project_id} via {executor_name} executor...")
    executor = get_executor(executor_name)
    result = executor.run_pipeline(project_id, pipeline_path=pipeline_path, profile=profile)
    
    print(f"\nPipeline {pipeline_id} execution {result.status.lower()}.")
    if result.errors:
        print(f"Errors: {result.errors}")

def main():
    parser = argparse.ArgumentParser(description="DAWN Pipelines Library")
    subparsers = parser.add_subparsers(dest="command")
    
    subparsers.add_parser("list", help="List golden pipelines")
    
    desc_parser = subparsers.add_parser("describe", help="Describe a pipeline")
    desc_parser.add_argument("--id", required=True, help="Pipeline ID")
    
    run_parser = subparsers.add_parser("run", help="Run a pipeline by ID")
    run_parser.add_argument("--id", required=True, help="Pipeline ID")
    run_parser.add_argument("--project", "-p", required=True, help="Project ID")
    run_parser.add_argument("--executor", default="local", choices=["local", "subprocess"], help="Executor backend")
    run_parser.add_argument("--profile", help="Override safety profile")
    
    args = parser.parse_args()
    
    if args.command == "list":
        list_pipelines()
    elif args.command == "describe":
        describe_pipeline(args.id)
    elif args.command == "run":
        run_pipeline(args.id, args.project, executor_name=args.executor, profile_override=args.profile)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
