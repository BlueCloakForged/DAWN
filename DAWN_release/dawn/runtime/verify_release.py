"""
DAWN Release Verification Tool - Phase 9.4

Verifies the integrity of release bundles by:
- Recomputing all file digests
- Validating manifest integrity
- Checking for tampering or corruption

Usage:
    python3 -m dawn.runtime.verify_release <release.zip>
    python3 -m dawn.runtime.verify_release <release.zip> --extract-to /tmp/verify
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple


class ReleaseVerificationError(Exception):
    """Raised when release verification fails."""
    pass


class ReleaseVerifier:
    """Verifies integrity of DAWN release bundles."""

    def __init__(self):
        self.errors: List[Dict] = []
        self.warnings: List[Dict] = []
        self.verified_files: List[Dict] = []

    def verify(self, release_path: str, extract_to: Optional[str] = None) -> Dict[str, Any]:
        """
        Verify a release bundle.

        Args:
            release_path: Path to the release ZIP file
            extract_to: Optional directory to extract to (uses temp if not provided)

        Returns:
            Verification result dictionary
        """
        release_path = Path(release_path)

        if not release_path.exists():
            raise ReleaseVerificationError(f"Release file not found: {release_path}")

        if not zipfile.is_zipfile(release_path):
            raise ReleaseVerificationError(f"Not a valid ZIP file: {release_path}")

        # Use temp directory if not specified
        if extract_to:
            extract_dir = Path(extract_to)
            extract_dir.mkdir(parents=True, exist_ok=True)
            cleanup = False
        else:
            extract_dir = Path(tempfile.mkdtemp(prefix="dawn_verify_"))
            cleanup = True

        try:
            # Extract the release
            with zipfile.ZipFile(release_path, "r") as zf:
                zf.extractall(extract_dir)

            # Find the manifest
            manifest = self._find_and_load_manifest(extract_dir)

            if manifest is None:
                self.errors.append({
                    "type": "MISSING_MANIFEST",
                    "message": "No manifest.json found in release bundle"
                })
                return self._build_result(release_path, False)

            # Verify manifest integrity
            self._verify_manifest_structure(manifest)

            # Verify all files in manifest
            self._verify_files(extract_dir, manifest)

            # Check for extra files not in manifest
            self._check_extra_files(extract_dir, manifest)

            # Build result
            verified = len(self.errors) == 0
            return self._build_result(release_path, verified, manifest)

        finally:
            if cleanup and extract_dir.exists():
                import shutil
                shutil.rmtree(extract_dir)

    def _find_and_load_manifest(self, extract_dir: Path) -> Optional[Dict]:
        """Find and load the manifest file."""
        # Try common manifest locations
        manifest_paths = [
            extract_dir / "manifest.json",
            extract_dir / "release_manifest.json",
        ]

        # Also check one level deep (if release has a root folder)
        for subdir in extract_dir.iterdir():
            if subdir.is_dir():
                manifest_paths.extend([
                    subdir / "manifest.json",
                    subdir / "release_manifest.json",
                ])

        for path in manifest_paths:
            if path.exists():
                try:
                    with open(path, "r") as f:
                        return json.load(f)
                except json.JSONDecodeError as e:
                    self.errors.append({
                        "type": "INVALID_MANIFEST",
                        "message": f"Manifest is not valid JSON: {e}",
                        "path": str(path)
                    })
                    return None

        return None

    def _verify_manifest_structure(self, manifest: Dict):
        """Verify the manifest has required fields."""
        required_fields = ["version", "files"]

        for field in required_fields:
            if field not in manifest:
                self.errors.append({
                    "type": "MISSING_MANIFEST_FIELD",
                    "message": f"Manifest missing required field: {field}"
                })

    def _verify_files(self, extract_dir: Path, manifest: Dict):
        """Verify all files listed in manifest."""
        files = manifest.get("files", {})

        if isinstance(files, list):
            # Handle list format
            for file_info in files:
                self._verify_single_file(extract_dir, file_info)
        elif isinstance(files, dict):
            # Handle dict format
            for filename, file_info in files.items():
                if isinstance(file_info, str):
                    # Simple format: {"filename": "digest"}
                    file_info = {"path": filename, "digest": file_info}
                else:
                    file_info["path"] = file_info.get("path", filename)
                self._verify_single_file(extract_dir, file_info)

    def _verify_single_file(self, extract_dir: Path, file_info: Dict):
        """Verify a single file's integrity."""
        rel_path = file_info.get("path")
        expected_digest = file_info.get("digest") or file_info.get("sha256")

        if not rel_path:
            self.warnings.append({
                "type": "MISSING_PATH",
                "message": "File entry missing path",
                "info": file_info
            })
            return

        # Find the file (might be in a subdirectory)
        file_path = self._find_file(extract_dir, rel_path)

        if file_path is None:
            self.errors.append({
                "type": "MISSING_FILE",
                "message": f"File listed in manifest not found: {rel_path}",
                "expected_path": rel_path
            })
            return

        # Compute actual digest
        actual_digest = self._compute_digest(file_path)

        if expected_digest:
            # Normalize digest comparison (handle sha256: prefix)
            expected_clean = expected_digest.replace("sha256:", "").lower()
            actual_clean = actual_digest.lower()

            if expected_clean != actual_clean:
                self.errors.append({
                    "type": "DIGEST_MISMATCH",
                    "message": f"File digest mismatch: {rel_path}",
                    "path": rel_path,
                    "expected": expected_clean[:16] + "...",
                    "actual": actual_clean[:16] + "..."
                })
            else:
                self.verified_files.append({
                    "path": rel_path,
                    "digest": actual_digest,
                    "size": file_path.stat().st_size
                })
        else:
            self.warnings.append({
                "type": "NO_DIGEST",
                "message": f"No digest to verify for: {rel_path}",
                "path": rel_path
            })
            self.verified_files.append({
                "path": rel_path,
                "digest": actual_digest,
                "size": file_path.stat().st_size,
                "verified": False
            })

    def _find_file(self, extract_dir: Path, rel_path: str) -> Optional[Path]:
        """Find a file in the extract directory."""
        # Try direct path
        direct = extract_dir / rel_path
        if direct.exists():
            return direct

        # Try searching recursively
        for path in extract_dir.rglob(Path(rel_path).name):
            if str(path.relative_to(extract_dir)).endswith(rel_path):
                return path

        # Try without leading directory
        if "/" in rel_path:
            short_path = "/".join(rel_path.split("/")[1:])
            return self._find_file(extract_dir, short_path)

        return None

    def _compute_digest(self, file_path: Path) -> str:
        """Compute SHA256 digest of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _check_extra_files(self, extract_dir: Path, manifest: Dict):
        """Check for files not listed in manifest."""
        manifest_files = set()
        files = manifest.get("files", {})

        if isinstance(files, list):
            for f in files:
                if isinstance(f, dict):
                    manifest_files.add(f.get("path", ""))
                else:
                    manifest_files.add(str(f))
        elif isinstance(files, dict):
            for path, info in files.items():
                manifest_files.add(path)
                if isinstance(info, dict) and "path" in info:
                    manifest_files.add(info["path"])

        # Find all files in extract
        for path in extract_dir.rglob("*"):
            if path.is_file():
                rel_path = str(path.relative_to(extract_dir))

                # Skip manifest itself
                if "manifest.json" in rel_path:
                    continue

                # Check if in manifest
                if rel_path not in manifest_files:
                    # Try without root folder
                    short_path = "/".join(rel_path.split("/")[1:]) if "/" in rel_path else rel_path
                    if short_path not in manifest_files and rel_path not in manifest_files:
                        self.warnings.append({
                            "type": "EXTRA_FILE",
                            "message": f"File not in manifest: {rel_path}",
                            "path": rel_path
                        })

    def _build_result(
        self,
        release_path: Path,
        verified: bool,
        manifest: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Build the verification result."""
        return {
            "verified": verified,
            "release_path": str(release_path),
            "release_size": release_path.stat().st_size,
            "manifest_version": manifest.get("version") if manifest else None,
            "files_verified": len(self.verified_files),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": self.errors,
            "warnings": self.warnings,
            "verified_files": self.verified_files,
        }


def main():
    parser = argparse.ArgumentParser(
        description="DAWN Release Verification Tool (Phase 9.4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Verify a release bundle
  python3 -m dawn.runtime.verify_release release.zip

  # Verify and keep extracted files for inspection
  python3 -m dawn.runtime.verify_release release.zip --extract-to /tmp/verify

  # Output detailed JSON report
  python3 -m dawn.runtime.verify_release release.zip --json

Verification checks:
  - Manifest presence and validity
  - All manifest files exist
  - File digests match (SHA256)
  - No tampered or corrupted files
        """
    )

    parser.add_argument("release", help="Path to release ZIP file")
    parser.add_argument("--extract-to", "-e", help="Extract to directory (temp by default)")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON report")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode (exit code only)")

    args = parser.parse_args()

    try:
        verifier = ReleaseVerifier()
        result = verifier.verify(args.release, args.extract_to)

        if args.json:
            print(json.dumps(result, indent=2))
        elif not args.quiet:
            print(f"\n{'=' * 60}")
            print(f" DAWN Release Verification")
            print(f"{'=' * 60}\n")

            print(f"Release: {result['release_path']}")
            print(f"Size: {result['release_size'] / 1024:.1f} KB")

            if result.get("manifest_version"):
                print(f"Manifest Version: {result['manifest_version']}")

            print()

            if result["verified"]:
                print("✓ VERIFICATION PASSED")
                print(f"  Files verified: {result['files_verified']}")
            else:
                print("✗ VERIFICATION FAILED")
                print(f"  Errors: {result['error_count']}")

                for err in result.get("errors", []):
                    print(f"\n  [{err['type']}] {err['message']}")
                    if "expected" in err:
                        print(f"    Expected: {err['expected']}")
                        print(f"    Actual:   {err['actual']}")

            if result.get("warnings"):
                print(f"\n  Warnings: {result['warning_count']}")
                for warn in result.get("warnings", [])[:5]:
                    print(f"    - {warn['message']}")
                if len(result.get("warnings", [])) > 5:
                    print(f"    ... and {len(result['warnings']) - 5} more")

            print()

        return 0 if result["verified"] else 1

    except ReleaseVerificationError as e:
        if not args.quiet:
            print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        if not args.quiet:
            print(f"Unexpected error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    exit(main())
