"""aipam.ingest.pcap — Source-agnostic PCAP ingest link.

Validates PCAP files from ``inputs/``, runs Zeek/Suricata for feature
extraction, computes provenance hashes, and publishes the unified
``aipam.flow.ir`` intermediate representation.

This link merges the old aipam.ingest + aipam.extract logic into a
single source-to-IR step, so that all three ingest variants
(pcap, security_onion, arkime) produce the identical schema.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# PCAP validation
# ---------------------------------------------------------------------------

PCAP_LE = b"\xd4\xc3\xb2\xa1"
PCAP_BE = b"\xa1\xb2\xc3\xd4"
PCAPNG_SHB = b"\x0a\x0d\x0d\x0a"
VALID_MAGICS = {PCAP_LE: "pcap_le", PCAP_BE: "pcap_be", PCAPNG_SHB: "pcapng"}


def _validate_pcap(path: Path) -> Optional[str]:
    try:
        with open(path, "rb") as fh:
            header = fh.read(4)
        return VALID_MAGICS.get(header)
    except OSError:
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _det_id(bundle_sha: str, salt: str) -> str:
    return hashlib.sha256(f"{bundle_sha}:{salt}".encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Zeek / Suricata parsers (inlined for self-containment)
# ---------------------------------------------------------------------------

def _parse_zeek_conn_log(log_path: Path, bundle_sha: str = "") -> List[Dict[str, Any]]:
    flows = []
    if not log_path.exists():
        return flows
    for line in log_path.read_text().strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            r = json.loads(line)
            flows.append({
                "flow_id": r.get("uid", _det_id(bundle_sha, f"zeek-flow-{len(flows)}")),
                "src_ip": r.get("id.orig_h", ""),
                "src_port": r.get("id.orig_p", 0),
                "dst_ip": r.get("id.resp_h", ""),
                "dst_port": r.get("id.resp_p", 0),
                "proto": r.get("proto", "tcp"),
                "service": r.get("service", ""),
                "duration": r.get("duration", 0),
                "orig_bytes": r.get("orig_bytes", 0),
                "resp_bytes": r.get("resp_bytes", 0),
                "conn_state": r.get("conn_state", ""),
                "source": "zeek",
            })
        except json.JSONDecodeError:
            continue
    return flows


def _parse_suricata_eve(eve_path: Path, bundle_sha: str = "") -> List[Dict[str, Any]]:
    alerts = []
    if not eve_path.exists():
        return alerts
    for line in eve_path.read_text().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("event_type") == "alert":
                a = r.get("alert", {})
                alerts.append({
                    "alert_id": f"suri-{a.get('signature_id', 0)}-{_det_id(bundle_sha, f'alert-{len(alerts)}')}",
                    "src_ip": r.get("src_ip", ""),
                    "src_port": r.get("src_port", 0),
                    "dst_ip": r.get("dest_ip", ""),
                    "dst_port": r.get("dest_port", 0),
                    "proto": r.get("proto", ""),
                    "signature": a.get("signature", ""),
                    "signature_id": a.get("signature_id", 0),
                    "severity": a.get("severity", 3),
                    "category": a.get("category", ""),
                    "source": "suricata",
                })
        except json.JSONDecodeError:
            continue
    return alerts


# ---------------------------------------------------------------------------
# Tool runners
# ---------------------------------------------------------------------------

def _run_zeek(pcap: Path, out_dir: Path, binary: str) -> Optional[Path]:
    try:
        subprocess.run(
            [binary, "-r", str(pcap), "LogAscii::use_json=T"],
            cwd=str(out_dir), capture_output=True, text=True, timeout=120,
        )
        conn = out_dir / "conn.log"
        return conn if conn.exists() else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _run_suricata(pcap: Path, out_dir: Path, binary: str, config: str) -> Optional[Path]:
    try:
        subprocess.run(
            [binary, "-r", str(pcap), "-l", str(out_dir), "-c", config,
             "--set", "outputs.0.eve-log.enabled=yes"],
            capture_output=True, text=True, timeout=120,
        )
        eve = out_dir / "eve.json"
        return eve if eve.exists() else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


# ---------------------------------------------------------------------------
# Scoring heuristic
# ---------------------------------------------------------------------------

def _score_flows(flows: List[Dict[str, Any]]) -> List[str]:
    scored = []
    for f in flows:
        score = 0
        if f.get("dst_port", 0) in (443, 80, 8080, 8443, 4443):
            score += 1
        dur = f.get("duration", 0) or 0
        if isinstance(dur, (int, float)) and dur > 60:
            score += 2
        resp = f.get("resp_bytes", 0) or 0
        if isinstance(resp, (int, float)) and resp > 100000:
            score += 1
        if score >= 2:
            scored.append(f["flow_id"])
    return scored


# ---------------------------------------------------------------------------
# DAWN entry point
# ---------------------------------------------------------------------------

def run(context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    DAWN Link: aipam.ingest.pcap

    1. Scan inputs/ for PCAP files, validate magic bytes
    2. Compute provenance bundle
    3. Run Zeek + Suricata on each PCAP
    4. Parse into unified aipam.flow.ir
    5. Publish both dawn.project.bundle and aipam.flow.ir
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
    sensitivity = config.get("sensitivity", "LOW").upper()
    zeek_bin = config.get("zeek_binary", "zeek")
    suricata_bin = config.get("suricata_binary", "suricata")
    suricata_cfg = config.get("suricata_config", "/etc/suricata/suricata.yaml")
    max_flows = config.get("max_flows", 10000)

    if not inputs_dir.exists():
        raise FileNotFoundError(f"Inputs directory not found: {inputs_dir}")

    print(f"[aipam.ingest.pcap] Scanning {inputs_dir}  sensitivity={sensitivity}")

    # ── Step 1: Validate PCAPs ────────────────────────────────────────────
    files = []
    rejected = []

    for file_path in sorted(inputs_dir.rglob("*")):
        if not file_path.is_file() or file_path.name.startswith("."):
            continue
        rel = file_path.relative_to(inputs_dir).as_posix()
        if file_path.suffix.lower() not in allowed_ext:
            rejected.append({"path": rel, "reason": f"extension not allowed"})
            continue
        size = file_path.stat().st_size
        if size > max_size_bytes:
            rejected.append({"path": rel, "reason": f"exceeds {max_size_mb}MB"})
            continue
        fmt = _validate_pcap(file_path)
        if fmt is None:
            rejected.append({"path": rel, "reason": "invalid PCAP magic bytes"})
            continue
        files.append({
            "path": rel,
            "uri": file_path.absolute().as_uri(),
            "bytes": size,
            "sha256": _sha256(file_path),
            "format": fmt,
        })

    if not files:
        raise RuntimeError(f"No valid PCAPs in {inputs_dir}")

    files.sort(key=lambda f: f["path"])
    canonical = "\n".join(f"{f['path']}:{f['sha256']}:{f['bytes']}" for f in files)
    bundle_sha = hashlib.sha256(canonical.encode()).hexdigest()

    # ── Step 2: Publish provenance bundle ─────────────────────────────────
    manifest = {
        "schema_version": "1.1.0",
        "bundle_sha256": bundle_sha,
        "root": "inputs",
        "files": files,
        "rejected": rejected,
        "meta_bundle": {"source": "aipam.ingest.pcap", "pcap_count": len(files)},
    }
    sandbox.publish(
        artifact="dawn.project.bundle",
        filename="dawn.project.bundle.json",
        obj=manifest,
        schema="json",
    )

    # ── Step 3: Run Zeek + Suricata on each PCAP ─────────────────────────
    all_flows: List[Dict[str, Any]] = []
    all_alerts: List[Dict[str, Any]] = []

    for pcap_info in files:
        pcap_path = inputs_dir / pcap_info["path"]
        print(f"  Processing: {pcap_info['path']}")

        with tempfile.TemporaryDirectory(prefix="aipam_pcap_") as tmpdir:
            tmp = Path(tmpdir)
            conn_log = _run_zeek(pcap_path, tmp, zeek_bin)
            if conn_log:
                all_flows.extend(_parse_zeek_conn_log(conn_log, bundle_sha))
            eve_json = _run_suricata(pcap_path, tmp, suricata_bin, suricata_cfg)
            if eve_json:
                all_alerts.extend(_parse_suricata_eve(eve_json, bundle_sha))

    # Fallback: header-only IR if no tools available
    if not all_flows and not all_alerts:
        print("  [fallback] No Zeek/Suricata — creating header-only IR")
        for idx, f in enumerate(files):
            all_flows.append({
                "flow_id": _det_id(bundle_sha, f"pcap-header-{idx}"),
                "src_ip": "0.0.0.0", "dst_ip": "0.0.0.0",
                "proto": "unknown", "source": "pcap_header",
                "pcap_file": f["path"], "pcap_sha256": f.get("sha256", ""),
            })

    if len(all_flows) > max_flows:
        all_flows = all_flows[:max_flows]

    high_priority_ids = _score_flows(all_flows)

    # ── Step 4: Publish aipam.flow.ir ─────────────────────────────────────
    job_id = f"dawn-{project_id}-{_det_id(bundle_sha, 'job')}"

    flow_ir = {
        "job_id": job_id,
        "exercise_id": project_id,
        "mode": "single_window",
        "source_type": "pcap",
        "sensitivity": sensitivity,
        "bundle_sha256": bundle_sha,
        "high_priority_flow_ids": high_priority_ids,
        "alert_ids": [a["alert_id"] for a in all_alerts],
        "flows": all_flows,
        "alerts": all_alerts,
        "metadata": {
            "source": "aipam.ingest.pcap",
            "pcap_count": len(files),
            "total_flows": len(all_flows),
            "total_alerts": len(all_alerts),
        },
    }

    sandbox.publish(
        artifact="aipam.flow.ir",
        filename="flow_ir.json",
        obj=flow_ir,
        schema="json",
    )

    # ── Audit ─────────────────────────────────────────────────────────────
    ledger.log_event(
        project_id=project_id, pipeline_id=pipeline_id,
        link_id="aipam.ingest.pcap", run_id=run_id,
        step_id="ingest_bundle", status="OK",
        inputs={"inputs_dir": str(inputs_dir), "sensitivity": sensitivity},
        outputs={"bundle_sha256": bundle_sha, "job_id": job_id},
        metrics={"pcap_count": len(files), "total_flows": len(all_flows),
                 "total_alerts": len(all_alerts), "rejected": len(rejected)},
        errors={},
    )

    print(f"[aipam.ingest.pcap] ✓ {len(all_flows)} flows, {len(all_alerts)} alerts, "
          f"sensitivity={sensitivity}")

    return {
        "status": "SUCCEEDED",
        "metrics": {
            "pcap_count": len(files),
            "total_flows": len(all_flows),
            "total_alerts": len(all_alerts),
            "high_priority_flows": len(high_priority_ids),
            "sensitivity": sensitivity,
        },
    }
