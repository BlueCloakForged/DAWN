import os
import hashlib
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

class ArtifactStore:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.artifacts_dir = self.project_root / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        
        self.shadow_dir = self.project_root / "shadow_artifacts"
        self.shadow_dir.mkdir(parents=True, exist_ok=True)
        
        # Artifact registries: artifact_id -> {path, schema, producer_link_id, ...}
        self._registry: Dict[str, Dict[str, Any]] = {}
        self._shadow_registry: Dict[str, Dict[str, Any]] = {}

        # Global persistent artifacts (shared across projects)
        # Assuming DAWN root is parents[1] of projects/
        self.global_artifacts_dir = self.project_root.parent.parent / "artifacts"
        self.global_artifacts_dir.mkdir(parents=True, exist_ok=True)

    def get_global_path(self, artifact_name: str) -> Path:
        """Get the path for a global persistent artifact."""
        return self.global_artifacts_dir / artifact_name

    def read_global_artifact(self, artifact_name: str) -> Optional[Any]:
        """Read a global artifact, checking project-local override first."""
        # 1. Check project-local override (for isolated testing/overrides)
        local_path = self.project_root / artifact_name
        # 2. Check central global store
        global_path = self.get_global_path(artifact_name)
        
        path = local_path if local_path.exists() else global_path
        
        if not path.exists():
            return None
        with open(path, "r") as f:
            if path.suffix == ".json":
                return json.load(f)
            return f.read()

    def update_global_vector(self, artifact_name: str, updates: Dict[str, float]):
        """Atomic-ish update for a global vector artifact, respecting local override."""
        local_path = self.project_root / artifact_name
        global_path = self.get_global_path(artifact_name)
        
        # If local exists, we update that instead of the central one
        path = local_path if local_path.exists() else global_path
        
        data = self.read_global_artifact(artifact_name) or {"vector": {}}
        
        if "vector" not in data:
            data["vector"] = {}
            
        for key, delta in updates.items():
            current = data["vector"].get(key, 0.0)
            data["vector"][key] = current + delta
            
        with open(path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)

    def register(self, artifact_id: str, abs_path: str, schema: Optional[str] = None,
                 producer_link_id: Optional[str] = None, blob_uri: Optional[str] = None,
                 is_shadow: bool = False):
        """Register an artifact in the runtime registry."""
        record = {
            "path": abs_path,
            "schema": schema,
            "producer_link_id": producer_link_id,
            "blob_uri": blob_uri,
            "digest": self.get_digest(Path(abs_path)) if Path(abs_path).exists() else None,
            "is_shadow": is_shadow
        }
        
        if is_shadow:
            self._shadow_registry[artifact_id] = record
        else:
            self._registry[artifact_id] = record
    
    def get(self, artifact_id: str, include_shadow: bool = False) -> Optional[Dict[str, Any]]:
        """Get artifact metadata from registry."""
        if include_shadow and artifact_id in self._shadow_registry:
            return self._shadow_registry[artifact_id]
        return self._registry.get(artifact_id)
    
    def list_artifacts(self) -> List[str]:
        """List all registered artifact IDs."""
        return list(self._registry.keys())

    def get_link_dir(self, link_id: str, is_shadow: bool = False) -> Path:
        base = self.shadow_dir if is_shadow else self.artifacts_dir
        link_dir = base / link_id
        link_dir.mkdir(parents=True, exist_ok=True)
        return link_dir

    def write_artifact(self, link_id: str, filename: str, content: Any, mode: str = "w") -> Path:
        link_dir = self.get_link_dir(link_id)
        file_path = link_dir / filename
        
        if isinstance(content, (bytes, bytearray)):
            with open(file_path, "wb") as f:
                f.write(content)
        elif isinstance(content, (dict, list)):
            with open(file_path, "w") as f:
                json.dump(content, f, indent=2, sort_keys=True)
        else:
            with open(file_path, mode) as f:
                f.write(str(content))
        
        return file_path

    def read_artifact(self, link_id: str, filename: str) -> Optional[Any]:
        """Read a project-specific artifact."""
        link_dir = self.get_link_dir(link_id)
        path = link_dir / filename
        if not path.exists():
            return None
        with open(path, "r") as f:
            if path.suffix == ".json":
                return json.load(f)
            return f.read()

    def get_digest(self, file_path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def list_artifacts_for_link(self, link_id: str) -> List[Path]:
        link_dir = self.artifacts_dir / link_id
        if not link_dir.exists():
            return []
        return [p for p in link_dir.iterdir() if p.is_file()]

    def save_manifest(self, link_id: str, is_shadow: bool = False):
        """
        Save artifact registry manifest for this link.
        """
        registry = self._shadow_registry if is_shadow else self._registry
        link_artifacts = {
            artifact_id: meta 
            for artifact_id, meta in registry.items()
            if meta.get("producer_link_id") == link_id
        }
        
        base = self.shadow_dir if is_shadow else self.artifacts_dir
        manifest_filename = ".shadow_artifacts.json" if is_shadow else ".dawn_artifacts.json"
        manifest_path = base / link_id / manifest_filename
        
        with open(manifest_path, "w") as f:
            json.dump(link_artifacts, f, indent=2, sort_keys=True)

    def rehydrate_from_link_dir(self, link_id: str, is_shadow: bool = False) -> int:
        """
        Rehydrate artifact registry from link's manifest.
        
        Reads .dawn_artifacts.json (or .shadow_artifacts.json) and re-registers all artifacts.
        Returns number of artifacts rehydrated.
        """
        base = self.shadow_dir if is_shadow else self.artifacts_dir
        manifest_filename = ".shadow_artifacts.json" if is_shadow else ".dawn_artifacts.json"
        manifest_path = base / link_id / manifest_filename
        
        if not manifest_path.exists():
            return 0
        
        with open(manifest_path, "r") as f:
            link_artifacts = json.load(f)
        
        count = 0
        for artifact_id, meta in link_artifacts.items():
            # Verify file still exists
            if Path(meta["path"]).exists():
                if is_shadow:
                    self._shadow_registry[artifact_id] = meta
                else:
                    self._registry[artifact_id] = meta
                count += 1
        
        return count

