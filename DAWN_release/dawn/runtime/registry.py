import os
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional

class Registry:
    def __init__(self, links_dir: str):
        self.links_dir = Path(links_dir)
        self.links: Dict[str, Dict[str, Any]] = {}

    def discover_links(self):
        self.links = {}
        if not self.links_dir.exists():
            return

        for link_path in self.links_dir.iterdir():
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
        return self.links.get(link_id)

    def list_links(self) -> List[str]:
        return list(self.links.keys())
