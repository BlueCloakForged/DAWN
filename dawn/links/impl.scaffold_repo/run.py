import os
import json
from pathlib import Path

def run(context, config):
    project_root = Path(context["project_root"])
    src_dir = project_root / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    
    # Create deterministic structure
    structure = {
        "todo_cli": {
            "__init__.py": "",
            "main.py": "# Main entry point\n",
            "models.py": "# Data models\n",
            "storage.py": "# Storage logic\n"
        },
        "tests": {
            "__init__.py": "",
            "test_main.py": "def test_nothing(): pass\n"
        },
        "requirements.txt": "pytest\n",
        "README.md": "# Todo App MVP\n"
    }
    
    manifest = []
    
    def create_structure(base, struct, current_manifest):
        for name, content in struct.items():
            path = base / name
            if isinstance(content, dict):
                path.mkdir(parents=True, exist_ok=True)
                create_structure(path, content, current_manifest)
            else:
                with open(path, "w") as f:
                    f.write(content)
                rel_path = str(path.relative_to(project_root))
                current_manifest.append(rel_path)

    create_structure(src_dir, structure, manifest)
    
    context["sandbox"].write_json("scaffold_manifest.json", manifest)
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "file_count": len(manifest)
        }
    }
