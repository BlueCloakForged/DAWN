"""
DAWN Multi-Project Queue Manager
Phase 8.4.3: Enhanced Queue Telemetry
"""

import argparse
import json
import os
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from filelock import FileLock
from dawn.runtime.orchestrator import Orchestrator

QUEUE_FILE = "queue/queue.jsonl"
QUEUE_LOCK = "queue/queue.lock"


class QueueManager:
    def __init__(self, queue_file: str = QUEUE_FILE):
        self.queue_file = Path(queue_file)
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = Path(QUEUE_LOCK)
        self._worker_id = f"{socket.gethostname()}:{os.getpid()}"

    def _read_queue(self) -> List[Dict]:
        """Read all entries from the queue."""
        if not self.queue_file.exists():
            return []

        entries = []
        with open(self.queue_file, "r") as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
        return entries

    def _write_queue(self, entries: List[Dict]):
        """Overwrite the queue file with new entries."""
        with open(self.queue_file, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

    def submit(self, project_id: str, pipeline: str, priority: int = 0, profile: str = "normal", executor: str = "local"):
        """Submit a new project to the queue."""
        with FileLock(self.lock_file):
            entries = self._read_queue()

            # Check if already queued
            for entry in entries:
                if entry["project_id"] == project_id and entry["status"] in ["PENDING", "RUNNING"]:
                    print(f"Project {project_id} is already in queue with status {entry['status']}")
                    return

            new_entry = {
                "project_id": project_id,
                "pipeline": pipeline,
                "priority": priority,
                "profile": profile,
                "executor": executor,
                "status": "PENDING",
                "submitted_at": time.time(),
                "started_at": None,
                "completed_at": None,
                "last_updated_at": time.time(),
                "worker_id": None,
                "run_id": None,
                "retry_count": 0,
                "error": None
            }

            entries.append(new_entry)
            # Sort by priority (higher first), then submission time
            entries.sort(key=lambda e: (-e.get("priority", 0), e.get("submitted_at", 0)))
            self._write_queue(entries)

            print(f"Submitted project {project_id} with priority {priority}, profile={profile}")

    def cancel(self, project_id: str):
        """Cancel a pending project."""
        with FileLock(self.lock_file):
            entries = self._read_queue()
            updated = []
            cancelled = False

            for entry in entries:
                if entry["project_id"] == project_id and entry["status"] == "PENDING":
                    entry["status"] = "CANCELLED"
                    entry["completed_at"] = time.time()
                    entry["last_updated_at"] = time.time()
                    cancelled = True
                updated.append(entry)

            self._write_queue(updated)

            if cancelled:
                print(f"Cancelled project {project_id}")
            else:
                print(f"Project {project_id} not found or not in PENDING status")

    def status(self, verbose: bool = False):
        """Display current queue status with enhanced telemetry (Phase 8.4.3)."""
        entries = self._read_queue()

        print("\n" + "=" * 100)
        print(" DAWN Queue Status")
        print("=" * 100)

        if verbose:
            print(f"\n{'Project ID':<20} {'Pipeline':<20} {'Status':<12} {'Pri':<4} {'Profile':<10} {'Worker':<20} {'Last Update':<20}")
            print("-" * 100)
        else:
            print(f"\n{'Project ID':<20} {'Pipeline':<25} {'Status':<12} {'Priority':<8} {'Profile':<10}")
            print("-" * 80)

        for entry in entries:
            pipeline_short = Path(entry["pipeline"]).stem if entry.get("pipeline") else "unknown"
            profile = entry.get("profile", "normal")

            if verbose:
                worker = entry.get("worker_id", "-") or "-"
                if len(worker) > 18:
                    worker = worker[:15] + "..."
                last_update = entry.get("last_updated_at")
                if last_update:
                    last_update_str = datetime.fromtimestamp(last_update).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    last_update_str = "-"
                print(f"{entry['project_id']:<20} {pipeline_short:<20} {entry['status']:<12} {entry.get('priority', 0):<4} {profile:<10} {worker:<20} {last_update_str:<20}")
            else:
                print(f"{entry['project_id']:<20} {pipeline_short:<25} {entry['status']:<12} {entry.get('priority', 0):<8} {profile:<10}")

        # Summary counts
        pending = sum(1 for e in entries if e["status"] == "PENDING")
        running = sum(1 for e in entries if e["status"] == "RUNNING")
        completed = sum(1 for e in entries if e["status"] == "COMPLETED")
        failed = sum(1 for e in entries if e["status"] == "FAILED")
        cancelled = sum(1 for e in entries if e["status"] == "CANCELLED")

        print("-" * (100 if verbose else 80))
        print(f"\nSummary: PENDING={pending} | RUNNING={running} | COMPLETED={completed} | FAILED={failed} | CANCELLED={cancelled}")

        # Show retry info if any
        retried = [e for e in entries if e.get("retry_count", 0) > 0]
        if retried:
            print(f"\nRetried projects: {len(retried)}")
            for e in retried:
                print(f"  - {e['project_id']}: {e['retry_count']} retries")

        # Show running project details
        running_entries = [e for e in entries if e["status"] == "RUNNING"]
        if running_entries and verbose:
            print(f"\nCurrently Running:")
            for e in running_entries:
                started = e.get("started_at")
                if started:
                    elapsed = time.time() - started
                    print(f"  - {e['project_id']} on {e.get('worker_id', 'unknown')} (elapsed: {elapsed:.1f}s)")

        print("=" * (100 if verbose else 80) + "\n")

    def retry(self, project_id: str):
        """Retry a failed project."""
        with FileLock(self.lock_file):
            entries = self._read_queue()
            retried = False

            for entry in entries:
                if entry["project_id"] == project_id and entry["status"] == "FAILED":
                    entry["status"] = "PENDING"
                    entry["retry_count"] = entry.get("retry_count", 0) + 1
                    entry["error"] = None
                    entry["started_at"] = None
                    entry["completed_at"] = None
                    entry["last_updated_at"] = time.time()
                    entry["worker_id"] = None
                    entry["run_id"] = None
                    retried = True

            if retried:
                entries.sort(key=lambda e: (-e.get("priority", 0), e.get("submitted_at", 0)))
                self._write_queue(entries)
                print(f"Retrying project {project_id}")
            else:
                print(f"Project {project_id} not found or not in FAILED status")

    def clear(self, status: str = None):
        """Clear entries from the queue. If status provided, only clear that status."""
        with FileLock(self.lock_file):
            entries = self._read_queue()

            if status:
                kept = [e for e in entries if e["status"] != status.upper()]
                removed = len(entries) - len(kept)
                self._write_queue(kept)
                print(f"Cleared {removed} entries with status {status.upper()}")
            else:
                # Clear completed/failed/cancelled only, keep pending/running
                kept = [e for e in entries if e["status"] in ["PENDING", "RUNNING"]]
                removed = len(entries) - len(kept)
                self._write_queue(kept)
                print(f"Cleared {removed} completed/failed/cancelled entries")

    def run(self, workers: int = 1, max_projects: Optional[int] = None,
            links_dir: str = "dawn/links", projects_dir: str = "projects",
            profile_override: Optional[str] = None):
        """Execute queued projects with profile support.

        Args:
            workers: Number of parallel workers (reserved for future use, currently single-threaded)
            max_projects: Maximum number of projects to execute before stopping
            links_dir: Directory containing link definitions
            projects_dir: Directory containing project data
            profile_override: Override profile for all projects (ignores per-project profile)
        """
        print(f"Starting queue runner with {workers} workers (serial execution)...")
        
        projects_executed = 0
        from dawn.runtime.executors import get_executor

        while True:
            if max_projects and projects_executed >= max_projects:
                break

            target_entry = None
            with FileLock(self.lock_file):
                entries = self._read_queue()
                for entry in entries:
                    if entry["status"] == "PENDING":
                        # Check if project is locked by another worker (if applicable, though the new snippet removes this check)
                        # For now, just assign it
                        entry["status"] = "RUNNING"
                        entry["started_at"] = datetime.now().isoformat()
                        entry["worker"] = socket.gethostname()
                        target_entry = entry
                        break
                
                if target_entry:
                    self._write_queue(entries)

            if not target_entry:
                print("No more pending projects in queue") # Added for clarity
                break

            project_id = target_entry["project_id"]
            pipeline = target_entry["pipeline"]
            profile = profile_override or target_entry["profile"]
            executor_name = target_entry.get("executor", "local")

            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Executing {project_id} (pipeline: {pipeline}) via {executor_name}...")
            
            try:
                executor = get_executor(executor_name, links_dir=links_dir, projects_dir=projects_dir)
                result = executor.run_pipeline(project_id, pipeline_path=pipeline, profile=profile)
                
                status = "COMPLETED" if result.status == "SUCCEEDED" else "FAILED"
            except Exception as e:
                print(f"Error executing {project_id}: {e}")
                status = "FAILED"
                error_msg = str(e)
            else:
                error_msg = None

            with FileLock(self.lock_file):
                entries = self._read_queue()
                for entry in entries:
                    if entry["project_id"] == project_id and entry["status"] == "RUNNING":
                        entry["status"] = status
                        entry["completed_at"] = datetime.now().isoformat()
                        entry["last_updated_at"] = datetime.now().isoformat() # Keep this for consistency
                        entry["error"] = error_msg
                        break
                self._write_queue(entries)
            
            # Update project index after queue run
            try:
                from dawn.runtime.project_index import update_project_index
                project_root = Path(projects_dir) / project_id
                # Get pipeline meta from entry if possible
                update_project_index(project_root, pipeline_meta={
                    "path": pipeline_path,
                    "profile": profile,
                    "executor": executor_name
                }, run_context={
                    "status": status,
                    "run_id": f"run_{int(time.time())}"
                })
            except: pass

            projects_executed += 1

def main():
    parser = argparse.ArgumentParser(description="DAWN Multi-Project Queue (Phase 8.4.3)")
    subparsers = parser.add_subparsers(dest="command")

    # Submit command
    submit_parser = subparsers.add_parser("submit", help="Submit a project to the queue")
    submit_parser.add_argument("--project", "-p", required=True, help="Project ID")
    submit_parser.add_argument("--pipeline", "-l", required=False, help="Pipeline path")
    submit_parser.add_argument("--pipeline-id", help="Pipeline ID from manifest") # Added
    submit_parser.add_argument("--priority", type=int, default=0, help="Priority (higher runs first)")
    submit_parser.add_argument("--profile", default="normal", choices=["normal", "isolation"],
                               help="Execution profile (default: normal)")
    submit_parser.add_argument("--executor", default="local", choices=["local", "subprocess"], # Added
                               help="Executor to use for the project (default: local)")

    # Cancel command
    cancel_parser = subparsers.add_parser("cancel", help="Cancel a pending project")
    cancel_parser.add_argument("--project", "-p", required=True, help="Project ID")

    # Status command
    status_parser = subparsers.add_parser("status", help="Show queue status")
    # status_parser.add_argument("--verbose", "-v", action="store_true", # Removed
    #                            help="Show detailed status including worker info")

    # Retry command
    retry_parser = subparsers.add_parser("retry", help="Retry a failed project")
    retry_parser.add_argument("--project", "-p", required=True, help="Project ID")

    # Clear command
    clear_parser = subparsers.add_parser("clear", help="Clear queue entries")
    clear_parser.add_argument("--status", choices=["pending", "running", "completed", "failed", "cancelled"], # Updated choices
                              help="Only clear entries with this status")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run queued projects")
    run_parser.add_argument("--workers", type=int, default=1,
                            help="Number of workers (currently only 1 supported)")
    run_parser.add_argument("--max-projects", type=int, help="Max projects to execute")
    run_parser.add_argument("--links-dir", default="dawn/links")
    run_parser.add_argument("--projects-dir", default="projects")
    run_parser.add_argument("--profile", choices=["normal", "isolation"],
                            help="Override profile for all projects")

    args = parser.parse_args()

    manager = QueueManager()

    if args.command == "submit":
        pipeline = args.pipeline
        if args.pipeline_id:
            from dawn.runtime.pipelines import describe_pipeline
            entry = describe_pipeline(args.pipeline_id)
            if entry:
                pipeline = entry["path"]
        manager.submit(args.project, pipeline, args.priority, args.profile, args.executor)
    elif args.command == "cancel":
        manager.cancel(args.project)
    elif args.command == "status":
        manager.status(verbose=getattr(args, 'verbose', False))
    elif args.command == "retry":
        manager.retry(args.project)
    elif args.command == "clear":
        manager.clear(args.status)
    elif args.command == "run":
        manager.run(args.workers, args.max_projects, args.links_dir, args.projects_dir,
                    getattr(args, 'profile', None))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
