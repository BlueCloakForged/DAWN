#!/usr/bin/env python3
"""
DAWN Pipeline Runner (Release Version)
"""

import sys
import argparse
from pathlib import Path

# Add core DAWN to path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from dawn.runtime.orchestrator import Orchestrator

def main():
    parser = argparse.ArgumentParser(description="Run a specific pipeline from its YAML file")
    parser.add_argument("project_id", help="The name of the project folder in 'projects/'")
    parser.add_argument("--pipeline", default="pipeline.yaml", help="Path to pipeline YAML (relative to project root)")
    
    args = parser.parse_args()

    # Configuration Paths
    links_dir = BASE_DIR / "dawn" / "links"
    projects_dir = BASE_DIR / "projects"
    
    projects_dir.mkdir(exist_ok=True)
    
    # Resolve pipeline path
    pipeline_path = projects_dir / args.project_id / args.pipeline
    if not pipeline_path.exists():
        print(f"Error: Pipeline file not found at {pipeline_path}")
        sys.exit(1)

    print(f"Running pipeline for project: {args.project_id}")
    print(f"Links directory: {links_dir}")
    
    orchestrator = Orchestrator(str(links_dir), str(projects_dir))
    
    try:
        context = orchestrator.run_pipeline(args.project_id, str(pipeline_path))
        print("\n✅ Pipeline completed successfully")
        
    except Exception as e:
        print(f"\n❌ Pipeline failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
