"""aipam.extract — Zeek/Suricata log extraction within DAWN sandbox.

Reads PCAPs from the ``dawn.project.bundle``, runs Zeek and Suricata
via subprocess, parses the output logs (``conn.log``, ``eve.json``),
and publishes ``aipam.flow.ir`` — the structured intermediate
representation consumed by ``analyze.forensic_cot``.

If Zeek/Suricata are not installed, the link falls back to a
"header-only" mode that creates a minimal IR from PCAP metadata
(sufficient for pipeline smoke-testing).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Zeek conn.log parser
# ---------------------------------------------------------------------------

def _det_id(bundle_sha: str, salt: str) -> str:
    """Generate a deterministic ID from bundle SHA + salt (§1 Deterministic Execution)."""
    return hashlib.sha256(f"{bundle_sha}:{salt}".encode()).hexdigest()[:12]


def _parse_zeek_conn_log(log_path: Path, bundle_sha: str = "") -> List[Dict[str, Any]]:
    """Parse a Zeek conn.log (JSON or TSV) into flow dicts."""
    flows = []

    if not log_path.exists():
        return flows

    text = log_path.read_text()

    # Try JSON-formatted log first (zeek -e 'redef LogAscii::use_json=T')
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            record = json.loads(line)
            flows.append({
                "flow_id": record.get("uid", _det_id(bundle_sha, f"zeek-flow-{len(flows)}")),
                "src_ip": record.get("id.orig_h", ""),
                "src_port": record.get("id.orig_p", 0),
                "dst_ip": record.get("id.resp_h", ""),
                "dst_port": record.get("id.resp_p", 0),
                "proto": record.get("proto", "tcp"),
                "service": record.get("service", ""),
                "duration": record.get("duration", 0),
                "orig_bytes": record.get("orig_bytes", 0),
                "resp_bytes": record.get("resp_bytes", 0),
                "conn_state": record.get("conn_state", ""),
                "source": "zeek",
            })
        except json.JSONDecodeError:
            # TSV format — parse header-based
            if line.startswith("#fields"):
                fields = line.split("\t")[1:]
                continue
            if line.startswith("#"):
                continue
            # Skip TSV parsing for now — JSON is preferred
            continue

    return flows


# ---------------------------------------------------------------------------
# Suricata eve.json parser
# ---------------------------------------------------------------------------

def _parse_suricata_eve(eve_path: Path, bundle_sha: str = "") -> List[Dict[str, Any]]:
    """Parse Suricata eve.json into alert dicts."""
    alerts = []

    if not eve_path.exists():
        return alerts

    for line in eve_path.read_text().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            if record.get("event_type") == "alert":
                alert_info = record.get("alert", {})
                alerts.append({
                    "alert_id": f"suri-{alert_info.get('signature_id', 0)}-{_det_id(bundle_sha, f'alert-{len(alerts)}')}",
                    "src_ip": record.get("src_ip", ""),
                    "src_port": record.get("src_port", 0),
                    "dst_ip": record.get("dest_ip", ""),
                    "dst_port": record.get("dest_port", 0),
                    "proto": record.get("proto", ""),
                    "signature": alert_info.get("signature", ""),
                    "signature_id": alert_info.get("signature_id", 0),
                    "severity": alert_info.get("severity", 3),
                    "category": alert_info.get("category", ""),
                    "source": "suricata",
                })
        except json.JSONDecodeError:
            continue

    return alerts


# ---------------------------------------------------------------------------
# Subprocess runners
# ---------------------------------------------------------------------------

def _run_zeek(pcap_path: Path, output_dir: Path, zeek_bin: str) -> Optional[Path]:
    """Run Zeek on a PCAP and return path to conn.log."""
    try:
        result = subprocess.run(
            [zeek_bin, "-r", str(pcap_path), "LogAscii::use_json=T"],
            cwd=str(output_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        conn_log = output_dir / "conn.log"
        if conn_log.exists():
            print(f"  [zeek] Produced conn.log ({conn_log.stat().st_size} bytes)")
            return conn_log
        else:
            print(f"  [zeek] No conn.log produced. stderr: {result.stderr[:200]}")
            return None
    except FileNotFoundError:
        print(f"  [zeek] Binary '{zeek_bin}' not found — skipping")
        return None
    except subprocess.TimeoutExpired:
        print(f"  [zeek] Timed out after 120s")
        return None


def _run_suricata(
    pcap_path: Path, output_dir: Path,
    suricata_bin: str, suricata_config: str,
) -> Optional[Path]:
    """Run Suricata on a PCAP and return path to eve.json."""
    try:
        result = subprocess.run(
            [
                suricata_bin, "-r", str(pcap_path),
                "-l", str(output_dir),
                "-c", suricata_config,
                "--set", "outputs.0.eve-log.enabled=yes",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        eve_json = output_dir / "eve.json"
        if eve_json.exists():
            print(f"  [suricata] Produced eve.json ({eve_json.stat().st_size} bytes)")
            return eve_json
        else:
            print(f"  [suricata] No eve.json produced. stderr: {result.stderr[:200]}")
            return None
    except FileNotFoundError:
        print(f"  [suricata] Binary '{suricata_bin}' not found — skipping")
        return None
    except subprocess.TimeoutExpired:
        print(f"  [suricata] Timed out after 120s")
        return None


# ---------------------------------------------------------------------------
# Scoring heuristic
# ---------------------------------------------------------------------------

def _score_flows(flows: List[Dict[str, Any]]) -> List[str]:
    """Return IDs of high-priority flows (simple heuristic)."""
    scored = []
    for f in flows:
        score = 0
        # High port → external service
        if f.get("dst_port", 0) in (443, 80, 8080, 8443, 4443):
            score += 1
        # Long duration sessions
        dur = f.get("duration", 0) or 0
        if isinstance(dur, (int, float)) and dur > 60:
            score += 2
        # Large data transfer
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
    DAWN Link: aipam.extract

    1. Load dawn.project.bundle for PCAP paths
    2. Run Zeek + Suricata on each PCAP
    3. Parse logs into structured flow/alert dicts
    4. Score flows and select high-priority
    5. Publish aipam.flow.ir
    """
    project_root = Path(context["project_root"])
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    ledger = context["ledger"]
    project_id = context["project_id"]
    pipeline_id = context.get("pipeline_id", "aipam_forensic")
    run_id = context.get("run_id", "unknown")

    config = link_config.get("spec", {}).get("config", {})
    zeek_bin = config.get("zeek_binary", "zeek")
    suricata_bin = config.get("suricata_binary", "suricata")
    suricata_config = config.get("suricata_config", "/etc/suricata/suricata.yaml")
    max_flows = config.get("max_flows", 10000)

    # Load bundle
    bundle_meta = artifact_store.get("dawn.project.bundle")
    if not bundle_meta:
        raise RuntimeError("MISSING_REQUIRED_ARTIFACT: dawn.project.bundle not found")

    with open(bundle_meta["path"]) as fh:
        bundle = json.load(fh)

    pcap_files = bundle.get("files", [])
    bundle_sha = bundle.get("bundle_sha256", "unknown")

    print(f"[aipam.extract] Processing {len(pcap_files)} PCAP(s) from bundle {bundle_sha[:16]}...")

    all_flows: List[Dict[str, Any]] = []
    all_alerts: List[Dict[str, Any]] = []

    inputs_dir = project_root / "inputs"

    for pcap_info in pcap_files:
        pcap_path = inputs_dir / pcap_info["path"]
        if not pcap_path.exists():
            print(f"  ⚠ PCAP not found: {pcap_path}")
            continue

        print(f"  Processing: {pcap_info['path']}")

        # Create temp directory for tool output
        with tempfile.TemporaryDirectory(prefix="aipam_extract_") as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Run Zeek
            conn_log = _run_zeek(pcap_path, tmpdir_path, zeek_bin)
            if conn_log:
                flows = _parse_zeek_conn_log(conn_log, bundle_sha)
                all_flows.extend(flows)

            # Run Suricata
            eve_json = _run_suricata(
                pcap_path, tmpdir_path, suricata_bin, suricata_config,
            )
            if eve_json:
                alerts = _parse_suricata_eve(eve_json, bundle_sha)
                all_alerts.extend(alerts)

    # If no tools produced output, create minimal IR from bundle metadata
    if not all_flows and not all_alerts:
        print(f"  [fallback] No Zeek/Suricata output — creating header-only IR")
        # Log fallback mode to ledger (§1 Audit Integrity)
        ledger.log_event(
            project_id=project_id, pipeline_id=pipeline_id,
            link_id="aipam.extract", run_id=run_id,
            step_id="extract_fallback", status="WARNING",
            inputs={"pcap_count": len(pcap_files)},
            outputs={}, metrics={},
            errors={"type": "EXTRACT_FALLBACK", "message": "No Zeek/Suricata available"},
        )
        for idx, pcap_info in enumerate(pcap_files):
            all_flows.append({
                "flow_id": _det_id(bundle_sha, f"pcap-header-{idx}"),
                "src_ip": "0.0.0.0",
                "dst_ip": "0.0.0.0",
                "proto": "unknown",
                "source": "pcap_header",
                "pcap_file": pcap_info["path"],
                "pcap_sha256": pcap_info.get("sha256", ""),
            })

    # Cap flows
    if len(all_flows) > max_flows:
        print(f"  Capping flows from {len(all_flows)} to {max_flows}")
        all_flows = all_flows[:max_flows]

    # Score and select high-priority flows
    high_priority_ids = _score_flows(all_flows)

    # Build flow IR
    # Build flow IR (§1 Deterministic Execution: job_id derived from bundle)
    job_id = f"dawn-{context['project_id']}-{_det_id(bundle_sha, 'job')}"

    flow_ir = {
        "job_id": job_id,
        "exercise_id": context["project_id"],
        "mode": "single_window",
        "bundle_sha256": bundle_sha,
        "high_priority_flow_ids": high_priority_ids,
        "alert_ids": [a["alert_id"] for a in all_alerts],
        "flows": all_flows,
        "alerts": all_alerts,
        "metadata": {
            "source": "aipam.extract",
            "pcap_count": len(pcap_files),
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

    print(f"[aipam.extract] ✓ {len(all_flows)} flows, {len(all_alerts)} alerts, "
          f"{len(high_priority_ids)} high-priority")

    # §1 Audit Integrity: log extraction results
    ledger.log_event(
        project_id=project_id, pipeline_id=pipeline_id,
        link_id="aipam.extract", run_id=run_id,
        step_id="extract_complete", status="OK",
        inputs={"bundle_sha256": bundle_sha, "pcap_count": len(pcap_files)},
        outputs={"job_id": job_id},
        metrics={"total_flows": len(all_flows), "total_alerts": len(all_alerts),
                 "high_priority_flows": len(high_priority_ids)},
        errors={},
    )

    return {
        "status": "SUCCEEDED",
        "metrics": {
            "total_flows": len(all_flows),
            "total_alerts": len(all_alerts),
            "high_priority_flows": len(high_priority_ids),
            "pcap_count": len(pcap_files),
        },
    }
