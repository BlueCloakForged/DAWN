import json
from pathlib import Path

def run(context, config):
    artifacts = context["artifact_index"]
    desc_path = Path(artifacts["dawn.project.descriptor"]["path"])
    ir_path = Path(artifacts["dawn.project.ir"]["path"])
    
    with open(desc_path, "r") as f:
        desc = json.load(f)
    with open(ir_path, "r") as f:
        ir = json.load(f)
        
    project_id = desc.get("project_id", "Unknown")
    description = ir.get("description", "No description available.")
    nodes = ir.get("nodes", [])
    
    plan_content = f"""# Solution Outline: {project_id}

## 1. Project Overview
{description}

## 2. Technical Architecture
The following components have been identified in the IR:
"""
    for node in nodes:
        plan_content += f"- **{node['name']}**: {node['role']} ({node['node_type']}) on {node.get('operating_system', 'unknown')}\n"
        
    plan_content += """
## 3. Implementation Checklist
- [ ] Scaffold project repository
- [ ] Define API contracts
- [ ] Implement core components
- [ ] Apply deterministic patchset
- [ ] Verify with smoke tests

## 4. Constraints & Assumptions
- All code must be deterministic and verifiable.
- Artifacts must follow DAWN contract specifications.
- Sandbox boundaries must be respected.
"""

    context["sandbox"].write_text("plan.md", plan_content)
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "component_count": len(nodes)
        }
    }
