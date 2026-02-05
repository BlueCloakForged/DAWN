import json

def run(context, config):
    # In a real scenario, this would analyze the plan.md
    # For this MVP, we generate a deterministic TODO API.
    
    api_spec = {
        "version": "1.0.0",
        "endpoints": [
            {
                "path": "/todo",
                "methods": ["GET", "POST"],
                "description": "Handles todo items"
            },
            {
                "path": "/todo/{id}",
                "methods": ["PUT", "DELETE"],
                "description": "Manage specific todo item"
            }
        ],
        "schemas": {
            "Todo": {
                "id": "integer",
                "task": "string",
                "done": "boolean"
            }
        }
    }
    
    context["sandbox"].write_json("api_contracts.json", api_spec)
    
    return {
        "status": "SUCCEEDED"
    }
