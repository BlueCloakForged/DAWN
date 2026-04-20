"""
DAWN Reproducibility Lockfile - Phase 9.3

Generates and validates dawn.lock.json for reproducible builds.

Contents:
- policy_digest: SHA256 of runtime_policy.yaml
- link_digests: SHA256 of each link.yaml used in the pipeline
- pipeline_digest: SHA256 of the pipeline YAML
- environment: Python version, pip freeze, platform info
- timestamp: When the lockfile was generated

Usage:
    python3 -m dawn.runtime.lockfile generate --project <id>
    python3 -m dawn.runtime.lockfile verify --project <id>
    python3 -m dawn.runtime.lockfile compare <lockfile1> <lockfile2>
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from ..policy import get_policy_loader


class LockfileGenerator:
    """Generates reproducibility lockfiles for DAWN runs."""

    LOCKFILE_VERSION = "1.0.0"

    def __init__(self, projects_dir: str = "projects", links_dir: str = "dawn/links"):
        self.projects_dir = Path(projects_dir)
        self.links_dir = Path(links_dir)
        self.policy_loader = get_policy_loader()

    def generate(self, project_id: str) -> Dict[str, Any]:
        """Generate a lockfile for a project run."""
        project_root = self.projects_dir / project_id

        if not project_root.exists():
            raise ValueError(f"Project not found: {project_id}")

        lockfile = {
            "lockfile_version": self.LOCKFILE_VERSION,
            "generated_at": datetime.now().isoformat(),
            "project_id": project_id,
            "policy": self._get_policy_info(),
            "pipeline": self._get_pipeline_info(project_root),
            "links": self._get_link_digests(project_root),
            "environment": self._get_environment_info(),
            "artifact_digests": self._get_artifact_digests(project_root),
        }

        return lockfile

    def _get_policy_info(self) -> Dict[str, Any]:
        """Get policy digest and version."""
        return {
            "version": self.policy_loader.version,
            "digest": self.policy_loader.digest,
            "path": str(self.policy_loader.policy_path),
        }

    def _get_pipeline_info(self, project_root: Path) -> Dict[str, Any]:
        """Get pipeline digest and info."""
        pipeline_path = project_root / "pipeline.yaml"

        if not pipeline_path.exists():
            return {"error": "pipeline.yaml not found"}

        content = pipeline_path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()

        import yaml
        with open(pipeline_path, "r") as f:
            config = yaml.safe_load(f)

        return {
            "path": str(pipeline_path),
            "digest": digest,
            "pipeline_id": config.get("pipelineId", "unknown"),
            "link_count": len(config.get("links", [])),
        }

    def _get_link_digests(self, project_root: Path) -> Dict[str, Dict[str, str]]:
        """Get digests of all link.yaml files used in the pipeline."""
        link_digests = {}

        # Load pipeline to get link list
        pipeline_path = project_root / "pipeline.yaml"
        if not pipeline_path.exists():
            return link_digests

        import yaml
        with open(pipeline_path, "r") as f:
            config = yaml.safe_load(f)

        links = config.get("links", [])
        for link_info in links:
            link_id = link_info if isinstance(link_info, str) else link_info.get("id")
            link_yaml = self.links_dir / link_id / "link.yaml"

            if link_yaml.exists():
                content = link_yaml.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                link_digests[link_id] = {
                    "path": str(link_yaml),
                    "digest": digest,
                }
            else:
                link_digests[link_id] = {
                    "error": "link.yaml not found",
                }

        return link_digests

    def _get_environment_info(self) -> Dict[str, Any]:
        """Get Python and system environment info."""
        env_info = {
            "python_version": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "hostname": platform.node(),
        }

        # Get pip freeze (installed packages)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "freeze"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                packages = {}
                for line in result.stdout.strip().split("\n"):
                    if "==" in line:
                        name, version = line.split("==", 1)
                        packages[name] = version
                    elif line:
                        packages[line] = "unknown"
                env_info["pip_packages"] = packages
                env_info["pip_freeze_hash"] = hashlib.sha256(
                    result.stdout.encode()
                ).hexdigest()
        except Exception as e:
            env_info["pip_error"] = str(e)

        return env_info

    def _get_artifact_digests(self, project_root: Path) -> Dict[str, str]:
        """Get digests of key artifacts for verification."""
        artifact_digests = {}

        # Load artifact index
        index_path = project_root / "artifact_index.json"
        if index_path.exists():
            with open(index_path, "r") as f:
                index = json.load(f)
                for artifact_id, info in index.items():
                    artifact_digests[artifact_id] = info.get("digest", "unknown")

        return artifact_digests

    def save(self, project_id: str, lockfile: Optional[Dict] = None) -> Path:
        """Generate and save lockfile to project directory."""
        if lockfile is None:
            lockfile = self.generate(project_id)

        project_root = self.projects_dir / project_id
        lockfile_path = project_root / "dawn.lock.json"

        with open(lockfile_path, "w") as f:
            json.dump(lockfile, f, indent=2)

        return lockfile_path

    def load(self, project_id: str) -> Dict[str, Any]:
        """Load existing lockfile from project."""
        project_root = self.projects_dir / project_id
        lockfile_path = project_root / "dawn.lock.json"

        if not lockfile_path.exists():
            raise ValueError(f"Lockfile not found: {lockfile_path}")

        with open(lockfile_path, "r") as f:
            return json.load(f)


class LockfileVerifier:
    """Verifies that current environment matches a lockfile."""

    def __init__(self, projects_dir: str = "projects", links_dir: str = "dawn/links"):
        self.projects_dir = Path(projects_dir)
        self.links_dir = Path(links_dir)
        self.policy_loader = get_policy_loader()

    def verify(self, project_id: str) -> Dict[str, Any]:
        """Verify current environment against project's lockfile."""
        generator = LockfileGenerator(str(self.projects_dir), str(self.links_dir))

        # Load existing lockfile
        try:
            lockfile = generator.load(project_id)
        except ValueError as e:
            return {
                "verified": False,
                "error": str(e),
                "mismatches": []
            }

        # Generate current state
        current = generator.generate(project_id)

        # Compare
        mismatches = []

        # Check policy digest
        if lockfile.get("policy", {}).get("digest") != current.get("policy", {}).get("digest"):
            mismatches.append({
                "component": "policy",
                "field": "digest",
                "expected": lockfile.get("policy", {}).get("digest"),
                "actual": current.get("policy", {}).get("digest"),
            })

        # Check pipeline digest
        if lockfile.get("pipeline", {}).get("digest") != current.get("pipeline", {}).get("digest"):
            mismatches.append({
                "component": "pipeline",
                "field": "digest",
                "expected": lockfile.get("pipeline", {}).get("digest"),
                "actual": current.get("pipeline", {}).get("digest"),
            })

        # Check link digests
        for link_id, link_info in lockfile.get("links", {}).items():
            current_link = current.get("links", {}).get(link_id, {})
            if link_info.get("digest") != current_link.get("digest"):
                mismatches.append({
                    "component": f"link:{link_id}",
                    "field": "digest",
                    "expected": link_info.get("digest"),
                    "actual": current_link.get("digest"),
                })

        # Check Python version (major.minor only)
        expected_py = lockfile.get("environment", {}).get("python_version", "").split()[0]
        actual_py = current.get("environment", {}).get("python_version", "").split()[0]
        if expected_py and actual_py:
            expected_parts = expected_py.split(".")[:2]
            actual_parts = actual_py.split(".")[:2]
            if expected_parts != actual_parts:
                mismatches.append({
                    "component": "environment",
                    "field": "python_version",
                    "expected": ".".join(expected_parts),
                    "actual": ".".join(actual_parts),
                })

        return {
            "verified": len(mismatches) == 0,
            "lockfile_version": lockfile.get("lockfile_version"),
            "generated_at": lockfile.get("generated_at"),
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
        }

    def compare_lockfiles(self, lockfile1_path: str, lockfile2_path: str) -> Dict[str, Any]:
        """Compare two lockfiles."""
        with open(lockfile1_path, "r") as f:
            lf1 = json.load(f)
        with open(lockfile2_path, "r") as f:
            lf2 = json.load(f)

        differences = []

        # Compare all top-level keys
        all_keys = set(lf1.keys()) | set(lf2.keys())
        for key in all_keys:
            if key in ["generated_at"]:  # Skip timestamp
                continue

            v1 = lf1.get(key)
            v2 = lf2.get(key)

            if v1 != v2:
                differences.append({
                    "key": key,
                    "lockfile1": v1,
                    "lockfile2": v2,
                })

        return {
            "identical": len(differences) == 0,
            "difference_count": len(differences),
            "differences": differences,
        }


def main():
    parser = argparse.ArgumentParser(
        description="DAWN Reproducibility Lockfile Tool (Phase 9.3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate lockfile for a project
  python3 -m dawn.runtime.lockfile generate --project my_project

  # Verify current environment matches lockfile
  python3 -m dawn.runtime.lockfile verify --project my_project

  # Compare two lockfiles
  python3 -m dawn.runtime.lockfile compare lock1.json lock2.json

  # Output lockfile to stdout
  python3 -m dawn.runtime.lockfile generate --project my_project --stdout
        """
    )

    subparsers = parser.add_subparsers(dest="command")

    # Generate command
    gen_parser = subparsers.add_parser("generate", help="Generate lockfile")
    gen_parser.add_argument("--project", "-p", required=True, help="Project ID")
    gen_parser.add_argument("--projects-dir", default="projects")
    gen_parser.add_argument("--links-dir", default="dawn/links")
    gen_parser.add_argument("--stdout", action="store_true", help="Output to stdout instead of file")

    # Verify command
    ver_parser = subparsers.add_parser("verify", help="Verify lockfile")
    ver_parser.add_argument("--project", "-p", required=True, help="Project ID")
    ver_parser.add_argument("--projects-dir", default="projects")
    ver_parser.add_argument("--links-dir", default="dawn/links")

    # Compare command
    cmp_parser = subparsers.add_parser("compare", help="Compare two lockfiles")
    cmp_parser.add_argument("lockfile1", help="First lockfile path")
    cmp_parser.add_argument("lockfile2", help="Second lockfile path")

    args = parser.parse_args()

    if args.command == "generate":
        generator = LockfileGenerator(args.projects_dir, args.links_dir)
        lockfile = generator.generate(args.project)

        if args.stdout:
            print(json.dumps(lockfile, indent=2))
        else:
            path = generator.save(args.project, lockfile)
            print(f"Lockfile generated: {path}")
            print(f"  Policy digest: {lockfile['policy']['digest'][:16]}...")
            print(f"  Pipeline digest: {lockfile['pipeline'].get('digest', 'N/A')[:16]}...")
            print(f"  Links: {len(lockfile['links'])}")
            print(f"  Artifacts: {len(lockfile['artifact_digests'])}")

    elif args.command == "verify":
        verifier = LockfileVerifier(args.projects_dir, args.links_dir)
        result = verifier.verify(args.project)

        if result.get("verified"):
            print(f"✓ Lockfile verification PASSED")
            print(f"  Generated: {result.get('generated_at')}")
        else:
            print(f"✗ Lockfile verification FAILED")
            if result.get("error"):
                print(f"  Error: {result['error']}")
            else:
                print(f"  Mismatches: {result.get('mismatch_count')}")
                for m in result.get("mismatches", []):
                    print(f"    - {m['component']}.{m['field']}")
                    print(f"      Expected: {m['expected']}")
                    print(f"      Actual:   {m['actual']}")
            return 1

    elif args.command == "compare":
        verifier = LockfileVerifier()
        result = verifier.compare_lockfiles(args.lockfile1, args.lockfile2)

        if result.get("identical"):
            print("✓ Lockfiles are identical")
        else:
            print(f"✗ Lockfiles differ in {result.get('difference_count')} places")
            for d in result.get("differences", []):
                print(f"  - {d['key']}")

    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
