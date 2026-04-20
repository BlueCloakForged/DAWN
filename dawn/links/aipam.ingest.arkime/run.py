"""aipam.ingest.arkime — Source-agnostic Arkime ingest link.

Queries the Arkime API (``/api/sessions.pcap``), downloads matching
PCAPs for the filter expression, runs Zeek/Suricata, and produces
the unified ``aipam.flow.ir`` intermediate representation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _det_id(bundle_sha: str, salt: str) -> str:
    return hashlib.sha256(f"{bundle_sha}:{salt}".encode()).hexdigest()[:12]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Zeek / Suricata parsers (identical schema to other ingest links)
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
# Arkime API
# ---------------------------------------------------------------------------

async def _fetch_arkime_pcap(
    api_url: str,
    username: str,
    password: str,
    flt: str,
    time_range: Dict[str, str],
) -> bytes:
    """Fetch sessions.pcap from Arkime API."""
    if not api_url:
        return b""
    params: Dict[str, str] = {}
    if flt:
        params["expression"] = flt
    auth = (username, password) if username and password else None
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(
            f"{api_url}/api/sessions.pcap",
            params=params,
            auth=auth,
        )
        resp.raise_for_status()
        return resp.content


# ---------------------------------------------------------------------------
# DAWN entry point
# ---------------------------------------------------------------------------

def run(context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    DAWN Link: aipam.ingest.arkime

    1. Query Arkime API for session PCAPs
    2. Run Zeek + Suricata on downloaded PCAPs
    3. Publish dawn.project.bundle + aipam.flow.ir
    """
    project_root = Path(context["project_root"])
    sandbox = context["sandbox"]
    ledger = context["ledger"]
    project_id = context["project_id"]
    pipeline_id = context.get("pipeline_id", "aipam_forensic")
    run_id = context.get("run_id", "unknown")

    config = link_config.get("spec", {}).get("config", {})
    sensitivity = config.get("sensitivity", "LOW").upper()
    api_url = config.get("api_url", "")
    username = config.get("api_username", "")
    password = config.get("api_password", "")
    flt = config.get("filter", "")
    time_range = config.get("time_range", {})
    zeek_bin = config.get("zeek_binary", "zeek")
    suricata_bin = config.get("suricata_binary", "suricata")
    suricata_cfg = config.get("suricata_config", "/etc/suricata/suricata.yaml")
    max_flows = config.get("max_flows", 10000)

    print(f"[aipam.ingest.arkime] filter={flt!r}  sensitivity={sensitivity}")

    # ── Step 1: Fetch PCAPs from Arkime ───────────────────────────────────
    blob = asyncio.run(
        _fetch_arkime_pcap(api_url, username, password, flt, time_range)
    )

    all_flows: List[Dict[str, Any]] = []
    all_alerts: List[Dict[str, Any]] = []
    pcap_files_info: List[Dict[str, Any]] = []

    if blob:
        inputs_dir = project_root / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        pcap_dest = inputs_dir / "arkime.pcap"
        pcap_dest.write_bytes(blob)

        pcap_sha = _sha256(pcap_dest)
        pcap_files_info.append({
            "path": "arkime.pcap",
            "bytes": len(blob),
            "sha256": pcap_sha,
            "format": "pcap",
        })

        # ── Step 2: Extract features ──────────────────────────────────────
        with tempfile.TemporaryDirectory(prefix="ark_extract_") as tmp:
            tmp_path = Path(tmp)
            conn_log = _run_zeek(pcap_dest, tmp_path, zeek_bin)
            if conn_log:
                all_flows.extend(_parse_zeek_conn_log(conn_log, pcap_sha))
            eve_json = _run_suricata(pcap_dest, tmp_path, suricata_bin, suricata_cfg)
            if eve_json:
                all_alerts.extend(_parse_suricata_eve(eve_json, pcap_sha))

    # ── Fallback ──────────────────────────────────────────────────────────
    if not all_flows and not all_alerts:
        print("  [fallback] No data from Arkime — creating placeholder IR")
        all_flows.append({
            "flow_id": _det_id("ark-fallback", "ark-header-0"),
            "src_ip": "0.0.0.0", "dst_ip": "0.0.0.0",
            "proto": "unknown", "source": "arkime_fallback",
        })

    if len(all_flows) > max_flows:
        all_flows = all_flows[:max_flows]

    high_priority_ids = _score_flows(all_flows)

    # ── Provenance bundle ─────────────────────────────────────────────────
    canonical_parts = []
    for f in sorted(pcap_files_info, key=lambda x: x.get("path", "")):
        canonical_parts.append(f"{f.get('path', '')}:{f.get('sha256', '')}:{f.get('bytes', 0)}")
    if not canonical_parts:
        canonical_parts.append(f"ark-ingest:{project_id}:{len(all_flows)}")
    bundle_sha = hashlib.sha256("\n".join(canonical_parts).encode()).hexdigest()

    manifest = {
        "schema_version": "1.1.0",
        "bundle_sha256": bundle_sha,
        "root": "arkime",
        "files": pcap_files_info,
        "rejected": [],
        "meta_bundle": {
            "source": "aipam.ingest.arkime",
            "filter": flt,
            "pcap_count": len(pcap_files_info),
        },
    }
    sandbox.publish(
        artifact="dawn.project.bundle",
        filename="dawn.project.bundle.json",
        obj=manifest,
        schema="json",
    )

    # ── Publish aipam.flow.ir ─────────────────────────────────────────────
    job_id = f"dawn-{project_id}-{_det_id(bundle_sha, 'job')}"

    flow_ir = {
        "job_id": job_id,
        "exercise_id": project_id,
        "mode": "single_window",
        "source_type": "arkime",
        "sensitivity": sensitivity,
        "bundle_sha256": bundle_sha,
        "high_priority_flow_ids": high_priority_ids,
        "alert_ids": [a["alert_id"] for a in all_alerts],
        "flows": all_flows,
        "alerts": all_alerts,
        "metadata": {
            "source": "aipam.ingest.arkime",
            "filter": flt,
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
        link_id="aipam.ingest.arkime", run_id=run_id,
        step_id="ingest_bundle", status="OK",
        inputs={"filter": flt, "sensitivity": sensitivity},
        outputs={"bundle_sha256": bundle_sha, "job_id": job_id},
        metrics={"total_flows": len(all_flows), "total_alerts": len(all_alerts)},
        errors={},
    )

    print(f"[aipam.ingest.arkime] ✓ {len(all_flows)} flows, {len(all_alerts)} alerts, "
          f"sensitivity={sensitivity}")

    return {
        "status": "SUCCEEDED",
        "metrics": {
            "total_flows": len(all_flows),
            "total_alerts": len(all_alerts),
            "high_priority_flows": len(high_priority_ids),
            "sensitivity": sensitivity,
        },
    }
