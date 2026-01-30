import subprocess
import os
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any
from .base import Executor, RunResult

class SubprocessExecutor(Executor):
    def __init__(self, projects_dir: str = "projects", **kwargs):
        self.projects_dir = Path(projects_dir)

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

        project_root = self.projects_dir / project_id
        run_id = f"run_sub_{int(time.time())}"
        run_dir = project_root / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        log_path = run_dir / "worker.log"

        cmd = [
            "python3", "-m", "dawn.runtime.main",
            "--project", project_id,
            "--pipeline", pipeline_path
        ]
        
        effective_profile = profile or isolation
        if effective_profile:
            cmd.extend(["--profile", effective_profile])

        # Signal RUNNING immediately
        try:
            from ..project_index import update_project_index
            update_project_index(project_root, pipeline_meta={
                "id": pipeline_id,
                "path": pipeline_path,
                "profile": effective_profile,
                "executor": "subprocess"
            }, run_context={
                "status": "RUNNING",
                "run_id": run_id,
                "worker_id": worker_id
            })
        except: pass

        try:
            with open(log_path, "w") as log_file:
                process = subprocess.Popen(
                    cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, "PYTHONPATH": ".", "PYTHONUNBUFFERED": "1"}
                )
                process.wait()

            status = "SUCCEEDED" if process.returncode == 0 else "FAILED"
            
            # Save run.json
            run_meta = {
                "run_id": run_id,
                "project_id": project_id,
                "pipeline_path": pipeline_path,
                "status": status,
                "profile": effective_profile,
                "exit_code": process.returncode,
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
                    "profile": effective_profile,
                    "executor": "subprocess"
                }, run_context={
                    "status": status,
                    "run_id": run_id,
                    "worker_id": worker_id,
                    "error": f"Exit code: {process.returncode}" if status == "FAILED" else None
                })
            except: pass

            report_path = str(project_root / "artifacts/package.project_report/project_report.html")
            
            return RunResult(
                status=status,
                run_id=run_id,
                project_id=project_id,
                pipeline_ref=pipeline_path,
                report_path=report_path if os.path.exists(report_path) else None,
                errors={"exit_code": process.returncode} if status == "FAILED" else None
            )
        except Exception as e:
            return RunResult(
                status="FAILED",
                run_id=run_id,
                project_id=project_id,
                pipeline_ref=pipeline_path,
                errors={"message": str(e)}
            )

    def get_status(self, project_id: str) -> dict:
        return {"status": "unknown"}

    def cancel(self, project_id: str) -> bool:
        return False # Stub
