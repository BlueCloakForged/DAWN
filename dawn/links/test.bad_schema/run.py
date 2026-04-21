"""Executes the test.bad_schema step in the DAWN pipeline."""
import json

def run(context, config):
    # Intentional schema violation: missing 'nodes', 'connections', etc.
    """Run."""
    bad_ir = {
        "name": "Invalid Project"
    }
    
    context["sandbox"].write_json("project_ir.json", bad_ir)
    
    return {
        "status": "SUCCEEDED"
    }
