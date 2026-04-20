import argparse
import os
import json
from pathlib import Path
from typing import Dict, List
from dawn.runtime.orchestrator import Orchestrator

def analyze_project(project_id: str, projects_dir: str, links_dir: str):
    project_root = Path(projects_dir) / project_id
    if not project_root.exists():
        print(f"ERROR: Project '{project_id}' does not exist at {project_root}")
        return

    # Manual context setup for read-only analysis
    # Manual context setup for read-only analysis
    orchestrator = Orchestrator(links_dir, projects_dir)
    from dawn.runtime.ledger import Ledger
    ledger = Ledger(str(project_root))
    
    artifact_index = {}
    index_path = project_root / "artifact_index.json"
    if index_path.exists():
        with open(index_path, "r") as f:
            artifact_index = json.load(f)
            
    context = {
        "project_id": project_id,
        "project_root": str(project_root),
        "ledger": ledger,
        "artifact_index": artifact_index,
        "status_index": {}
    }
    
    # Load Ledger to find the actual pipeline and status
    events = ledger.get_events()
    if not events:
        print(f"Project '{project_id}' has no ledger events. It has not been run yet.")
        print(f"NEXT STEP: Run a pipeline for this project using 'python3 -m dawn.runtime.main --project {project_id} --pipeline <path>'")
        return

    # Infer pipeline_id and current status
    pipeline_id = events[-1].get("pipeline_id")
    context["pipeline_id"] = pipeline_id
    
    print(f"\n================================================================================")
    print(f" DAWN RUNBOOK: {project_id} (Pipeline: {pipeline_id})")
    print(f"================================================================================\n")

    # Group events by link
    link_status = {}
    for ev in events:
        l_id = ev.get("link_id")
        if not l_id: continue
        status = ev.get("status")
        if status in ["STARTED", "SUCCEEDED", "FAILED", "SKIPPED"]:
            link_status[l_id] = status

    # We need the pipeline definition to know the order and requirements
    pipeline_path = project_root / "pipeline.yaml"
    if not pipeline_path.exists():
        # Fallback to checking dawn/pipelines if pipeline.yaml is missing
        pipeline_path = Path("dawn/pipelines") / f"{pipeline_id}.yaml"
        
    if not pipeline_path.exists():
        print(f"WARNING: Pipeline definition not found at {project_root / 'pipeline.yaml'} or in dawn/pipelines/.")
        print("Detailed next-step analysis may be limited.")
    else:
        import yaml
        with open(pipeline_path, "r") as f:
            pipeline = yaml.safe_load(f)
            
        links = pipeline.get("links", [])
        overrides = pipeline.get("overrides", {})
        
        found_next = False
        for l_info in links:
            l_id = l_info if isinstance(l_info, str) else l_info.get("id")
            status = link_status.get(l_id, "PENDING")
            
            if status == "PENDING" or status == "FAILED":
                print(f"CURRENT FOCUS: {l_id} ({status})")
                
                # Check requirements
                meta = orchestrator.registry.get_link(l_id)
                if not meta:
                    print(f"  ✗ ERROR: Link '{l_id}' not found in registry.")
                    break
                
                link_meta = meta["metadata"].copy()
                if l_id in overrides:
                    orchestrator._apply_overrides(link_meta, overrides[l_id])
                
                requires = link_meta.get("spec", {}).get("requires", [])
                missing = []
                for req in requires:
                    art_id = req.get("artifactId") or req.get("artifact")
                    if not art_id: continue
                    if art_id not in context["artifact_index"] and not req.get("optional", False):
                        missing.append(art_id)
                
                if missing:
                    print(f"  ✗ BLOCKED: Missing required artifacts: {', '.join(missing)}")
                    for mart in missing:
                        if mart == "dawn.gate.decision":
                            print(f"    → ACTION: Create 'human_decision.json' in 'projects/{project_id}/inputs/'.")
                        elif mart.startswith("dawn.project."):
                            print(f"    → ACTION: Ensure an ingestion link (e.g., ingest.generic_handoff) has run successfully.")
                        else:
                            print(f"    → ACTION: Resolve missing artifact '{mart}'.")
                else:
                    print(f"  ✓ READY: All requirements satisfied.")
                    print(f"  → ACTION: Execute the pipeline to run this link.")
                
                found_next = True
                break
        
        if not found_next:
            print("STATUS: All links in the pipeline have SUCCEEDED or were SKIPPED.")
            print("NEXT STEP: Project complete. Review artifacts or evidence pack.")

def main():
    parser = argparse.ArgumentParser(description="DAWN Runbook: Predictable Next Steps")
    parser.add_argument("--project", "-p", required=True, help="Project ID")
    parser.add_argument("--projects-dir", default="projects", help="Base projects directory")
    parser.add_argument("--links-dir", default="dawn/links", help="Links registry directory")
    
    args = parser.parse_args()
    analyze_project(args.project, args.projects_dir, args.links_dir)

if __name__ == "__main__":
    main()
