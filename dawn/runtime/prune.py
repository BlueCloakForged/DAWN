"""
DAWN Artifact Pruning Tool - Phase 9.2

Responsibilities:
- Remove old artifacts based on retention policy
- Preserve protected artifacts (evidence packs, release bundles)
- Never delete ledger events (audit trail)
- Maintain auditability invariants

Usage:
    python3 -m dawn.runtime.prune --project <id> [--dry-run]
    python3 -m dawn.runtime.prune --all [--dry-run]
"""

import argparse
import json
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..policy import get_policy_loader


class PruningReport:
    """Tracks what was pruned and what was preserved."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.preserved: List[Dict] = []
        self.deleted: List[Dict] = []
        self.errors: List[Dict] = []
        self.space_freed_bytes: int = 0

    def add_preserved(self, artifact_id: str, reason: str, path: str):
        self.preserved.append({
            "artifact_id": artifact_id,
            "reason": reason,
            "path": path
        })

    def add_deleted(self, artifact_id: str, reason: str, path: str, size_bytes: int):
        self.deleted.append({
            "artifact_id": artifact_id,
            "reason": reason,
            "path": path,
            "size_bytes": size_bytes
        })
        self.space_freed_bytes += size_bytes

    def add_error(self, artifact_id: str, error: str, path: str):
        self.errors.append({
            "artifact_id": artifact_id,
            "error": error,
            "path": path
        })

    def to_dict(self) -> Dict:
        return {
            "project_id": self.project_id,
            "timestamp": datetime.now().isoformat(),
            "preserved_count": len(self.preserved),
            "deleted_count": len(self.deleted),
            "error_count": len(self.errors),
            "space_freed_bytes": self.space_freed_bytes,
            "space_freed_mb": round(self.space_freed_bytes / (1024 * 1024), 2),
            "preserved": self.preserved,
            "deleted": self.deleted,
            "errors": self.errors
        }


class ArtifactPruner:
    """Prunes artifacts based on retention policy."""

    def __init__(self, projects_dir: str = "projects"):
        self.projects_dir = Path(projects_dir)
        self.policy_loader = get_policy_loader()

    def prune_project(self, project_id: str, dry_run: bool = True) -> PruningReport:
        """Prune artifacts for a single project."""
        report = PruningReport(project_id)
        project_root = self.projects_dir / project_id

        if not project_root.exists():
            report.add_error("__project__", f"Project not found: {project_id}", str(project_root))
            return report

        # Load run history from ledger
        runs = self._get_run_history(project_root)

        # Load artifact index
        artifact_index = self._load_artifact_index(project_root)

        # Determine which runs to keep
        runs_to_keep = self._determine_runs_to_keep(runs)

        # Determine which artifacts to keep
        artifacts_to_keep = self._determine_artifacts_to_keep(
            artifact_index, runs_to_keep, runs
        )

        # Process each artifact
        for artifact_id, info in artifact_index.items():
            artifact_path = Path(info.get("path", ""))

            if artifact_id in artifacts_to_keep:
                reason = artifacts_to_keep[artifact_id]
                report.add_preserved(artifact_id, reason, str(artifact_path))
            else:
                if artifact_path.exists():
                    size = self._get_size(artifact_path)
                    if not dry_run:
                        try:
                            if artifact_path.is_file():
                                artifact_path.unlink()
                            elif artifact_path.is_dir():
                                shutil.rmtree(artifact_path)
                            report.add_deleted(artifact_id, "retention_policy", str(artifact_path), size)
                        except Exception as e:
                            report.add_error(artifact_id, str(e), str(artifact_path))
                    else:
                        report.add_deleted(artifact_id, "retention_policy (dry-run)", str(artifact_path), size)

        # Prune empty link directories in artifacts/
        if not dry_run:
            self._cleanup_empty_dirs(project_root / "artifacts")

        return report

    def _get_run_history(self, project_root: Path) -> List[Dict]:
        """Get run history from ledger events."""
        runs = []
        ledger_file = project_root / "ledger" / "events.jsonl"

        if not ledger_file.exists():
            return runs

        # Group events by run_id
        run_events: Dict[str, List[Dict]] = {}

        with open(ledger_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                event = json.loads(line)
                run_id = event.get("metrics", {}).get("run_id") or event.get("run_id")
                if run_id:
                    if run_id not in run_events:
                        run_events[run_id] = []
                    run_events[run_id].append(event)

        # Build run summaries
        for run_id, events in run_events.items():
            # Find the last event to determine status
            last_event = max(events, key=lambda e: e.get("timestamp", 0))
            first_event = min(events, key=lambda e: e.get("timestamp", 0))

            status = "UNKNOWN"
            for event in reversed(events):
                if event.get("step_id") == "link_complete":
                    status = event.get("status", "UNKNOWN")
                    break

            runs.append({
                "run_id": run_id,
                "status": status,
                "started_at": first_event.get("timestamp"),
                "ended_at": last_event.get("timestamp"),
                "events": events
            })

        # Sort by start time (newest first)
        runs.sort(key=lambda r: r.get("started_at", 0), reverse=True)
        return runs

    def _load_artifact_index(self, project_root: Path) -> Dict:
        """Load artifact index from project."""
        index_path = project_root / "artifact_index.json"
        if not index_path.exists():
            return {}

        with open(index_path, "r") as f:
            return json.load(f)

    def _determine_runs_to_keep(self, runs: List[Dict]) -> Set[str]:
        """Determine which runs to keep based on retention policy."""
        keep_n = self.policy_loader.get_keep_last_n_runs()
        keep_failed_days = self.policy_loader.get_keep_failed_runs_days()

        runs_to_keep = set()
        successful_count = 0
        cutoff_time = time.time() - (keep_failed_days * 24 * 60 * 60)

        for run in runs:
            run_id = run.get("run_id")
            status = run.get("status")
            ended_at = run.get("ended_at", 0)

            # Keep last N successful runs
            if status == "SUCCEEDED":
                if successful_count < keep_n:
                    runs_to_keep.add(run_id)
                    successful_count += 1

            # Keep recent failed runs
            elif status == "FAILED":
                if ended_at > cutoff_time:
                    runs_to_keep.add(run_id)

        return runs_to_keep

    def _determine_artifacts_to_keep(
        self,
        artifact_index: Dict,
        runs_to_keep: Set[str],
        runs: List[Dict]
    ) -> Dict[str, str]:
        """Determine which artifacts to keep and why."""
        artifacts_to_keep: Dict[str, str] = {}
        protected_types = self.policy_loader.get_protected_artifacts()

        for artifact_id, info in artifact_index.items():
            # Protected artifact types (never delete)
            if artifact_id in protected_types:
                artifacts_to_keep[artifact_id] = "protected_artifact_type"
                continue

            # Check if artifact is from a run we're keeping
            link_id = info.get("link_id")

            # For now, keep all artifacts (we'd need run_id in artifact_index to be more precise)
            # This is a safe default - artifacts without run tracking are preserved
            artifacts_to_keep[artifact_id] = "no_run_tracking"

        # Always keep evidence packs if configured
        if self.policy_loader.should_keep_evidence_pack():
            if "dawn.evidence.pack" in artifact_index:
                artifacts_to_keep["dawn.evidence.pack"] = "always_keep_evidence_pack"

        return artifacts_to_keep

    def _get_size(self, path: Path) -> int:
        """Get size of file or directory in bytes."""
        if path.is_file():
            return path.stat().st_size
        elif path.is_dir():
            total = 0
            for p in path.rglob("*"):
                if p.is_file():
                    total += p.stat().st_size
            return total
        return 0

    def _cleanup_empty_dirs(self, artifacts_dir: Path):
        """Remove empty directories in artifacts folder."""
        if not artifacts_dir.exists():
            return

        for link_dir in artifacts_dir.iterdir():
            if link_dir.is_dir() and not any(link_dir.iterdir()):
                link_dir.rmdir()

    def prune_all_projects(self, dry_run: bool = True) -> List[PruningReport]:
        """Prune artifacts for all projects."""
        reports = []

        if not self.projects_dir.exists():
            return reports

        for project_dir in self.projects_dir.iterdir():
            if project_dir.is_dir() and not project_dir.name.startswith("."):
                report = self.prune_project(project_dir.name, dry_run)
                reports.append(report)

        return reports


def main():
    parser = argparse.ArgumentParser(
        description="DAWN Artifact Pruning Tool (Phase 9.2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run for a single project (shows what would be deleted)
  python3 -m dawn.runtime.prune --project my_project --dry-run

  # Actually prune a project
  python3 -m dawn.runtime.prune --project my_project

  # Dry run for all projects
  python3 -m dawn.runtime.prune --all --dry-run

  # Generate JSON report
  python3 -m dawn.runtime.prune --project my_project --output report.json
        """
    )

    parser.add_argument("--project", "-p", help="Project ID to prune")
    parser.add_argument("--all", "-a", action="store_true", help="Prune all projects")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Show what would be deleted without actually deleting")
    parser.add_argument("--projects-dir", default="projects", help="Projects directory")
    parser.add_argument("--output", "-o", help="Output JSON report to file")

    args = parser.parse_args()

    if not args.project and not args.all:
        parser.print_help()
        print("\nError: Must specify --project or --all")
        return 1

    pruner = ArtifactPruner(args.projects_dir)

    if args.all:
        reports = pruner.prune_all_projects(dry_run=args.dry_run)
    else:
        reports = [pruner.prune_project(args.project, dry_run=args.dry_run)]

    # Print summary
    mode = "DRY RUN" if args.dry_run else "PRUNING"
    print(f"\n{'=' * 60}")
    print(f" DAWN Artifact Pruner - {mode}")
    print(f"{'=' * 60}\n")

    total_freed = 0
    for report in reports:
        print(f"Project: {report.project_id}")
        print(f"  Preserved: {len(report.preserved)} artifacts")
        print(f"  Deleted: {len(report.deleted)} artifacts")
        print(f"  Errors: {len(report.errors)}")
        print(f"  Space freed: {report.space_freed_bytes / (1024*1024):.2f} MB")
        total_freed += report.space_freed_bytes

        if report.errors:
            print(f"  Errors:")
            for err in report.errors:
                print(f"    - {err['artifact_id']}: {err['error']}")
        print()

    print(f"Total space {'would be ' if args.dry_run else ''}freed: {total_freed / (1024*1024):.2f} MB")

    # Output JSON if requested
    if args.output:
        output_data = {
            "mode": mode,
            "timestamp": datetime.now().isoformat(),
            "total_space_freed_bytes": total_freed,
            "reports": [r.to_dict() for r in reports]
        }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\nReport written to: {args.output}")

    return 0


if __name__ == "__main__":
    exit(main())
