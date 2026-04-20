import argparse
import json
import os
import sys
import yaml
from pathlib import Path
from dawn.runtime.orchestrator import Orchestrator
from dawn.runtime.ledger import Ledger

def get_project_status(project_id, projects_dir, links_dir):
    project_root = Path(projects_dir) / project_id
    if not project_root.exists():
        return {"error": f"Project {project_id} not found"}

    orchestrator = Orchestrator(links_dir, projects_dir)
    ledger = Ledger(str(project_root))
    events = ledger.get_events()
    
    # Artifact Index
    artifact_index = {}
    index_path = project_root / "artifact_index.json"
    if index_path.exists():
        with open(index_path, "r") as f:
            artifact_index = json.load(f)

    # Status Index
    link_status = {}
    pipeline_id = None
    for ev in events:
        pipeline_id = ev.get("pipeline_id")
        l_id = ev.get("link_id")
        if not l_id: continue
        status = ev.get("status")
        if status in ["STARTED", "SUCCEEDED", "FAILED", "SKIPPED"]:
            link_status[l_id] = status
    
    # Fallback to project metadata if ledger is empty
    if not pipeline_id:
        meta_path = project_root / "config" / "project.json"
        if meta_path.exists():
            with open(meta_path, "r") as f:
                try:
                    meta = json.load(f)
                    pipeline_id = meta.get("pipeline_id")
                except: pass

    # Next Step Analysis
    next_link = None
    required_inputs = []
    
    pipeline_path = project_root / "pipeline.yaml"
    if not pipeline_path.exists():
        pipeline_path = Path("dawn/pipelines") / f"{pipeline_id}.yaml" if pipeline_id else None
        
    if pipeline_path and pipeline_path.exists():
        with open(pipeline_path, "r") as f:
            pipeline = yaml.safe_load(f)
            
        links = pipeline.get("links", [])
        for l_info in links:
            l_id = l_info if isinstance(l_info, str) else l_info.get("id")
            status = link_status.get(l_id, "PENDING")
            
            if status == "PENDING" or status == "FAILED":
                next_link = l_id
                meta = orchestrator.registry.get_link(l_id)
                if meta:
                    requires = meta["metadata"].get("spec", {}).get("requires", [])
                    for req in requires:
                        art_id = req.get("artifactId") or req.get("artifact")
                        if not art_id or req.get("optional", False): continue
                        if art_id not in artifact_index:
                            required_inputs.append(art_id)
                break

    return {
        "project_id": project_id,
        "pipeline_id": pipeline_id,
        "status": link_status,
        "next_step": next_link,
        "required_inputs": required_inputs,
        "artifact_index": list(artifact_index.keys()),
        "last_event": events[-1] if events else None
    }

def main():
    parser = argparse.ArgumentParser(description="DAWN Agent Interface (JSON)")
    parser.add_argument("--project", "-p", required=True, help="Project ID")
    parser.add_argument("--action", "-a", required=True, choices=["runbook", "run", "inspect", "artifact_open", "release"])
    parser.add_argument("--args", help="Action arguments as JSON string")
    parser.add_argument("--human", action="store_true", help="Pretty-print for humans")
    parser.add_argument("--projects-dir", default="projects")
    parser.add_argument("--links-dir", default="dawn/links")
    parser.add_argument("--executor", default="local", choices=["local", "subprocess"], help="Executor backend")
    
    args = parser.parse_args()
    
    response = {"status": "error", "message": "Unknown action"}
    
    try:
        if args.action == "runbook" or args.action == "inspect":
            response = {"status": "success", "data": get_project_status(args.project, args.projects_dir, args.links_dir)}
        
        elif args.action == "run" or args.action == "release":
            from dawn.runtime.executors import get_executor
            executor = get_executor(args.executor, links_dir=args.links_dir, projects_dir=args.projects_dir)
            
            pipeline = None
            if args.args:
                try:
                    pipeline = json.loads(args.args).get("pipeline")
                except: pass
            
            if args.action == "release" and not pipeline:
                pipeline = "dawn/pipelines/app_mvp.yaml" # Default release-capable pipeline
            
            if not pipeline:
                # Try to infer from ledger
                status = get_project_status(args.project, args.projects_dir, args.links_dir)
                pipeline_id = status.get("pipeline_id")
                if pipeline_id:
                    pipeline = f"dawn/pipelines/{pipeline_id}.yaml"
            
            if not pipeline:
                response = {"status": "error", "message": "No pipeline specified and could not infer from project."}
            else:
                executor.run_pipeline(args.project, pipeline_path=pipeline)
                response = {"status": "success", "data": get_project_status(args.project, args.projects_dir, args.links_dir)}

        elif args.action == "artifact_open":
            if not args.args:
                response = {"status": "error", "message": "Missing --args '{\"artifactId\": \"...\"}'"}
            else:
                art_args = json.loads(args.args)
                art_id = art_args.get("artifactId")
                
                project_root = Path(args.projects_dir) / args.project
                index_path = project_root / "artifact_index.json"
                
                with open(index_path, "r") as f:
                    index = json.load(f)
                
                if art_id in index:
                    art_path = Path(index[art_id]["path"])
                    content = None
                    if art_path.suffix in [".json", ".md", ".txt", ".yaml"]:
                        with open(art_path, "r") as f:
                            content = f.read()
                    
                    response = {
                        "status": "success", 
                        "data": {
                            "artifactId": art_id,
                            "path": str(art_path),
                            "content": content
                        }
                    }
                else:
                    response = {"status": "error", "message": f"Artifact {art_id} not found."}

    except Exception as e:
        response = {"status": "error", "message": str(e)}

    if args.human:
        print(json.dumps(response, indent=2))
    else:
        print(json.dumps(response))

if __name__ == "__main__":
    main()
