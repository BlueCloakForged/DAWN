import os
import json
import time
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List

def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 digest of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def update_project_index(project_root: Path, pipeline_meta: Optional[Dict] = None, run_context: Optional[Dict] = None) -> None:
    """
    Update the canonical project_index.json for a project.
    
    Args:
        project_root: Path to the project directory.
        pipeline_meta: Optional pipeline metadata (id, path, version).
        run_context: Optional run context (run_id, status, worker_id, executor, profile).
    """
    try:
        index_path = project_root / "project_index.json"
        warnings = []

        # 1. Load existing index or start fresh
        if index_path.exists():
            with open(index_path, "r") as f:
                try:
                    index = json.load(f)
                except:
                    index = {}
        else:
            index = {}

        # 2. Basic Metadata
        index["schema_version"] = "1.0.0"
        index["project_id"] = project_root.name
        index["workspace_root"] = str(Path(os.getcwd()).absolute())
        
        # 3. Load Project Config (Bootstrap metadata)
        config_path = project_root / "config" / "project.json"
        if config_path.exists():
            with open(config_path, "r") as f:
                try:
                    config = json.load(f)
                    index.setdefault("created_at", config.get("created_at"))
                    # If pipeline_meta is not provided, try to infer from config
                    if not pipeline_meta:
                        pipeline_meta = {
                            "id": config.get("pipeline_id"),
                            "profile": config.get("profile")
                        }
                except Exception as e:
                    warnings.append(f"Failed to load config/project.json: {e}")
        
        if not index.get("created_at"):
            index["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        
        index["last_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # 4. Pipeline Metadata
        if pipeline_meta:
            index.setdefault("pipeline", {})
            for key in ["id", "path", "version", "profile", "executor"]:
                if pipeline_meta.get(key):
                    index["pipeline"][key] = pipeline_meta[key]
        
        # 5. Run Context and History
        index.setdefault("runs", {})
        index["runs"].setdefault("history", [])

        if run_context:
            run_id = run_context.get("run_id")
            if run_id:
                index["runs"]["last_run_id"] = run_id
            
            status = run_context.get("status")
            if status:
                index["runs"]["last_status"] = status
            
            if run_context.get("worker_id"):
                index["runs"]["worker_id"] = run_context["worker_id"]

            # Maintain history
            history = index.get("runs", {}).get("history", [])
            
            # Update or Add current run to history
            current_run = next((r for r in history if r["run_id"] == run_id), None) if run_id else None
            if not current_run and run_id:
                current_run = {
                    "run_id": run_id,
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "executor": pipeline_meta.get("executor") if pipeline_meta else None,
                    "profile": pipeline_meta.get("profile") if pipeline_meta else None,
                    "run_dir": f"runs/{run_id}",
                    "log_path": f"runs/{run_id}/worker.log"
                }
                history.insert(0, current_run) # Newest first
            
            if current_run:
                if status:
                    current_run["status"] = status
                if status in ["SUCCEEDED", "FAILED"]:
                    current_run["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    if run_context.get("error"):
                        current_run["error"] = run_context["error"]

            # Cap history at 20 entries
            index["runs"]["history"] = history[:20]

        # 6. Parse Ledger for Link Statuses
        ledger_path = project_root / "ledger" / "events.jsonl"
        links_status = {}
        if ledger_path.exists():
            try:
                with open(ledger_path, "r") as f:
                    for line in f:
                        event = json.loads(line)
                        link_id = event.get("link_id")
                        if not link_id: continue
                        
                        status = event.get("status")
                        timestamp = event.get("timestamp")
                        
                        if link_id not in links_status:
                            links_status[link_id] = {"status": "PENDING", "attempts": 0}
                        
                        if status == "STARTED":
                            links_status[link_id]["started_at"] = timestamp
                            links_status[link_id]["attempts"] += 1
                            links_status[link_id]["status"] = "RUNNING"
                        elif status in ["SUCCEEDED", "FAILED", "SKIPPED"]:
                            links_status[link_id]["ended_at"] = timestamp
                            links_status[link_id]["status"] = status
                            # Extract metrics if available (Phase 1.2: psutil etc.)
                            if "metrics" in event:
                                links_status[link_id]["metrics"] = event["metrics"]
                            if status == "FAILED":
                                index["runs"]["last_error"] = event.get("error") or event.get("message")
            except Exception as e:
                warnings.append(f"Failed to parse ledger: {e}")
        
        index["links"] = links_status

        # Phase 11.0: Enhanced MIME Mapping
        MIME_MAP = {
            ".json": "application/json",
            ".html": "text/html",
            ".zip": "application/zip",
            ".md": "text/markdown",
            ".txt": "text/plain",
            ".yaml": "text/yaml",
            ".yml": "text/yaml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".pdf": "application/pdf"
        }

        # 7. Artifact Inventory
        art_index_path = project_root / "artifact_index.json"
        artifacts = {}
        downloads = {}
        if art_index_path.exists():
            try:
                with open(art_index_path, "r") as f:
                    raw_artifacts = json.load(f)
                    for art_id, info in raw_artifacts.items():
                        rel_path = info.get("path")
                        # Ensure path is relative for the index
                        if rel_path and os.path.isabs(rel_path):
                            try:
                                rel_path = str(Path(rel_path).relative_to(index["workspace_root"]))
                            except ValueError:
                                pass # Keep as is if not relative to workspace
                        
                        full_path = Path(index["workspace_root"]) / rel_path if rel_path else None
                        size_bytes = 0
                        mime = "application/octet-stream"
                        if full_path and full_path.exists():
                            stats = full_path.stat()
                            size_bytes = stats.st_size
                            mime = MIME_MAP.get(full_path.suffix.lower(), "application/octet-stream")

                        art_data = {
                            "artifactId": art_id,
                            "producer": info.get("link_id"),
                            "path": rel_path,
                            "digest_sha256": info.get("digest"),
                            "size_bytes": size_bytes,
                            "mime": mime
                        }
                        if info.get("run_id"):
                            art_data["run_id"] = info["run_id"]
                        if info.get("created_at"):
                            art_data["created_at"] = info["created_at"]
                            
                        artifacts[art_id] = art_data
                        
                        # Popular downloads (Phase 11: as objects)
                        download_map = {
                            "dawn.project.report": "project_report",
                            "dawn.evidence.pack": "evidence_pack",
                            "dawn.release.bundle": "release_bundle"
                        }
                        if art_id in download_map:
                            downloads[download_map[art_id]] = {
                                "path": rel_path,
                                "mime": mime,
                                "size_bytes": size_bytes,
                                "digest_sha256": info.get("digest")
                            }
            except Exception as e:
                warnings.append(f"Failed to parse artifact_index.json: {e}")
        
        index["artifacts"] = artifacts
        index["downloads"] = downloads

        # 8. Inputs Registry (Phase 11)
        inputs_dir = project_root / "inputs"
        index["inputs"] = {"files": []}
        if inputs_dir.exists():
            for f in inputs_dir.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    try:
                        index["inputs"]["files"].append({
                            "path": str(f.relative_to(project_root)),
                            "size_bytes": f.stat().st_size,
                            "digest_sha256": calculate_sha256(f),
                            "mime": MIME_MAP.get(f.suffix.lower(), "text/plain"),
                            "last_modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(f.stat().st_mtime))
                        })
                    except: pass

        # 9. Approvals Audit Trail (Phase 11)
        # Scan inputs for decision JSONs to populate history
        approvals = []
        if inputs_dir.exists():
            for f in ["human_decision.json", "patch_approval.json"]:
                p = inputs_dir / f
                if p.exists():
                    try:
                        with open(p, "r") as df:
                            data = json.load(df)
                            approvals.append({
                                "gate_type": "human_review" if f == "human_decision.json" else "patch_approval",
                                "decision": data.get("decision"),
                                "written_path": str(p.relative_to(project_root)),
                                "written_digest_sha256": calculate_sha256(p),
                                "timestamp": data.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                                "comment": data.get("reason", "")
                            })
                    except: pass
        index["approvals"] = {"history": sorted(approvals, key=lambda x: x["timestamp"], reverse=True)}

        index["warnings"] = warnings

        # 8. Atomic Write
        temp_path = index_path.with_suffix(".tmp")
        with open(temp_path, "w") as f:
            json.dump(index, f, indent=2)
        os.replace(temp_path, index_path)

    except Exception as e:
        # Index generation should never fail the run
        print(f"CRITICAL ERROR updating project index for {project_root}: {e}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        update_project_index(Path(sys.argv[1]))
