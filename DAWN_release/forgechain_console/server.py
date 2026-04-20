import os
import sys
import json
import time
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Body, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import asyncio

# Import Core DAWN schemas
try:
    from .schemas import (
        ErrorResponse, ErrorDetail, create_error_response, create_conflict_response,
        ProjectCreate, ProjectRun, ProjectSummary,
        GatesResponse, GateStatus, GateApprovalRequest, GateApprovalResponse,
        HealingReport, HealingIteration
    )
except ImportError:
    from schemas import (
        ErrorResponse, ErrorDetail, create_error_response, create_conflict_response,
        ProjectCreate, ProjectRun, ProjectSummary,
        GatesResponse, GateStatus, GateApprovalRequest, GateApprovalResponse,
        HealingReport, HealingIteration
    )

# Try to import ForgeChain modules directly
try:
    from dawn.runtime.pipelines import describe_pipeline, MANIFEST_PATH
    from dawn.runtime.agent import get_project_status
    from dawn.runtime.new import bootstrap_project
    from dawn.runtime.executors import get_executor
    DIRECT_IMPORTS = True
except ImportError:
    DIRECT_IMPORTS = False
    # Define fallback for MANIFEST_PATH when imports fail
    # Server runs from forgechain_console, so we need to go up one level
    MANIFEST_PATH = "../dawn/pipelines/pipeline_manifest.json"

app = FastAPI(title="ForgeChain Operator Console")

# Project/Run state tracking
# {project_id: {"run_id": str, "started_at": float, "executor": str, "pipeline": str}}
active_runs: Dict[str, Dict[str, Any]] = {}

# Constants
# When running from forgechain_console, we need to go up one level
BASE_DIR = Path(os.getcwd())
if BASE_DIR.name == "forgechain_console":
    BASE_DIR = BASE_DIR.parent
PROJECTS_DIR = BASE_DIR / "projects"
LINKS_DIR = BASE_DIR / "dawn" / "links"
PORT = 3434

def get_project_index(project_id: str) -> Optional[Dict[str, Any]]:
    index_path = PROJECTS_DIR / project_id / "project_index.json"
    if index_path.exists():
        with open(index_path, "r") as f:
            try:
                return json.load(f)
            except:
                return None
    return None

# Ensure static directory exists
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# --- API Routes ---

@app.get("/api/pipelines")
async def get_pipelines():
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r") as f:
            return json.load(f)
    return []

@app.get("/api/pipelines/{pipeline_id}")
async def get_pipeline_details(pipeline_id: str):
    if DIRECT_IMPORTS:
        details = describe_pipeline(pipeline_id)
        if details:
            return details
    
    # Fallback to manual manifest read
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r") as f:
            manifest = json.load(f)
            entry = next((p for p in manifest if p["id"] == pipeline_id), None)
            if entry:
                return entry
    
    raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")

@app.post("/api/projects")
async def create_project(data: ProjectCreate):
    # Check if project already exists (409 Conflict)
    project_dir = PROJECTS_DIR / data.project_id
    if project_dir.exists():
        existing_index = get_project_index(data.project_id)
        if existing_index:
            metadata = existing_index.get("metadata", {})
            status = existing_index.get("status", {}).get("current", "UNKNOWN")
            
            error_response = create_error_response(
                code="PROJECT_EXISTS",
                message=f"Project '{data.project_id}' already exists",
                category="conflict",
                user_action_required=True,
                suggestions=[
                    f"Update existing: POST /api/projects/{data.project_id}/inputs",
                    f"Create new: Use different project_id (e.g., {data.project_id}_v2)"
                ]
            )
            
            # Convert to dict and add existing_project info
            response_data = error_response.model_dump()
            response_data["error"]["existing_project"] = {
                "project_id": data.project_id,
                "status": status,
                "created_at": metadata.get("created_at", "unknown")
            }
            
            return JSONResponse(
                status_code=409,
                content=response_data
            )
    
    if DIRECT_IMPORTS:
        success = bootstrap_project(data.project_id, data.pipeline_id, data.profile, str(PROJECTS_DIR), metadata=data.metadata)
        if not success:
            raise HTTPException(status_code=400, detail="Project creation failed. Directory might already exist.")
    else:
        # Fallback to subprocess
        # Use the venv's Python explicitly (sys.executable might point to wrong Python)
        parent_dir = str(BASE_DIR)
        venv_python = str(BASE_DIR / ".venv" / "bin" / "python3")
        
        # Fall back to sys.executable if venv not found
        python_exec = venv_python if Path(venv_python).exists() else sys.executable
        
        cmd = [
            python_exec, "-m", "dawn.runtime.new",
            "--project", data.project_id,
            "--pipeline-id", data.pipeline_id,
            "--profile", data.profile
        ]
        if data.metadata:
            # Pass metadata as JSON string if using subprocess
            cmd.extend(["--metadata", json.dumps(data.metadata)])
        
        # Run from parent directory and set PYTHONPATH to parent directory
        env = {**os.environ, "PYTHONPATH": parent_dir}
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=parent_dir)
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail=result.stderr or result.stdout)
    
    # Load and return the project index
    index = get_project_index(data.project_id)
    if not index:
        raise HTTPException(status_code=500, detail="Project created but index not found")
    
    return {
        "status": "success",
        "data": {
            "project_id": data.project_id,
            "index": index
        }
    }

@app.get("/api/projects")
async def list_projects():
    """
    List all projects with status information.
    Enhanced with standardized project metadata fields.
    """
    if not PROJECTS_DIR.exists():
        return {"projects": []}
    
    projects = []
    for p_dir in PROJECTS_DIR.iterdir():
        if p_dir.is_dir() and not p_dir.name.startswith("."):
            index = get_project_index(p_dir.name)
            if index:
                metadata = index.get("metadata", {})
                status_info = index.get("status", {})
                
                # Check if project is gate-blocked
                approvals = index.get("approvals", {})
                gate_blocked = approvals.get("gate_blocked", False)
                
                projects.append({
                    "project_id": p_dir.name,  # Standardize on "project_id" for programmatic parity
                    "status": status_info.get("current", "UNKNOWN"),
                    "pipeline_id": index.get("pipeline", {}).get("id"),
                    "created_at": metadata.get("created_at"),
                    "last_modified": metadata.get("last_modified") or index.get("last_updated_at"),
                    "gate_blocked": gate_blocked,
                    "is_running": p_dir.name in active_runs
                })
            else:
                # Still show project but with limited info if index missing
                projects.append({
                    "project_id": p_dir.name,
                    "status": "UNINDEXED",
                    "is_running": p_dir.name in active_runs,
                    "gate_blocked": False
                })
    
    return {"projects": projects}

@app.get("/api/projects/{project_id}")
async def get_project_details(project_id: str):
    index = get_project_index(project_id)
    if not index:
        # Try to generate it if missing? Or just 404
        raise HTTPException(status_code=404, detail=f"Project {project_id} index not found")
    
    index["is_running"] = project_id in active_runs
    if project_id in active_runs:
        index["active_run"] = active_runs[project_id]
    
    return index

@app.get("/api/projects/{project_id}/gates")
async def get_project_gates(project_id: str):
    """
    Get gate status for a project.
    Returns active gate blocks and approval status.
    """
    index = get_project_index(project_id)
    if not index:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    gates = []
    blocked = False
    
    # Check approvals section
    approvals = index.get("approvals", {})
    history = approvals.get("history", [])
    
    # Check if project has any gate blocks
    # Gate blocks are typically indicated in the approvals section
    # For now, we'll check for common gate IDs
    project_dir = PROJECTS_DIR / project_id
    
    # Check for hitl.gate approval status
    hitl_gate_file = project_dir / "approvals" / "hitl.gate.approved"
    
    gate_status = "APPROVED" if hitl_gate_file.exists() else "BLOCKED"
    
    if gate_status == "BLOCKED":
        blocked = True
        gates.append({
            "gate_id": "hitl.gate",
            "status": "BLOCKED",
            "reason": "First-time approval required for pipeline execution",
            "approval_options": {
                "approve": f"/api/projects/{project_id}/gates/hitl.gate/approve",
                "reject": None,
                "skip": f"/api/projects/{project_id}/gates/hitl.gate/approve"
            },
            "artifacts_to_review": ["dawn.project.ir", "dawn.cro.json"]
        })
    else:
        # Check approval history for details
        for approval in history:
            if approval.get("gate_id") == "hitl.gate":
                gates.append({
                    "gate_id": "hitl.gate",
                    "status": "APPROVED",
                    "approved_at": approval.get("approved_at"),
                    "approved_by": approval.get("approved_by", "api_client"),
                    "reason": None
                })
                break
    
    return GatesResponse(gates=gates, blocked=blocked).model_dump()

@app.post("/api/projects/{project_id}/gates/{gate_id}/approve")
async def approve_gate(project_id: str, gate_id: str, data: GateApprovalRequest):
    """
    Approve a gate via API.
    Creates approval marker file and updates project index.
    """
    # Validate project exists
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    # Security: Validate gate_id to prevent path traversal
    if ".." in gate_id or "/" in gate_id or "\\" in gate_id:
        raise HTTPException(status_code=400, detail="Invalid gate_id")
    
    # Create approvals directory
    approvals_dir = project_dir / "approvals"
    approvals_dir.mkdir(parents=True, exist_ok=True)
    
    # Create approval marker file
    approval_file = approvals_dir / f"{gate_id}.approved"
    
    approval_data = {
        "approved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "approved_by": "sam_api",
        "mode": data.mode,
        "artifacts_reviewed": data.artifacts_reviewed or [],
        "reason": data.reason or "API approval"
    }
    
    with open(approval_file, 'w') as f:
        json.dump(approval_data, f, indent=2)
    
    # Update project index approvals history
    index = get_project_index(project_id)
    if index:
        if "approvals" not in index:
            index["approvals"] = {"history": []}
        if "history" not in index["approvals"]:
            index["approvals"]["history"] = []
        
        index["approvals"]["history"].append({
            "gate_id": gate_id,
            "approved_at": approval_data["approved_at"],
            "approved_by": approval_data["approved_by"],
            "mode": data.mode
        })
        
        # Mark as not gate-blocked
        index["approvals"]["gate_blocked"] = False
        
        # Write updated index
        index_path = project_dir / "project_index.json"
        with open(index_path, 'w') as f:
            json.dump(index, f, indent=2)
    
    return GateApprovalResponse(
        success=True,
        gate_id=gate_id,
        status="approved",
        message=f"Gate {gate_id} approved with mode {data.mode}"
    ).model_dump()

@app.post("/api/projects/{project_id}/run")
async def run_project(project_id: str, data: ProjectRun):
    # Determine pipeline path
    pipeline_path = None
    p_id = data.pipeline_id
    
    if not p_id:
        # Try to infer from project index if not provided
        index = get_project_index(project_id)
        if index:
            p_id = index.get("pipeline", {}).get("id")
    
    if p_id:
        if DIRECT_IMPORTS:
            meta = describe_pipeline(p_id)
            if meta:
                pipeline_path = meta["path"]
        
        if not pipeline_path and os.path.exists(MANIFEST_PATH):
            with open(MANIFEST_PATH, "r") as f:
                manifest = json.load(f)
                entry = next((p for p in manifest if p["id"] == p_id), None)
                if entry:
                    pipeline_path = entry["path"]

        # Final fallback/check
        if not pipeline_path:
            # Check standard locations
            candidates = [
                f"dawn/pipelines/{p_id}.yaml",
                f"dawn/pipelines/golden/{p_id}.yaml"
            ]
            for c in candidates:
                if (BASE_DIR / c).exists():
                    pipeline_path = c
                    break
    
    if not pipeline_path or not (BASE_DIR / pipeline_path).exists():
        raise HTTPException(status_code=400, detail=f"Could not resolve pipeline path for ID: {p_id}")

    # Executor logic
    try:
        # We handle the execution in a separate way depending on the executor
        # For 'local', it blocks unless we background it.
        # But Phase 11 says "UI shows 'running' until inspect reports terminal states".
        # We can background the run_pipeline call or use SubprocessExecutor which is already async-ish in nature (it waits, but we can call it in a thread).
        
        # Mark as running
        run_id = f"run-{int(time.time())}"
        active_runs[project_id] = {
            "run_id": run_id,
            "started_at": time.time(),
            "executor": data.executor,
            "pipeline": pipeline_path
        }

        # Background execution (simple threading for MVP)
        import threading
        def _run():
            try:
                executor = get_executor(data.executor, projects_dir=str(PROJECTS_DIR), links_dir=str(LINKS_DIR))
                result = executor.run_pipeline(project_id, pipeline_path=pipeline_path, profile=data.profile, metadata=data.metadata)
                active_runs[project_id]["run_id"] = result.run_id
            finally:
                if project_id in active_runs:
                    del active_runs[project_id]

        thread = threading.Thread(target=_run)
        thread.start()

        # We return a temporary ID or wait a tiny bit to get the real one?
        # Actually, executors generate run_id immediately before execution.
        # Let's make get_executor/run_pipeline return the ID or generate it here.
        # For now, we return our own stable run_id and let executor use it if we passed it.
        return {"status": "success", "run_id": run_id}
    except Exception as e:
        if project_id in active_runs:
            del active_runs[project_id]
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects/{project_id}/runs")
async def list_project_runs(project_id: str):
    index = get_project_index(project_id)
    if not index:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return index.get("runs", {}).get("history", [])

@app.get("/api/projects/{project_id}/runs/{run_id}")
async def get_run_details(project_id: str, run_id: str):
    run_dir = PROJECTS_DIR / project_id / "runs" / run_id
    run_json = run_dir / "run.json"
    
    if not run_json.exists():
        raise HTTPException(status_code=404, detail="Run session not found")
    
    with open(run_json, "r") as f:
        return json.load(f)

@app.get("/api/projects/{project_id}/healing")
async def get_healing_metadata(project_id: str):
    """
    Get self-healing metadata for the most recent run.
    Returns healing iterations and outcomes.
    """
    index = get_project_index(project_id)
    if not index:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    # PRIORITY 1: Check artifacts directory (primary location from validation.self_heal link)
    # This works even if no runs exist yet
    artifacts_healing_path = PROJECTS_DIR / project_id / "artifacts" / "validation.self_heal" / "healing_report.json"
    if artifacts_healing_path.exists():
        with open(artifacts_healing_path, "r") as f:
            healing_data = json.load(f)
            # Add run_id from latest run if available
            runs_dir = PROJECTS_DIR / project_id / "runs"
            if runs_dir.exists():
                run_dirs = sorted([d for d in runs_dir.iterdir() if d.is_dir()], 
                                 key=lambda x: x.stat().st_mtime, reverse=True)
                if run_dirs and "run_id" not in healing_data:
                    healing_data["run_id"] = run_dirs[0].name
            return healing_data
    
    # PRIORITY 2: Check runs directory for run-specific healing reports
    runs_dir = PROJECTS_DIR / project_id / "runs"
    if not runs_dir.exists():
        # No runs yet, return empty healing report
        return HealingReport(
            healing_enabled=True,
            total_attempts=0,
            final_status="not_needed",
            iterations=[]
        ).model_dump()
    
    # Get latest run directory
    run_dirs = sorted([d for d in runs_dir.iterdir() if d.is_dir()], 
                     key=lambda x: x.stat().st_mtime, reverse=True)
    
    if not run_dirs:
        return HealingReport(
            healing_enabled=True,
            total_attempts=0,
            final_status="not_needed",
            iterations=[]
        ).model_dump()
    
    latest_run_dir = run_dirs[0]
    
    # Phase 2: Check artifacts directory first (primary location from validation.self_heal link)
    artifacts_healing_path = PROJECTS_DIR / project_id / "artifacts" / "validation.self_heal" / "healing_report.json"
    if artifacts_healing_path.exists():
        with open(artifacts_healing_path, "r") as f:
            healing_data = json.load(f)
            # Add run_id if not present
            if "run_id" not in healing_data:
                healing_data["run_id"] = latest_run_dir.name
            return healing_data
    
    # Fallback: Check run directory (legacy/alternative location)
    healing_report_path = latest_run_dir / "healing_report.json"
    if healing_report_path.exists():
        with open(healing_report_path, "r") as f:
            return json.load(f)
    
    # Fallback: Try to infer healing from run metadata
    # This is a placeholder for projects that haven't run healing yet
    run_json_path = latest_run_dir / "run.json"
    if run_json_path.exists():
        with open(run_json_path, "r") as f:
            run_data = json.load(f)
        
        # Check if run was successful - if status is SUCCEEDED, possibly healed
        status = run_data.get("status", "UNKNOWN")
        
        return HealingReport(
            healing_enabled=True,
            total_attempts=0,
            final_status="healed" if status == "SUCCEEDED" else "not_attempted",
            iterations=[],
            run_id=latest_run_dir.name
        ).model_dump()
    
    # No healing data available
    return HealingReport(
        healing_enabled=False,
        total_attempts=0,
        final_status="unknown",
        iterations=[]
    ).model_dump()

@app.get("/api/projects/{project_id}/runs/{run_id}/logs")
async def stream_logs(project_id: str, run_id: str, stream: int = 0):
    run_dir = PROJECTS_DIR / project_id / "runs" / run_id
    log_path = run_dir / "worker.log"
    
    if not log_path.exists():
        # Try to wait a bit if it's a very new run
        for _ in range(5):
            if log_path.exists(): break
            await asyncio.sleep(0.5)
            
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    if stream == 0:
        with open(log_path, "r") as f:
            # Return last 500 lines
            lines = f.readlines()
            return {"logs": "".join(lines[-500:])}

    async def log_generator():
        with open(log_path, "r") as f:
            # Start from beginning
            while True:
                line = f.readline()
                if line:
                    yield {"data": line.rstrip()}
                else:
                    # Check if run is still active
                    # Simple check: if project is in active_runs and run_id matches
                    is_active = project_id in active_runs and active_runs[project_id].get("run_id") == run_id
                    
                    # Also check run_json for terminal status
                    run_json = run_dir / "run.json"
                    if not is_active and run_json.exists():
                        try:
                            with open(run_json, "r") as rj:
                                meta = json.load(rj)
                                if meta.get("status") in ["SUCCEEDED", "FAILED"]:
                                    # Final read
                                    remaining = f.read()
                                    if remaining:
                                        for l in remaining.splitlines():
                                            yield {"data": l}
                                    break
                        except: pass
                    
                    await asyncio.sleep(0.5)

    return EventSourceResponse(log_generator())

@app.get("/api/projects/{project_id}/artifacts")
async def list_artifacts(project_id: str):
    index = get_project_index(project_id)
    if not index:
        raise HTTPException(status_code=404, detail="Project index not found")
    return index.get("artifacts", {})

@app.get("/api/projects/{project_id}/artifact/{artifact_id}")
async def get_artifact(project_id: str, artifact_id: str):
    index = get_project_index(project_id)
    if not index:
        raise HTTPException(status_code=404, detail="Project index not found")
    
    artifact = index.get("artifacts", {}).get(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found in index")
    
    rel_path = artifact.get("path")
    if not rel_path:
        raise HTTPException(status_code=404, detail="Artifact path missing in index")
    
    file_path = BASE_DIR / rel_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found on disk: {rel_path}")
    
    return FileResponse(path=file_path, filename=file_path.name, media_type=artifact.get("mime"))

@app.get("/api/projects/{project_id}/report")
async def view_report(project_id: str):
    index = get_project_index(project_id)
    if not index:
        raise HTTPException(status_code=404, detail="Project index not found")
    
    download_entry = index.get("downloads", {}).get("project_report")
    rel_path = download_entry.get("path") if isinstance(download_entry, dict) else download_entry
    if not rel_path:
        raise HTTPException(status_code=404, detail="Project report not available for this project")
    
    file_path = BASE_DIR / rel_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report file missing on disk")
    
    return FileResponse(path=file_path)

@app.get("/api/projects/{project_id}/download/{kind}")
async def download_artifact(project_id: str, kind: str):
    index = get_project_index(project_id)
    if not index:
        raise HTTPException(status_code=404, detail="Project index not found")
    
    download_entry = index.get("downloads", {}).get(kind)
    rel_path = download_entry.get("path") if isinstance(download_entry, dict) else download_entry
    if not rel_path:
        raise HTTPException(status_code=404, detail=f"Download '{kind}' not found for project {project_id}")
    
    file_path = BASE_DIR / rel_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found on disk: {rel_path}")
    
    return FileResponse(path=file_path, filename=file_path.name)

@app.get("/api/projects/{project_id}/inputs")
async def list_inputs(project_id: str):
    project_root = PROJECTS_DIR / project_id
    inputs_dir = project_root / "inputs"
    if not inputs_dir.exists():
        return {"files": []}
    
    files = []
    for f in inputs_dir.iterdir():
        if f.is_file() and not f.name.startswith("."):
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime
            })
    return {"files": files}

@app.get("/api/projects/{project_id}/inputs/{filename}")
async def get_input(project_id: str, filename: str):
    # Basic security check
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    project_root = PROJECTS_DIR / project_id
    input_path = project_root / "inputs" / filename
    
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Input {filename} not found")
    
    try:
        with open(input_path, "r") as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects/{project_id}/view/{filename}")
async def view_input_raw(project_id: str, filename: str):
    """
    Serve an input file directly for browser viewing.
    Useful for verifying HTML or Streamlit code.
    """
    # Basic security check
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    project_root = PROJECTS_DIR / project_id
    input_path = project_root / "inputs" / filename
    
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"File {filename} not found")
    
    import mimetypes
    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = "text/plain"
        
    return FileResponse(path=input_path, media_type=mime_type)

@app.put("/api/projects/{project_id}/inputs/{filename}")
async def update_input(project_id: str, filename: str, content: str = Body(..., embed=True)):
    # Basic security check
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    # Expanded allowed extensions for web dev projects
    allowed_exts = [".md", ".json", ".yaml", ".yml", ".txt", ".html", ".css", ".js", ".py"]
    if not any(filename.lower().endswith(ext) for ext in allowed_exts):
        raise HTTPException(status_code=400, detail=f"File extension not allowed. Must be one of: {allowed_exts}")

    project_root = PROJECTS_DIR / project_id
    input_path = project_root / "inputs" / filename
    
    if not input_path.parent.exists():
        raise HTTPException(status_code=404, detail="Project or inputs directory not found")
    
    try:
        with open(input_path, "w") as f:
            f.write(content)
        return {"status": "success", "message": f"Updated {filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{project_id}/inputs")
async def upload_inputs(
    project_id: str,
    files: List[UploadFile] = File(...)
):
    """
    Upload one or more files to project inputs directory.
    
    Security constraints:
    - Rejects filenames matching hitl_*.json (approval files)
    - Rejects filenames matching .dawn_* (internal manifests)
    - Validates file extensions (.py, .json, .md, .yaml, .yml, .txt)
    - Prevents path traversal attacks
    - Enforces 10MB file size limit
    """
    # Validate project exists
    project_root = PROJECTS_DIR / project_id
    inputs_dir = project_root / "inputs"
    
    if not project_root.exists():
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    inputs_dir.mkdir(parents=True, exist_ok=True)
    
    # Allowed extensions
    allowed_exts = [".py", ".json", ".md", ".yaml", ".yml", ".txt", ".html", ".css", ".js"]
    
    # File size limit (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024
    
    uploaded_files = []
    
    for file in files:
        filename = file.filename
        
        # Security: Block approval files (agents cannot write their own approvals)
        if filename.startswith("hitl_") and filename.endswith(".json"):
            raise HTTPException(
                status_code=400,
                detail=f"Security violation: Cannot upload approval files (hitl_*.json). File: {filename}"
            )
        
        # Security: Block internal DAWN manifest files
        if filename.startswith(".dawn_"):
            raise HTTPException(
                status_code=400,
                detail=f"Security violation: Cannot upload internal DAWN files (.dawn_*). File: {filename}"
            )
        
        # Validate filename and path traversal
        if not filename or filename.startswith("/") or ".." in filename:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid filename (path traversal or absolute path detected): {filename}"
            )
        
        # Enforce relative path structure (must stay inside inputs/)
        # We allow '/' for subdirectories like tests/test_math.py
        target_path = inputs_dir / filename
        try:
            # Check if resolved path is still within inputs_dir
            target_path.resolve().relative_to(inputs_dir.resolve())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid filename (path traversal detected): {filename}"
            )
        
        # Create subdirectories if they exist in the filename
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Validate file extension (check the final part of the path)
        if not any(filename.endswith(ext) for ext in allowed_exts):
            raise HTTPException(
                status_code=400,
                detail=f"File extension not allowed: {filename}. Allowed: {', '.join(allowed_exts)}"
            )
        
        # Read file content
        content = await file.read()
        
        # Check file size
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large: {filename} ({len(content)} bytes, max {MAX_FILE_SIZE})"
            )
        
        # Write file
        file_path = inputs_dir / filename
        try:
            with open(file_path, "wb") as f:
                f.write(content)
            
            # Calculate checksum for verification
            import hashlib
            checksum = hashlib.sha256(content).hexdigest()
            
            uploaded_files.append({
                "filename": filename,
                "size": len(content),
                "checksum": checksum[:16] + "...",  # Truncated for brevity
                "path": str(file_path.relative_to(PROJECTS_DIR))
            })
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to write file {filename}: {str(e)}"
            )
    
    return {
        "status": "success",
        "project_id": project_id,
        "uploaded": len(uploaded_files),
        "files": uploaded_files
    }


@app.post("/api/projects/{project_id}/gate")
async def resolve_gate(project_id: str, payload: Dict[str, Any] = Body(...)):
    filename = payload.get("filename")
    decision = payload.get("decision") # e.g. "APPROVED"
    reason = payload.get("reason", "")
    
    if not filename or not decision:
        raise HTTPException(status_code=400, detail="Missing filename or decision")
    
    # Security check for filename
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    project_root = PROJECTS_DIR / project_id
    input_path = project_root / "inputs" / filename
    
    # We write a decision JSON
    # Typically for human_decision.json or patch_approval.json
    try:
        content = {
            "decision": decision,
            "reason": reason,
            "decided_by": "Operator UI",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        with open(input_path, "w") as f:
            json.dump(content, f, indent=2)
        return {"status": "success", "message": f"Resolved gate: {filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects/{project_id}/compare-runs")
async def compare_runs(project_id: str, r1: str, r2: str):
    project_root = PROJECTS_DIR / project_id
    
    def get_run_meta(rid):
        p = project_root / "runs" / rid / "run.json"
        if p.exists():
            with open(p, "r") as f: return json.load(f)
        return None

    m1 = get_run_meta(r1)
    m2 = get_run_meta(r2)
    
    if not m1 or not m2:
        raise HTTPException(status_code=404, detail="One or both runs not found")
        
    return {
        "run1": m1,
        "run2": m2,
        "diff": {
            "status_changed": m1.get("status") != m2.get("status"),
            "profile_changed": m1.get("profile") != m2.get("profile")
        }
    }

# --- Static Files ---
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT)
