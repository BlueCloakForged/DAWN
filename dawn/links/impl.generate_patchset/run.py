"""
Patchset Generator Adapter

Calls local Agent Service to generate patchset + capabilities manifest.

Architecture:
  DAWN → this adapter → Agent Service (http://127.0.0.1:9411)
                            ↓
                      patchset.json
                      capabilities_manifest.json
"""

import json
import hashlib
import os
from pathlib import Path
import httpx


def run(context, config):
    """
    Generate patchset by calling Agent Service.
    
    Reads: dawn.requirements_map (primary)
    Calls: Agent Service HTTP API
    Produces: patchset.json, capabilities_manifest.json
    """
    artifact_index = context["artifact_index"]
    project_id = context["project_id"]
    
    # Get agent URL from config or env
    agent_url = config.get("agent_url") or os.getenv("DAWN_AGENT_URL", "http://127.0.0.1:9411")
    agent_timeout = config.get("agent_timeout", 120)
    
    # 1. Load requirements_map (primary input)
    req_map_artifact = artifact_index.get("dawn.requirements_map")
    if not req_map_artifact:
        raise FileNotFoundError("dawn.requirements_map artifact not found")
    
    with open(req_map_artifact["path"], 'r') as f:
        requirements_map = json.load(f)
    
    # 2. Optional: Load SRS for context
    srs_artifact = artifact_index.get("dawn.spec.srs")
    srs_markdown = None
    if srs_artifact:
        with open(srs_artifact["path"], 'r') as f:
            srs_markdown = f.read()
    
    # 3. Build agent request
    agent_request = {
        "schema_version": "1.0.0",
        "project_id": project_id,
        "pipeline_id": "app_mvp",
        "input": {
            "requirements_map": requirements_map,
            "srs_markdown": srs_markdown
        },
        "constraints": {
            "deterministic": True,
            "no_network": True,
            "max_files": 50,
            "max_total_bytes": 500000
        },
        "generation": {
            "model": config.get("agent_model", "rule-based-v1"),
            "temperature": 0.0,
            "seed": 1337
        }
    }
    
    # 4. Call agent service
    try:
        agent_response = call_agent_service(agent_request, agent_url, agent_timeout)
    except Exception as e:
        raise Exception(f"Agent service call failed: {e}")
    
    # 5. Validate response
    validate_agent_response(agent_response)
    
    # 6. Extract artifacts
    patchset = agent_response["patchset"]
    capabilities_manifest = agent_response["capabilities_manifest"]
    
    # 7. Canonicalize for determinism
    patchset = canonicalize_patchset(patchset)
    capabilities_manifest = canonicalize_manifest(capabilities_manifest)
    
    # 8. Write artifacts
    context["sandbox"].write_json("patchset.json", patchset)
    context["sandbox"].write_json("capabilities_manifest.json", capabilities_manifest)
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "patch_count": len(patchset),
            "agent_model": agent_response.get("generator", {}).get("model", "unknown")
        }
    }


def call_agent_service(request_data, agent_url, timeout=120):
    """Call agent service with timeout and error handling"""
    try:
        response = httpx.post(
            f"{agent_url}/v1/patchset:generate",
            json=request_data,
            timeout=httpx.Timeout(connect=2.0, read=timeout)
        )
        response.raise_for_status()
        return response.json()
    except httpx.TimeoutException as e:
        raise Exception(f"Agent service timeout after {timeout}s")
    except httpx.HTTPStatusError as e:
        body_preview = e.response.text[:200] if e.response.text else "no body"
        raise Exception(
            f"Agent service error: {e.response.status_code}\n"
            f"URL: {agent_url}/v1/patchset:generate\n"
            f"Response: {body_preview}"
        )
    except httpx.ConnectError as e:
        raise Exception(
            f"Cannot connect to agent service at {agent_url}\n"
            f"Is the service running? Try: uvicorn service:app --host 127.0.0.1 --port 9411"
        )
    except Exception as e:
        raise Exception(f"Agent service call failed: {e}")


def validate_agent_response(response):
    """Validate agent response before writing artifacts"""
    # 1. Must be dict
    if not isinstance(response, dict):
        raise ValueError("Agent response must be dict")
    
    # 2. Must have required fields
    required = ["schema_version", "patchset", "capabilities_manifest"]
    for field in required:
        if field not in response:
            raise ValueError(f"Missing required field: {field}")
    
    # 3. Validate patchset
    patchset = response["patchset"]
    if not isinstance(patchset, dict):
        raise ValueError("Patchset must be dict")
    
    if len(patchset) == 0:
        raise ValueError("Patchset must contain at least one file")
    
    for path, patch in patchset.items():
        # Path safety
        if path.startswith("/"):
            raise ValueError(f"Absolute path not allowed: {path}")
        if ".." in path:
            raise ValueError(f"Path traversal not allowed: {path}")
        if "\\" in path or "\0" in path:
            raise ValueError(f"Invalid characters in path: {path}")
        
        # Must have content and sha256
        if not isinstance(patch, dict):
            raise ValueError(f"Patch must be dict: {path}")
        if "content" not in patch:
            raise ValueError(f"Patch missing content: {path}")
        if "sha256" not in patch:
            raise ValueError(f"Patch missing sha256: {path}")
        
        # Verify SHA256
        content = patch["content"]
        if not isinstance(content, str):
            raise ValueError(f"Content must be string: {path}")
        
        computed = hashlib.sha256(content.encode()).hexdigest()
        provided = patch["sha256"]
        if computed != provided:
            raise ValueError(
                f"SHA256 mismatch for {path}\n"
                f"Computed: {computed}\n"
                f"Provided: {provided}"
            )
    
    # 4. Validate capabilities manifest
    manifest = response["capabilities_manifest"]
    if not isinstance(manifest, dict):
        raise ValueError("Capabilities manifest must be dict")
    
    if "schema_version" not in manifest:
        raise ValueError("Capabilities manifest missing schema_version")
    
    # Trust boundary: must NOT claim "tested"
    capabilities = manifest.get("capabilities", {})
    forbidden_keys = ["examples_tested", "tests_passed", "verified"]
    for key in forbidden_keys:
        if key in capabilities:
            raise ValueError(
                f"Trust boundary violation: capabilities.{key} not allowed\n"
                f"Capabilities can only declare what's implemented, not what's tested"
            )
    
    return True


def canonicalize_patchset(patchset):
    """Canonicalize patchset for determinism"""
    # Sort keys
    sorted_patchset = {}
    for path in sorted(patchset.keys()):
        patch = patchset[path]
        # Normalize newlines
        content = patch["content"].replace("\r\n", "\n").replace("\r", "\n")
        sorted_patchset[path] = {
            "content": content,
            "sha256": hashlib.sha256(content.encode()).hexdigest()
        }
    
    return sorted_patchset


def canonicalize_manifest(manifest):
    """Canonicalize capabilities manifest for determinism"""
    # Sort operator lists
    if "capabilities" in manifest:
        caps = manifest["capabilities"]
        if "operators_supported" in caps:
            caps["operators_supported"] = sorted(caps["operators_supported"])
        if "syntax_supported" in caps:
            caps["syntax_supported"] = sorted(caps["syntax_supported"])
        if "constraints" in caps:
            caps["constraints"] = sorted(caps["constraints"])
    
    return manifest
