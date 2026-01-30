"""
JSON Artifact Boundary Validator

Validates JSON artifacts at the boundary:
1. Must parse as valid JSON
2. Must be object (dict) at top-level
3. Must include schema_version (if enforced)

Config-driven and reusable across pipelines.
"""

import json
from pathlib import Path


class JSONValidationError(Exception):
    """Raised when JSON artifact validation fails"""
    pass


def run(context, config):
    """
    Validate JSON artifacts at boundary.
    
    Config:
      artifacts_to_validate: list of artifact IDs
      enforce_schema_version: bool (default True)
      enforce_generator_id: bool (default False)
      allow_enveloped_payloads: bool (default False) - for CRO/n8n wrapped formats
    """
    artifact_index = context.get("artifact_index", {})
    artifacts_to_validate = config.get("artifacts_to_validate", [])
    enforce_schema_version = config.get("enforce_schema_version", True)
    enforce_generator_id = config.get("enforce_generator_id", False)
    allow_enveloped = config.get("allow_enveloped_payloads", False)
    
    if not artifacts_to_validate:
        print("Warning: No artifacts configured for validation")
        return {"status": "SUCCEEDED", "metrics": {"validated": 0}}
    
    results = []
    
    for artifact_id in artifacts_to_validate:
        artifact = artifact_index.get(artifact_id)
        if not artifact:
            # Skip if artifact doesn't exist (might be optional)
            print(f"Skipping {artifact_id} (not found in artifact index)")
            continue
        
        artifact_path = Path(artifact["path"])
        
        if not artifact_path.exists():
            print(f"Skipping {artifact_id} (file does not exist: {artifact_path})")
            continue
        
        try:
            # 1. Parse JSON
            with open(artifact_path, 'r') as f:
                data = json.load(f)
            
            # 2. Must be object
            if not isinstance(data, dict):
                raise JSONValidationError(
                    f"Expected object/dict, got {type(data).__name__}"
                )
            
            # 3. Check for enveloped payload format
            is_enveloped = allow_enveloped and "payload" in data and "format" in data
            validation_target = data["payload"] if is_enveloped else data
            
            # 4. Must have schema_version (if enforced, on outer envelope)
            if enforce_schema_version and "schema_version" not in data:
                raise JSONValidationError(
                    "Missing required field: schema_version"
                )
            
            # 5. Must have generator_id or generated_by (if enforced)
            if enforce_generator_id:
                if "generator_id" not in validation_target and "generated_by" not in validation_target:
                    raise JSONValidationError(
                        "Missing required field: generator_id or generated_by"
                    )
            
            results.append({
                "artifact_id": artifact_id,
                "path": str(artifact_path),
                "status": "valid",
                "schema_version": data.get("schema_version"),
                "enveloped": is_enveloped,
                "size_bytes": artifact_path.stat().st_size
            })
            
            envelope_note = f" (enveloped: {data.get('format')})" if is_enveloped else ""
            print(f"✓ {artifact_id}: valid JSON (schema_version={data.get('schema_version')}){envelope_note}")
            
        except json.JSONDecodeError as e:
            error_msg = (
                f"JSON validation failed for {artifact_id}\n"
                f"Artifact: {artifact_id}\n"
                f"Path: {artifact_path}\n"
                f"Error: Invalid JSON: {e}"
            )
            raise JSONValidationError(error_msg)
            
        except JSONValidationError as e:
            error_msg = (
                f"JSON validation failed for {artifact_id}\n"
                f"Artifact: {artifact_id}\n"
                f"Path: {artifact_path}\n"
                f"Error: {e}"
            )
            raise JSONValidationError(error_msg)
            
        except Exception as e:
            error_msg = (
                f"JSON validation failed for {artifact_id}\n"
                f"Artifact: {artifact_id}\n"
                f"Path: {artifact_path}\n"
                f"Error: Unexpected error: {e}"
            )
            raise JSONValidationError(error_msg)
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "validated": len(results),
            "artifacts": results
        }
    }
    
    if not artifacts_to_validate:
        print("Warning: No artifacts configured for validation")
        return {"status": "SUCCEEDED", "metrics": {"validated": 0}}
    
    results = []
    
    for artifact_id in artifacts_to_validate:
        artifact = artifact_index.get(artifact_id)
        if not artifact:
            # Skip if artifact doesn't exist (might be optional)
            print(f"Skipping {artifact_id} (not found in artifact index)")
            continue
        
        artifact_path = Path(artifact["path"])
        
        if not artifact_path.exists():
            print(f"Skipping {artifact_id} (file does not exist: {artifact_path})")
            continue
        
        try:
            # 1. Parse JSON
            with open(artifact_path, 'r') as f:
                data = json.load(f)
            
            # 2. Must be object
            if not isinstance(data, dict):
                raise JSONValidationError(
                    f"Expected object/dict, got {type(data).__name__}"
                )
            
            # 3. Must have schema_version (if enforced)
            if enforce_schema_version and "schema_version" not in data:
                raise JSONValidationError(
                    "Missing required field: schema_version"
                )
            
            # 4. Must have generator_id or generated_by (if enforced)
            if enforce_generator_id:
                if "generator_id" not in data and "generated_by" not in data:
                    raise JSONValidationError(
                        "Missing required field: generator_id or generated_by"
                    )
            
            results.append({
                "artifact_id": artifact_id,
                "path": str(artifact_path),
                "status": "valid",
                "schema_version": data.get("schema_version"),
                "size_bytes": artifact_path.stat().st_size
            })
            
            print(f"✓ {artifact_id}: valid JSON (schema_version={data.get('schema_version')})")
            
        except json.JSONDecodeError as e:
            error_msg = (
                f"JSON validation failed for {artifact_id}\n"
                f"Artifact: {artifact_id}\n"
                f"Path: {artifact_path}\n"
                f"Error: Invalid JSON: {e}"
            )
            raise JSONValidationError(error_msg)
            
        except JSONValidationError as e:
            error_msg = (
                f"JSON validation failed for {artifact_id}\n"
                f"Artifact: {artifact_id}\n"
                f"Path: {artifact_path}\n"
                f"Error: {e}"
            )
            raise JSONValidationError(error_msg)
            
        except Exception as e:
            error_msg = (
                f"JSON validation failed for {artifact_id}\n"
                f"Artifact: {artifact_id}\n"
                f"Path: {artifact_path}\n"
                f"Error: Unexpected error: {e}"
            )
            raise JSONValidationError(error_msg)
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "validated": len(results),
            "artifacts": results
        }
    }
