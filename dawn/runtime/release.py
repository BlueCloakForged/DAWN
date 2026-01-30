import argparse
import sys
from pathlib import Path
from dawn.runtime.orchestrator import Orchestrator

def main():
    parser = argparse.ArgumentParser(description="DAWN Project Release CLI")
    parser.add_argument("--project", "-p", required=True, help="Project ID")
    parser.add_argument("--projects-dir", default="projects", help="Base projects directory")
    parser.add_argument("--links-dir", default="dawn/links", help="Links registry directory")
    parser.add_argument("--pipeline", default="dawn/pipelines/app_mvp.yaml", help="Pipeline to use (must include release link)")
    
    args = parser.parse_args()
    
    orchestrator = Orchestrator(args.links_dir, args.projects_dir)
    
    print(f"Starting release for project: {args.project}")
    try:
        # We run the pipeline. Idempotency will ensure only new/release links run.
        orchestrator.run_pipeline(args.project, args.pipeline)
        print(f"\nRelease complete for project: {args.project}")
    except Exception as e:
        print(f"\nRelease failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
