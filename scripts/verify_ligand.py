import os
import json
import yaml
from pathlib import Path
from dawn.runtime.orchestrator import Orchestrator
from dawn.runtime.artifact_store import ArtifactStore
from dawn.runtime.ligand_query import get_ligand_status

def setup_test_project(orchestrator, project_id):
    project_root = orchestrator.projects_dir / project_id
    project_root.mkdir(parents=True, exist_ok=True)
    
    # Create a dummy input artifact
    inputs_dir = project_root / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    with open(inputs_dir / "blueprint.json", "w") as f:
        json.dump({"score": 0.6}, f)
    
    # Create a pipeline that uses synapse_threshold
    pipeline = {
        "pipelineId": "ligand_test",
        "links": [
            {
                "id": "logic.generate_ir",
                "config": {}
            },
            {
                "id": "ligand.synapse_threshold",
                "config": {
                    "source_artifacts": ["dawn.project.ir"],
                    "target_field": "score",
                    "threshold": 0.5
                }
            }
        ]
    }
    
    pipeline_path = project_root / "pipeline.yaml"
    with open(pipeline_path, "w") as f:
        yaml.dump(pipeline, f)
        
    return pipeline_path

def verify_ligand():
    print("--- LIGAND Framework Verification ---")
    
    # Calculate paths relative to DAWN root
    script_dir = Path(__file__).resolve().parent
    dawn_root = script_dir.parent
    links_dir = str(dawn_root / "dawn" / "links")
    projects_dir = str(dawn_root / "projects")
    orchestrator = Orchestrator(links_dir, projects_dir)
    
    # Initial state
    pool_path = dawn_root / "artifacts" / "ligand.pool.json"
    with open(pool_path, "w") as f:
        json.dump({"vector": {"alpha": 1.0}, "meta": {"test": True}}, f)
    
    print(f"Initial Vector: {get_ligand_status()}")

    # Setup project
    project_id = "ligand_verify_001"
    pipeline_path = setup_test_project(orchestrator, project_id)
    
    # Run 1: Should fire (score 0.6 > threshold 0.5)
    print("\nRunning Verification Pipeline...")
    orchestrator.run_pipeline(project_id, str(pipeline_path))
    
    # Check Artifacts
    store = ArtifactStore(str(orchestrator.projects_dir / project_id))
    gate = store.get("ligand.gate_open")
    if gate:
        print("✅ SUCCESS: ligand.gate_open produced.")
    else:
        print("❌ FAILURE: ligand.gate_open missing.")
        
    # Check Snapshot
    snapshot_path = Path(store.project_root) / "artifacts" / "meta.bundle" / "ligand.pool.snapshot.json"
    if snapshot_path.exists():
        with open(snapshot_path, "r") as f:
            snap = json.load(f)
            print(f"✅ SUCCESS: Snapshot found. Alpha={snap['vector']['alpha']}")
    else:
        print("❌ FAILURE: Snapshot missing.")

    # Check Decay
    final_vector = get_ligand_status()
    print(f"Vector After Decay: {final_vector}")
    if final_vector.get("alpha", 1.0) < 1.0:
        print("✅ SUCCESS: Homeostatic decay applied.")
    else:
        print("❌ FAILURE: Decay not applied.")

if __name__ == "__main__":
    verify_ligand()
