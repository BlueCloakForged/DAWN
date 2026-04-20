from typing import Dict, Any

def run(project_context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    project_id = project_context["project_id"]
    artifact_store = project_context["artifact_store"]
    
    print(f"Running service.catalog for project {project_id}")
    
    artifact_name = "catalog.json"
    content = {"project_id": project_id, "status": "scaffolded", "timestamp": project_context.get("timestamp", 123)}
    
    # Use artifact store to write
    file_path = artifact_store.write_artifact("service.catalog", artifact_name, content)
    
    return {
        "status": "SUCCEEDED",
        "outputs": {
            artifact_name: {"path": str(file_path)}
        },
        "metrics": {
            "duration": 0.1
        }
    }
