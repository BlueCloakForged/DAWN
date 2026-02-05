"""
Project Bundle Registration Link

Registers human input bundle as a first-class DAWN artifact.

Purpose:
  - Make inputs/ an explicit artifact dependency (not convention)
  - Enable deterministic bundle hashing
  - Create self-contained pipeline runs

Produces:
  - dawn.project.bundle (JSON manifest): Deterministic file list + hash

Determinism:
  - Sorted file list
  - Canonical JSON (sorted keys)
  - No timestamps
  - Bundle hash from manifest content (not filesystem order)
"""

import json
import hashlib
import fnmatch
from pathlib import Path
from typing import List, Dict, Any


def run(context, config):
    """
    Generate deterministic bundle manifest from inputs directory.
    
    Excludes control-plane files (HITL templates, manifests) to ensure
    bundle digest only reflects user-provided data-plane inputs.
    """
    project_root = Path(context["project_root"])
    inputs_dir = project_root / "inputs"
    
    if not inputs_dir.exists():
        raise FileNotFoundError(f"Inputs directory not found: {inputs_dir}")
    
    # Default exclude patterns (control-plane files)
    default_excludes = [
        "hitl_*.json",      # HITL templates/approvals
        ".dawn_*",          # DAWN manifests
        ".DS_Store",        # macOS
        "Thumbs.db",        # Windows
        "._*",              # macOS metadata
        "*.tmp",            # Temp files
        "*.swp",            # Editor swap files
    ]
    
    # Allow config to extend excludes
    config_excludes = config.get("exclude_globs", [])
    all_excludes = default_excludes + config_excludes
    
    # Collect files (data-plane only)
    files = []
    excluded = []
    
    for file_path in sorted(inputs_dir.rglob("*")):
        if not file_path.is_file():
            continue
        
        # Relative POSIX path
        rel_path = file_path.relative_to(inputs_dir).as_posix()
        
        # Check exclusions
        should_exclude = False
        for pattern in all_excludes:
            if fnmatch.fnmatch(file_path.name, pattern) or fnmatch.fnmatch(rel_path, pattern):
                should_exclude = True
                excluded.append(rel_path)
                break
        
        if should_exclude:
            continue
        
        # Read file bytes (no stat info, no timestamps)
        file_bytes = file_path.read_bytes()
        file_sha256 = hashlib.sha256(file_bytes).hexdigest()
        
        files.append({
            "path": rel_path,
            "uri": (project_root / "inputs" / rel_path).absolute().as_uri(),
            "bytes": len(file_bytes),
            "sha256": file_sha256
        })
    
    # Sort by path for determinism
    files.sort(key=lambda f: f["path"])
    
    # Phase 2.2: Meta-Bundle (Context Binding)
    meta_bundle = context.get("ephemeral_input", {})
    
    # Compute bundle_sha256 from canonical representation
    # Format: path:sha256:bytes\n for each file + meta_bundle JSON
    canonical_parts = [f"{f['path']}:{f['sha256']}:{f['bytes']}" for f in files]
    
    # Include Meta-Bundle in the canonical string to force hash change on context shift
    meta_json = json.dumps(meta_bundle, sort_keys=True)
    canonical_parts.append(f"meta:{hashlib.sha256(meta_json.encode()).hexdigest()}")
    
    canonical_str = "\n".join(canonical_parts)
    bundle_sha256 = hashlib.sha256(canonical_str.encode()).hexdigest()
    
    # Build deterministic manifest
    manifest = {
        "schema_version": "1.1.0",
        "bundle_sha256": bundle_sha256,
        "root": "inputs",
        "files": files,
        "meta_bundle": meta_bundle
    }
    
    # Debug logging
    print(f"[Bundle] Included files: {len(files)}")
    if excluded:
        print(f"[Bundle] Excluded files: {excluded}")
    
    # Publish with deterministic JSON
    sandbox = context["sandbox"]
    sandbox.publish(
        artifact="dawn.project.bundle",
        filename="dawn.project.bundle.json",
        obj=manifest,
        schema="json"
    )
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "files_bundled": len(files),
            "bundle_sha256": bundle_sha256
        }
    }


def discover_files(inputs_dir: Path) -> List[Dict[str, Any]]:
    """
    Discover all files in inputs directory.
    
    Returns deterministic list (sorted by path).
    """
    files = []
    
    for path in sorted(inputs_dir.rglob("*")):  # Sorted for determinism
        if path.is_file():
            # Compute file hash
            with open(path, "rb") as f:
                content = f.read()
                file_hash = hashlib.sha256(content).hexdigest()
            
            # Relative path from inputs dir (normalized)
            rel_path = path.relative_to(inputs_dir.parent)
            
            files.append({
                "path": str(rel_path).replace("\\", "/"),  # Normalize separators
                "sha256": file_hash,
                "bytes": len(content)
            })
    
    return files


def build_manifest(files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build deterministic manifest with bundle hash.
    
    Bundle hash is computed from canonical file list.
    """
    # Compute bundle hash from sorted, canonical file list
    # Format: path:sha256\npath:sha256\n...
    canonical_lines = [f"{f['path']}:{f['sha256']}" for f in files]
    canonical_content = "\n".join(canonical_lines) + "\n"
    bundle_sha256 = hashlib.sha256(canonical_content.encode()).hexdigest()
    
    return {
        "schema_version": "1.0.0",
        "bundle_sha256": bundle_sha256,
        "root": "inputs",
        "files": files  # Already sorted from discover_files
    }

