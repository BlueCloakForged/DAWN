
import os
import json
import time
from pathlib import Path
from dawn.runtime.orchestrator import Orchestrator
from dawn.runtime.new import bootstrap_project
from dawn.runtime.executors.local import LocalExecutor
from dawn.runtime.project_index import update_project_index

def test_uri_pointers():
    print("Verifying URI pointers in dawn.project.bundle...")
    project_id = "test_verify_uri"
    project_root = Path("projects") / project_id
    if project_root.exists():
        import shutil
        shutil.rmtree(project_root)
        
    bootstrap_project(project_id, "autofix")
    
    # Create a dummy file
    (project_root / "inputs" / "hello.py").write_text("print('hello')")
    
    # Run the orchestrator for a real check
    orchestrator = Orchestrator("dawn/links", "projects")
    orchestrator.run_pipeline(project_id, "dawn/pipelines/autofix.yaml")
    
    # Check bundle file
    bundle_path = project_root / "artifacts" / "ingest.project_bundle" / "dawn.project.bundle.json"
    with open(bundle_path) as f:
        bundle = json.load(f)
    
    for f in bundle["files"]:
        if "uri" not in f:
            raise Exception(f"URI missing for file {f['path']}")
        print(f"  ✓ Found URI: {f['uri']}")

def test_metadata_persistence():
    print("Verifying metadata persistence...")
    project_id = "test_verify_metadata"
    project_root = Path("projects") / project_id
    if project_root.exists():
        import shutil
        shutil.rmtree(project_root)
        
    metadata = {"trace_id": "agent-trace-123", "user": "developer"}
    bootstrap_project(project_id, "autofix", metadata=metadata)
    
    # Check config/project.json
    with open(project_root / "config" / "project.json") as f:
        config = json.load(f)
    
    if config.get("metadata") != metadata:
        raise Exception(f"Metadata not persisted in project.json: {config.get('metadata')}")
    print("  ✓ Metadata persisted in project.json")
    
    executor = LocalExecutor(projects_dir="projects")
    result = executor.run_pipeline(project_id, pipeline_id="autofix", metadata=metadata)
    
    # Check run.json
    run_dir = project_root / "runs" / result.run_id
    with open(run_dir / "run.json") as f:
        run_data = json.load(f)
        
    if run_data.get("metadata") != metadata:
        raise Exception(f"Metadata not persisted in run.json: {run_data.get('metadata')}")
    print("  ✓ Metadata persisted in run.json")

def test_metrics_indexing():
    print("Verifying metrics indexing...")
    project_id = "test_verify_metrics"
    project_root = Path("projects") / project_id
    if not project_root.exists():
        bootstrap_project(project_id, "autofix")
        
    executor = LocalExecutor(projects_dir="projects")
    executor.run_pipeline(project_id, pipeline_id="autofix")
    
    update_project_index(project_root)
    
    with open(project_root / "project_index.json") as f:
        index = json.load(f)
        
    for link_id, info in index.get("links", {}).items():
        if info.get("status") == "SUCCEEDED":
            if "metrics" not in info:
                raise Exception(f"Metrics missing for link {link_id}")
            print(f"  ✓ Metrics found for link {link_id}: {info['metrics'].keys()}")

if __name__ == "__main__":
    try:
        test_uri_pointers()
        test_metadata_persistence()
        test_metrics_indexing()
        print("\n🎉 ALL VERIFICATION TESTS PASSED!")
    except Exception as e:
        print(f"\n❌ VERIFICATION FAILED: {e}")
        import traceback
        traceback.print_exc()
