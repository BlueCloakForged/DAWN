from dataclasses import dataclass
from typing import Protocol, Optional, Dict, Any

@dataclass
class RunResult:
    status: str  # SUCCEEDED, FAILED, SKIPPED
    run_id: str
    project_id: str
    pipeline_ref: str
    errors: Optional[Dict[str, Any]] = None
    report_path: Optional[str] = None

class Executor(Protocol):
    def run_pipeline(
        self,
        project_id: str,
        pipeline_path: Optional[str] = None,
        pipeline_id: Optional[str] = None,
        profile: Optional[str] = None,
        worker_id: Optional[str] = None,
        isolation: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> RunResult:
        ...

    def get_status(self, project_id: str) -> dict:
        ...

    def cancel(self, project_id: str) -> bool:
        ...
