"""
DAWN Canonical Schemas
Enforces structural integrity across the SDLC pipeline.
"""

PROJECT_IR_SCHEMA = {
    "type": "object",
    "required": ["name", "nodes", "connections", "groups"],
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "role", "node_type"],
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "node_type": {"type": "string"},
                    "architecture": {"type": "string"},
                    "operating_system": {"type": "string"},
                    "template_hint": {"type": "string"},
                    "parent_group": {"type": ["string", "null"]},
                    "interfaces": {"type": "array"},
                    "services": {"type": "array"},
                    "metadata": {"type": "object"}
                }
            }
        },
        "connections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source_node", "target_node"],
                "properties": {
                    "source_node": {"type": "string"},
                    "target_node": {"type": "string"},
                    "connection_type": {"type": "string"},
                    "bidirectional": {"type": "boolean"},
                    "confidence": {"type": "number"}
                }
            }
        },
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "member_nodes"],
                "properties": {
                    "name": {"type": "string"},
                    "member_nodes": {"type": "array", "items": {"type": "string"}},
                    "parent_group": {"type": ["string", "null"]},
                    "group_type": {"type": "string"}
                }
            }
        },
        "workflow": {
            "type": "object",
            "properties": {
                "steps": {"type": "array"}
            }
        },
        "metadata": {"type": "object"}
    }
}

COHERENCE_POLICY_SCHEMA = {
    "type": "object",
    "properties": {
        "threshold": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "check_frequency": {"type": "string", "enum": ["always", "periodic"]},
        "on_drift": {"type": "string", "enum": ["fail", "warn", "pause_and_reflect"]}
    }
}

# Registry for easy lookup by name in link contracts
SCHEMA_REGISTRY = {
    "dawn.project.ir": PROJECT_IR_SCHEMA
}

META_BUNDLE_SCHEMA = {
    "type": "object",
    "required": ["timestamp", "origin_source", "environment_hash"],
    "properties": {
        "timestamp": {"type": "string"},
        "origin_source": {"type": "string"},
        "environment_hash": {"type": "string"},
        "media_digests": {
            "type": "object",
            "additionalProperties": {"type": "string"}
        }
    }
}
