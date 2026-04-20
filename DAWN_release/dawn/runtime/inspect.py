import argparse
import os
import json
from pathlib import Path
from .ledger import Ledger
from ..policy import get_policy_loader, PolicyValidationError

def inspect_project(project_id: str, projects_dir: str = None):
    if projects_dir is None:
        # Default to repo/projects
        base_dir = Path(__file__).parent.parent.parent
        projects_dir = base_dir / "projects"
    
    project_root = Path(projects_dir) / project_id
    if not project_root.exists():
        print(f"Error: Project {project_id} not found at {project_root}")
        return

    ledger = Ledger(str(project_root))
    events = ledger.get_events()
    
    if not events:
        print(f"Project {project_id} has no ledger events.")
        return

    print("\n" + "=" * 80)
    print(f" DAWN PROJECT INSPECTOR: {project_id}")
    print("=" * 80)
    
    # Reconstruct artifact index from ledger
    artifact_index = {}
    last_status = {}
    
    for event in events:
        link_id = event["link_id"]
        status = event["status"]
        last_status[link_id] = status
        
        if event["step_id"] == "link_complete" and status == "SUCCEEDED":
            outputs = event.get("outputs", {})
            for art_id, info in outputs.items():
                artifact_index[art_id] = {
                    "path": info["path"],
                    "digest": info["digest"],
                    "link": link_id
                }

    print(f"\n[PIPELINE STATUS]")
    for link_id, status in last_status.items():
        color = "✓" if status == "SUCCEEDED" else "✗"
        print(f"  {color} {link_id:<30} {status}")

    print(f"\n[ARTIFACT INDEX]")
    if not artifact_index:
        print("  No artifacts found.")
    else:
        print(f"  {'Artifact ID':<35} {'Producer':<25} {'Digest (Short)':<10}")
        print(f"  {'-' * 35} {'-' * 25} {'-' * 10}")
        for art_id, info in artifact_index.items():
            short_digest = info["digest"][:8]
            print(f"  {art_id:<35} {info['link']:<25} {short_digest:<10}")

    print(f"\n[KEY ARTIFACT PATHS]")
    for art_id, info in artifact_index.items():
        rel_path = os.path.relpath(info["path"], os.getcwd())
        print(f"  • {art_id:<35} -> {rel_path}")

    # Policy info
    print(f"\n[POLICY]")
    try:
        policy_loader = get_policy_loader()
        print(f"  policy.version: {policy_loader.version}")
        print(f"  policy.digest: {policy_loader.digest}")
        print(f"  policy.default_profile: {policy_loader.policy.get('default_profile')}")

        # Show budget limits
        budgets = policy_loader.policy.get("budgets", {})
        per_link = budgets.get("per_link", {})
        per_project = budgets.get("per_project", {})
        print(f"  budgets.per_link.max_wall_time_sec: {per_link.get('max_wall_time_sec')}")
        print(f"  budgets.per_link.max_output_bytes: {per_link.get('max_output_bytes')}")
        print(f"  budgets.per_project.max_project_bytes: {per_project.get('max_project_bytes')}")
    except PolicyValidationError as e:
        print(f"  ERROR: {e}")
    except Exception as e:
        print(f"  ERROR loading policy: {e}")

    print("\n" + "=" * 80 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DAWN Project Inspector")
    parser.add_argument("--project", "-p", required=True, help="Project ID")
    parser.add_argument("--projects-dir", default="projects", help="Base directory for projects")
    
    args = parser.parse_args()
    inspect_project(args.project, args.projects_dir)
