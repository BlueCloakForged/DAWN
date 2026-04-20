"""aipam.ingest — PCAP validation and bundle registration.

Scans ``inputs/`` for PCAP/PCAPNG files, validates magic bytes,
computes SHA256 digests, and publishes a deterministic
``dawn.project.bundle`` manifest.

Magic bytes checked:
  - PCAP classic:  ``d4 c3 b2 a1`` (LE) or ``a1 b2 c3 d4`` (BE)
  - PCAPNG:        ``0a 0d 0d 0a`` (Section Header Block)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# PCAP magic byte signatures
PCAP_LE = b"\xd4\xc3\xb2\xa1"
PCAP_BE = b"\xa1\xb2\xc3\xd4"
PCAPNG_SHB = b"\x0a\x0d\x0d\x0a"

VALID_MAGICS = {
    PCAP_LE: "pcap_le",
    PCAP_BE: "pcap_be",
    PCAPNG_SHB: "pcapng",
}


def _validate_pcap(path: Path) -> Optional[str]:
    """Return format name if valid PCAP, else None."""
    try:
        with open(path, "rb") as fh:
            header = fh.read(4)
        return VALID_MAGICS.get(header)
    except OSError:
        return None


def _sha256(path: Path) -> str:
    """Compute SHA256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run(context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    DAWN Link: aipam.ingest

    1. Scan inputs/ for PCAP files
    2. Validate magic bytes
    3. Compute deterministic bundle manifest
    4. Publish dawn.project.bundle
    5. Log INGEST_BUNDLE / INGEST_REJECTED to ledger
    """
    project_root = Path(context["project_root"])
    sandbox = context["sandbox"]
    ledger = context["ledger"]
    project_id = context["project_id"]
    pipeline_id = context.get("pipeline_id", "aipam_forensic")
    run_id = context.get("run_id", "unknown")
    inputs_dir = project_root / "inputs"

    config = link_config.get("spec", {}).get("config", {})
    allowed_ext = set(config.get("allowed_extensions", [".pcap", ".pcapng", ".cap"]))
    max_size_mb = config.get("max_file_size_mb", 500)
    max_size_bytes = max_size_mb * 1024 * 1024

    if not inputs_dir.exists():
        raise FileNotFoundError(f"Inputs directory not found: {inputs_dir}")

    print(f"[aipam.ingest] Scanning {inputs_dir}")

    files: List[Dict[str, Any]] = []
    rejected: List[Dict[str, str]] = []

    for file_path in sorted(inputs_dir.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.name.startswith(".") or file_path.name.startswith("hitl_"):
            continue

        rel_path = file_path.relative_to(inputs_dir).as_posix()
        suffix = file_path.suffix.lower()

        # Check extension
        if suffix not in allowed_ext:
            rejected.append({"path": rel_path, "reason": f"extension {suffix} not allowed"})
            continue

        # Check size
        size = file_path.stat().st_size
        if size > max_size_bytes:
            rejected.append({"path": rel_path, "reason": f"size {size} exceeds {max_size_mb}MB"})
            continue

        # Validate magic bytes
        fmt = _validate_pcap(file_path)
        if fmt is None:
            rejected.append({"path": rel_path, "reason": "invalid PCAP magic bytes"})
            continue

        file_sha = _sha256(file_path)

        files.append({
            "path": rel_path,
            "uri": file_path.absolute().as_uri(),
            "bytes": size,
            "sha256": file_sha,
            "format": fmt,
        })

    if not files:
        raise RuntimeError(
            f"No valid PCAP files found in {inputs_dir}. "
            f"Rejected: {json.dumps(rejected, indent=2)}"
        )

    # Sort for determinism
    files.sort(key=lambda f: f["path"])

    # Compute bundle SHA256 from canonical representation
    canonical_parts = [f"{f['path']}:{f['sha256']}:{f['bytes']}" for f in files]
    canonical_str = "\n".join(canonical_parts)
    bundle_sha256 = hashlib.sha256(canonical_str.encode()).hexdigest()

    manifest = {
        "schema_version": "1.1.0",
        "bundle_sha256": bundle_sha256,
        "root": "inputs",
        "files": files,
        "rejected": rejected,
        "meta_bundle": {
            "source": "aipam.ingest",
            "pcap_count": len(files),
        },
    }

    sandbox.publish(
        artifact="dawn.project.bundle",
        filename="dawn.project.bundle.json",
        obj=manifest,
        schema="json",
    )

    # §1 Audit Integrity: log bundle registration to ledger
    ledger.log_event(
        project_id=project_id,
        pipeline_id=pipeline_id,
        link_id="aipam.ingest",
        run_id=run_id,
        step_id="ingest_bundle",
        status="OK",
        inputs={"inputs_dir": str(inputs_dir)},
        outputs={"bundle_sha256": bundle_sha256, "files_bundled": len(files)},
        metrics={"pcap_count": len(files), "rejected_count": len(rejected)},
        errors={},
    )

    # Log rejections as individual audit events
    for rej in rejected:
        ledger.log_event(
            project_id=project_id,
            pipeline_id=pipeline_id,
            link_id="aipam.ingest",
            run_id=run_id,
            step_id="ingest_rejected",
            status="WARNING",
            inputs={"path": rej["path"]},
            outputs={},
            metrics={},
            errors={"type": "INGEST_REJECTED", "message": rej["reason"]},
        )

    print(f"[aipam.ingest] ✓ Bundled {len(files)} PCAP(s), "
          f"rejected {len(rejected)}, sha256={bundle_sha256[:16]}...")

    return {
        "status": "SUCCEEDED",
        "metrics": {
            "files_bundled": len(files),
            "files_rejected": len(rejected),
            "bundle_sha256": bundle_sha256,
        },
    }
