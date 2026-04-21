"""Discovers and indexes link metadata from link.yaml files across one or more links directories."""
import os
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional

class Registry:
    def __init__(self, links_dirs: List[str]):
        """ init ."""
        self.links_dirs = [Path(d) for d in links_dirs]
        self.links: Dict[str, Dict[str, Any]] = {}

    def discover_links(self):
        """Discover links."""
        self.links = {}
        for d in self.links_dirs:
            if not d.exists():
                continue

            for link_path in d.iterdir():
                if link_path.is_dir():
                    link_yaml = link_path / "link.yaml"
                    if link_yaml.exists():
                        with open(link_yaml, "r") as f:
                            metadata = yaml.safe_load(f)
                            link_id = metadata.get("metadata", {}).get("name")
                            if link_id:
                                self.links[link_id] = {
                                    "path": str(link_path),
                                    "metadata": metadata
                                }

    def get_link(self, link_id: str) -> Optional[Dict[str, Any]]:
        """Get link."""
        return self.links.get(link_id)

    def list_links(self) -> List[str]:
        """List links."""
        return list(self.links.keys())
