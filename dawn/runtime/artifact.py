import argparse
import os
import json
from pathlib import Path

def resolve_artifact(project_id: str, artifact_id: str, print_content: bool, projects_dir: str):
    project_root = Path(projects_dir) / project_id
    index_path = project_root / "artifact_index.json"
    
    if not index_path.exists():
        print(f"ERROR: Artifact index not found for project '{project_id}' at {index_path}")
        return

    with open(index_path, "r") as f:
        index = json.load(f)

    if artifact_id not in index:
        print(f"ERROR: Artifact ID '{artifact_id}' not found in project '{project_id}'.")
        # Suggest available IDs
        print(f"Available IDs: {', '.join(index.keys())}")
        return

    entry = index[artifact_id]
    path = entry["path"]
    
    # If path is relative to project root in the index? 
    # Current Orchestrator stores absolute paths, but let's be safe.
    abs_path = Path(path)
    if not abs_path.is_absolute():
        # Check if the path already looks like it's relative to the CWD (projects/...)
        if not (abs_path.exists()):
            abs_path = project_root / path
            if not abs_path.exists():
                # Fallback to checking if it's already a subpath of project_root in some other way?
                # For now, let's just use the projects_dir-prefixed one if it exists.
                pass

    print(str(abs_path))

    if print_content:
        if not abs_path.exists():
            print(f"ERROR: File does not exist at {abs_path}")
            return
        
        print("\n--- CONTENT START ---")
        try:
            with open(abs_path, "r") as f:
                print(f.read())
        except Exception as e:
            print(f"ERROR reading file: {str(e)}")
        print("--- CONTENT END ---")

def main():
    parser = argparse.ArgumentParser(description="DAWN Artifact Helper")
    subparsers = parser.add_subparsers(dest="command")

    open_parser = subparsers.add_parser("open", help="Resolve and optionally print an artifact")
    open_parser.add_argument("--project", "-p", required=True, help="Project ID")
    open_parser.add_argument("--artifactId", "-a", required=True, help="Artifact ID")
    open_parser.add_argument("--print", action="store_true", help="Print content to stdout")
    open_parser.add_argument("--projects-dir", default="projects", help="Base projects directory")

    args = parser.parse_args()
    
    if args.command == "open":
        resolve_artifact(args.project, args.artifactId, args.print, args.projects_dir)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
