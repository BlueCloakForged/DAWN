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
        
        # Artifact registry: artifact_id -> {path, schema, producer_link_id, ...}
        self._registry: Dict[str, Dict[str, Any]] = {}

    def register(self, artifact_id: str, abs_path: str, schema: Optional[str] = None,
                 producer_link_id: Optional[str] = None):
        """Register an artifact in the runtime registry."""
        self._registry[artifact_id] = {
            "path": abs_path,
            "schema": schema,
            "producer_link_id": producer_link_id,
            "digest": self.get_digest(Path(abs_path)) if Path(abs_path).exists() else None
        }
    
    def get(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        """Get artifact metadata from registry."""
        return self._registry.get(artifact_id)
    
    def list_artifacts(self) -> List[str]:
        """List all registered artifact IDs."""
        return list(self._registry.keys())

    def get_link_dir(self, link_id: str) -> Path:
        link_dir = self.artifacts_dir / link_id
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

    def save_manifest(self, link_id: str):
        """
        Save artifact registry manifest for this link.
        
        Creates .dawn_artifacts.json with all registered artifacts for this link.
        """
        link_artifacts = {
            artifact_id: meta 
            for artifact_id, meta in self._registry.items()
            if meta.get("producer_link_id") == link_id
        }
        
        manifest_path = self.artifacts_dir / link_id / ".dawn_artifacts.json"
        with open(manifest_path, "w") as f:
            json.dump(link_artifacts, f, indent=2, sort_keys=True)

    def rehydrate_from_link_dir(self, link_id: str) -> int:
        """
        Rehydrate artifact registry from link's manifest.
        
        Reads .dawn_artifacts.json and re-registers all artifacts.
        Returns number of artifacts rehydrated.
        """
        manifest_path = self.artifacts_dir / link_id / ".dawn_artifacts.json"
        
        if not manifest_path.exists():
            return 0
        
        with open(manifest_path, "r") as f:
            link_artifacts = json.load(f)
        
        count = 0
        for artifact_id, meta in link_artifacts.items():
            # Verify file still exists
            if Path(meta["path"]).exists():
                self._registry[artifact_id] = meta
                count += 1
        
        return count

