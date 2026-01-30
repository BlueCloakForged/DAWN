import argparse
import sys
from pathlib import Path
from dawn.runtime.orchestrator import Orchestrator

def main():
    parser = argparse.ArgumentParser(description="DAWN Orchestrator: Execute SDLC pipelines.")
    parser.add_argument("--project", "-p", required=True, help="Project ID")
    parser.add_argument("--pipeline", "-l", required=True, help="Path to pipeline YAML")
    parser.add_argument("--profile", help="Isolation profile to use")
    
    args = parser.parse_args()
    
    # If run as python3 -m dawn.runtime.main, __file__ is repo/dawn/runtime/main.py
    # We want base_dir to be repo/
    base_dir = Path(__file__).parent.parent.parent
    links_dir = base_dir / "dawn" / "links"
    projects_dir = base_dir / "projects"
    
    orchestrator = Orchestrator(str(links_dir), str(projects_dir), profile=args.profile)
    
    status = "SUCCEEDED"
    error = None
    try:
        orchestrator.run_pipeline(args.project, args.pipeline)
    except Exception as e:
        status = "FAILED"
        error = str(e)
        print(f"\nPipeline execution failed: {e}")
        # We don't exit(1) immediately to allow index update
    
    # Update project index
    try:
        from dawn.runtime.project_index import update_project_index
        project_root = projects_dir / args.project
        update_project_index(project_root, pipeline_meta={
            "path": args.pipeline,
            "profile": args.profile,
            "executor": "local" # main.py is the in-process entry for subprocesses
        }, run_context={
            "status": status,
            "run_id": f"run_{int(time.time())}"
        })
    except: pass

    if status == "FAILED":
        exit(1)

if __name__ == "__main__":
    main()
