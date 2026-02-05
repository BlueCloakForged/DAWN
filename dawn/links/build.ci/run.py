from typing import Dict, Any

def run(project_context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Entrypoint for the link.
    
    Args:
        project_context: Dict containing project-level info (registry, ledger, artifact_store, etc.)
        link_config: The loaded link.yaml (with overrides)
        
    Returns:
        Dict containing status, outputs, and metrics.
    """
    project_id = project_context["project_id"]
    artifact_store = project_context["artifact_store"]
    
    print(f"Running {link_config['metadata']['name']} for project {project_id}")
    
    # Implementation goes here
    
    return {
        "status": "SUCCEEDED",
        "outputs": {},
        "metrics": {
            "duration": 0.1
        }
    }
