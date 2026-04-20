import os
import json
import shutil
from pathlib import Path
from typing import Any, Optional

class Sandbox:
    def __init__(self, project_root: str, link_id: str, is_shadow: bool = False):
        self.project_root = Path(project_root)
        self.link_id = link_id
        self.is_shadow = is_shadow
        
        base = self.project_root / "shadow_artifacts" if is_shadow else self.project_root / "artifacts"
        self.sandbox_root = base / link_id
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        
        # Injected by orchestrator
        self.artifact_store = None

    def write_json(self, path: str, obj: Any):
        """Write a JSON object to the sandbox."""
        full_path = self.sandbox_root / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "w") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
        return str(full_path)

    def write_text(self, path: str, content: str):
        """Write text content to the sandbox."""
        full_path = self.sandbox_root / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)
        return str(full_path)

    def copy_in(self, src: str, dest: str):
        """Copy an external file into the sandbox."""
        src_path = Path(src)
        dest_path = self.sandbox_root / dest
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)
        return str(dest_path)

    def publish(self, artifact: str, filename: str, obj: Any, schema: str = "json", blob_uri: Optional[str] = None):
        """
        Publish an artifact and register it in the artifact store.
        
        Args:
            artifact: Artifact ID (e.g., "dawn.project.bundle")
            filename: Filename to write (e.g., "bundle.json")
            obj: JSON-serializable object
            schema: Schema type hint
            blob_uri: Optional external storage URI
        """
        path = self.write_json(filename, obj)
        if self.artifact_store:
            self.artifact_store.register(
                artifact_id=artifact,
                abs_path=str(Path(path).absolute()),
                schema=schema,
                producer_link_id=self.link_id,
                blob_uri=blob_uri,
                is_shadow=self.is_shadow
            )
        return path

    def publish_text(self, artifact: str, filename: str, text: str, schema: str = "text", blob_uri: Optional[str] = None):
        """Publish text artifact and register."""
        path = self.write_text(filename, text)
        if self.artifact_store:
            self.artifact_store.register(
                artifact_id=artifact,
                abs_path=str(Path(path).absolute()),
                schema=schema,
                producer_link_id=self.link_id,
                blob_uri=blob_uri,
                is_shadow=self.is_shadow
            )
        return path

