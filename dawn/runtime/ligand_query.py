"""Interface for querying LIGAND modulation pool state, decoupled from any specific agent."""
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

class LigandQueryInterface:
    """
    Generic interface for querying LIGAND modulation state.
    Decouples the framework from agents like SAM.
    """
    def __init__(self, pool_path: str = None):
        """ init ."""
        if pool_path is None:
            # Default to artifacts/ligand.pool.json relative to DAWN root
            dawn_root = os.environ.get("DAWN_ROOT", str(Path(__file__).resolve().parent.parent.parent))
            pool_path = os.path.join(dawn_root, "artifacts", "ligand.pool.json")
        self.pool_path = Path(pool_path)

    def get_current_state(self) -> Dict[str, Any]:
        """Returns the complete current modulation pool."""
        if not self.pool_path.exists():
            return {"error": "Pool not found", "vector": {}}
        
        try:
            with open(self.pool_path, "r") as f:
                return json.load(f)
        except Exception as e:
            return {"error": str(e), "vector": {}}

    def get_vector(self) -> Dict[str, float]:
        """Returns only the modulation vector."""
        state = self.get_current_state()
        return state.get("vector", {})

def get_ligand_status() -> Dict[str, float]:
    """Helper function for quick status checks."""
    return LigandQueryInterface().get_vector()
