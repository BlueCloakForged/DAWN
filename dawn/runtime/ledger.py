import json
import time
from pathlib import Path
from typing import Dict, Any, Optional

class Ledger:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.ledger_dir = self.project_root / "ledger"
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.ledger_dir / "events.jsonl"

    def log_event(self, 
                  project_id: str, 
                  pipeline_id: str, 
                  link_id: str, 
                  run_id: str, 
                  step_id: str, 
                  status: str, 
                  inputs: Optional[Dict[str, Any]] = None, 
                  outputs: Optional[Dict[str, Any]] = None, 
                  metrics: Optional[Dict[str, Any]] = None, 
                  errors: Optional[Dict[str, Any]] = None,
                  policy_versions: Optional[Dict[str, Any]] = None,
                  drift_score: Optional[float] = None,
                  drift_metadata: Optional[Dict[str, Any]] = None):
        
        event = {
            "timestamp": time.time(),
            "project_id": project_id,
            "pipeline_id": pipeline_id,
            "link_id": link_id,
            "run_id": run_id,
            "step_id": step_id,
            "status": status,
            "inputs": inputs if inputs is not None else {},
            "outputs": outputs if outputs is not None else {},
            "metrics": metrics if metrics is not None else {},
            "errors": errors if errors is not None else {},
            "policy_versions": policy_versions if policy_versions is not None else {},
            "drift_score": drift_score,
            "drift_metadata": drift_metadata if drift_metadata is not None else {}
        }
        
        with open(self.events_file, "a") as f:
            f.write(json.dumps(event) + "\n")

    def get_events(self, link_id: Optional[str] = None) -> list:
        events = []
        if not self.events_file.exists():
            return events
            
        with open(self.events_file, "r") as f:
            for line in f:
                event = json.loads(line)
                if link_id is None or event["link_id"] == link_id:
                    events.append(event)
        return events
