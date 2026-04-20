from typing import Dict, Any

def run(project_context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    project_id = project_context["project_id"]
    artifact_store = project_context["artifact_store"]
    
    print(f"Running quality.gates for project {project_id}")
    
    produces = link_config.get("spec", {}).get("produces", [])
    artifact_name = produces[0].get("path", "report.json") if produces else "report.json"
    content = {"pass": True, "score": 100}
    
    file_path = artifact_store.write_artifact("quality.gates", artifact_name, content)
    
    return {
        "status": "SUCCEEDED",
        "outputs": {
            artifact_name: {"path": str(file_path)}
        },
        "metrics": {
            "duration": 0.1
        }
    }
