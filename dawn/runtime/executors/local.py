import os
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from .base import Executor, RunResult
from ..orchestrator import Orchestrator

class LocalExecutor(Executor):
    def __init__(self, links_dir: str = "dawn/links", projects_dir: str = "projects", **kwargs):
        self.links_dir = links_dir
        self.projects_dir = projects_dir

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
        # Resolve pipeline path if only ID provided
        if not pipeline_path and pipeline_id:
            pipeline_path = f"dawn/pipelines/{pipeline_id}.yaml"
        
        if not pipeline_path:
            raise ValueError("Either pipeline_path or pipeline_id must be provided")

        orchestrator = Orchestrator(self.links_dir, self.projects_dir, profile=profile or isolation)
        project_root = Path(self.projects_dir) / project_id
        run_id = f"run_local_{int(time.time())}"
        run_dir = project_root / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        log_path = run_dir / "worker.log"
        errors = []
        status = "RUNNING"

        # Signal RUNNING immediately
        try:
            from ..project_index import update_project_index
            update_project_index(project_root, pipeline_meta={
                "id": pipeline_id,
                "path": pipeline_path,
                "profile": profile or isolation,
                "executor": "local"
            }, run_context={
                "status": status,
                "run_id": run_id,
                "worker_id": worker_id
            })
        except: pass

        import contextlib
        import sys

        try:
            with open(log_path, "w") as log_file:
                with contextlib.redirect_stdout(log_file), contextlib.redirect_stderr(log_file):
                    print(f"--- Starting Local Run: {run_id} ---")
                    print(f"Project: {project_id}, Pipeline: {pipeline_path}, Profile: {profile or isolation}")
                    orchestrator.run_pipeline(project_id, pipeline_path)
            status = "SUCCEEDED"
        except Exception as e:
            errors.append(str(e))
            status = "FAILED"
            with open(log_path, "a") as f:
                f.write(f"\nERROR: {e}\n")

        # Save run.json
        run_meta = {
            "run_id": run_id,
            "project_id": project_id,
            "pipeline_path": pipeline_path,
            "status": status,
            "profile": profile or isolation,
            "errors": errors,
            "ended_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        if metadata:
            run_meta["metadata"] = metadata
        with open(run_dir / "run.json", "w") as f:
            json.dump(run_meta, f, indent=2)

        # Update project index
        try:
            from ..project_index import update_project_index
            update_project_index(project_root, pipeline_meta={
                "id": pipeline_id,
                "path": pipeline_path,
                "profile": profile or isolation,
                "executor": "local"
            }, run_context={
                "status": status,
                "run_id": run_id,
                "worker_id": worker_id,
                "error": errors[0] if errors else None
            })
        except Exception as idx_err:
            print(f"Warning: Failed to update project index: {idx_err}")

        report_path = project_root / "artifacts/package.project_report/project_report.html"
        
        return RunResult(
            status=status,
            run_id=run_id,
            project_id=project_id,
            pipeline_ref=pipeline_path,
            errors={"errors": errors} if errors else None,
            report_path=str(report_path) if report_path.exists() else None
        )

    def get_status(self, project_id: str) -> dict:
        # Mock for now, could integrate with index reader later
        return {"status": "unknown"}

    def cancel(self, project_id: str) -> bool:
        return False # Stub
