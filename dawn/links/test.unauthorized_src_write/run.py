from pathlib import Path

def run(context, config):
    # Try to write to src/ without being authorized
    project_root = Path(context["project_root"])
    src_dir = project_root / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    
    unauthorized_file = src_dir / "unauthorized_file.txt"
    
    with open(unauthorized_file, "w") as f:
        f.write("I should not be here.")
        
    context["sandbox"].write_json("void.json", {"status": "violated"})
    
    return {
        "status": "SUCCEEDED"
    }
