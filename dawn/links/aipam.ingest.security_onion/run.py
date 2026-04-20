"""aipam.ingest.security_onion — Source-agnostic Security Onion ingest.

Connects to Security Onion via API or filesystem mode, pulls PCAP/log
data for the specified time range and sensors, runs Zeek/Suricata (or
parses existing SO Zeek logs), and produces the unified ``aipam.flow.ir``
intermediate representation.

Modes
-----
* **filesystem**: Reads PCAPs from ``base_pcap_path`` and pre-existing
  Zeek logs from ``zeek_log_path``.  Uses sensor subdirectories and
  file mtime filtering for time range.
* **api**: Calls the SO REST API endpoint, paginating via ``Link`` headers,
  then runs Zeek/Suricata on the downloaded PCAPs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx


# ---------------------------------------------------------------------------
# Deterministic ID helper
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
# Zeek / Suricata parsers (same schema as aipam.ingest.pcap)
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
# Security Onion — Filesystem mode helpers
# ---------------------------------------------------------------------------

def _parse_iso8601(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _find_so_pcaps(
    base_path: Path,
    time_range: Dict[str, str],
    sensors: List[str],
) -> List[Path]:
    """Locate PCAPs from SO filesystem filtered by sensors and time range."""
    start = _parse_iso8601(time_range.get("start", ""))
    end = _parse_iso8601(time_range.get("end", ""))

    search_roots: List[Path] = []
    if sensors:
        for sensor in sensors:
            d = base_path / sensor
            if d.is_dir():
                search_roots.append(d)
    if not search_roots and base_path.is_dir():
        search_roots.append(base_path)
        for child in base_path.iterdir():
            if child.is_dir():
                search_roots.append(child)

    results: List[Path] = []
    for root in search_roots:
        for pcap in root.rglob("*.pcap"):
            try:
                mtime = datetime.fromtimestamp(pcap.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if start and mtime < start:
                continue
            if end and mtime > end:
                continue
            results.append(pcap)
    return sorted(results)


def _find_so_zeek_logs(
    zeek_log_path: Path,
    time_range: Dict[str, str],
) -> List[Path]:
    """Find pre-existing SO Zeek conn.log files in the log directory."""
    start = _parse_iso8601(time_range.get("start", ""))
    end = _parse_iso8601(time_range.get("end", ""))
    results: List[Path] = []
    if not zeek_log_path.is_dir():
        return results
    for log in zeek_log_path.rglob("conn.log"):
        try:
            mtime = datetime.fromtimestamp(log.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if start and mtime < start:
            continue
        if end and mtime > end:
            continue
        results.append(log)
    return sorted(results)


def _find_so_suricata_logs(
    suricata_log_path: Path,
    time_range: Dict[str, str],
) -> List[Path]:
    """Find pre-existing SO Suricata eve.json files."""
    start = _parse_iso8601(time_range.get("start", ""))
    end = _parse_iso8601(time_range.get("end", ""))
    results: List[Path] = []
    if not suricata_log_path.is_dir():
        return results
    for log in suricata_log_path.rglob("eve.json"):
        try:
            mtime = datetime.fromtimestamp(log.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if start and mtime < start:
            continue
        if end and mtime > end:
            continue
        results.append(log)
    return sorted(results)


# ---------------------------------------------------------------------------
# Security Onion — API mode helpers
# ---------------------------------------------------------------------------

async def _fetch_so_api(api_url: str, api_token: str,
                        time_range: Dict[str, str],
                        sensors: List[str]) -> List[bytes]:
    """Fetch PCAP bytes from the Security Onion REST API."""
    if not api_url or not api_token:
        return []

    params: Dict[str, object] = {}
    if time_range:
        if time_range.get("start"):
            params["start"] = time_range["start"]
        if time_range.get("end"):
            params["end"] = time_range["end"]
    if sensors:
        params["sensor"] = sensors

    headers = {"Authorization": f"Bearer {api_token}"}
    blobs: List[bytes] = []
    url: Optional[str] = api_url

    async with httpx.AsyncClient(timeout=60) as client:
        while url:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            if resp.content:
                blobs.append(resp.content)
            params = {}
            next_link = getattr(resp, "links", None) or {}
            next_info = next_link.get("next") if isinstance(next_link, dict) else None
            url = next_info.get("url") if isinstance(next_info, dict) else None

    return blobs


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
    DAWN Link: aipam.ingest.security_onion

    1. Determine mode (filesystem vs API)
    2. Acquire PCAP/log data from Security Onion
    3. Parse Zeek/Suricata output into flows + alerts
    4. Publish dawn.project.bundle + aipam.flow.ir
    """
    project_root = Path(context["project_root"])
    sandbox = context["sandbox"]
    ledger = context["ledger"]
    project_id = context["project_id"]
    pipeline_id = context.get("pipeline_id", "aipam_forensic")
    run_id = context.get("run_id", "unknown")

    config = link_config.get("spec", {}).get("config", {})
    sensitivity = config.get("sensitivity", "LOW").upper()
    mode = config.get("mode", "filesystem")
    api_url = config.get("api_url", "")
    api_token = config.get("api_token", "")
    base_pcap_path = Path(config.get("base_pcap_path", "/opt/so/pcap"))
    zeek_log_path = Path(config.get("zeek_log_path", "/opt/so/log/zeek"))
    suricata_log_path = Path(config.get("suricata_log_path", "/opt/so/log/suricata"))
    time_range = config.get("time_range", {})
    sensors = config.get("sensors", [])
    zeek_bin = config.get("zeek_binary", "zeek")
    suricata_bin = config.get("suricata_binary", "suricata")
    suricata_cfg = config.get("suricata_config", "/etc/suricata/suricata.yaml")
    max_flows = config.get("max_flows", 10000)

    print(f"[aipam.ingest.security_onion] mode={mode}  sensitivity={sensitivity}")

    all_flows: List[Dict[str, Any]] = []
    all_alerts: List[Dict[str, Any]] = []
    pcap_files_info: List[Dict[str, Any]] = []

    if mode == "filesystem":
        # ── Filesystem: parse existing SO Zeek/Suricata logs directly ─────
        print(f"  Scanning SO filesystem: pcap={base_pcap_path}")

        # Try pre-existing Zeek logs first
        zeek_logs = _find_so_zeek_logs(zeek_log_path, time_range)
        for zlog in zeek_logs:
            print(f"    Parsing Zeek log: {zlog}")
            all_flows.extend(_parse_zeek_conn_log(zlog, ""))

        # Try pre-existing Suricata logs
        suri_logs = _find_so_suricata_logs(suricata_log_path, time_range)
        for slog in suri_logs:
            print(f"    Parsing Suricata log: {slog}")
            all_alerts.extend(_parse_suricata_eve(slog, ""))

        # Also find raw PCAPs and run tools if logs are sparse
        pcaps = _find_so_pcaps(base_pcap_path, time_range, sensors)
        for pcap in pcaps:
            pcap_files_info.append({
                "path": str(pcap.relative_to(base_pcap_path)),
                "bytes": pcap.stat().st_size,
                "sha256": _sha256(pcap),
                "format": "pcap",
            })
            if not all_flows:
                with tempfile.TemporaryDirectory(prefix="so_zeek_") as tmp:
                    conn_log = _run_zeek(pcap, Path(tmp), zeek_bin)
                    if conn_log:
                        all_flows.extend(_parse_zeek_conn_log(conn_log, ""))
            if not all_alerts:
                with tempfile.TemporaryDirectory(prefix="so_suri_") as tmp:
                    eve = _run_suricata(pcap, Path(tmp), suricata_bin, suricata_cfg)
                    if eve:
                        all_alerts.extend(_parse_suricata_eve(eve, ""))

    elif mode == "api":
        # ── API mode: fetch PCAPs from SO REST endpoint ───────────────────
        print(f"  Fetching from SO API: {api_url}")
        blobs = asyncio.run(_fetch_so_api(api_url, api_token, time_range, sensors))

        inputs_dir = project_root / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)

        for idx, blob in enumerate(blobs):
            dest = inputs_dir / f"so_{idx}.pcap"
            dest.write_bytes(blob)
            pcap_files_info.append({
                "path": dest.name,
                "bytes": len(blob),
                "sha256": _sha256(dest),
                "format": "pcap",
            })
            with tempfile.TemporaryDirectory(prefix="so_extract_") as tmp:
                tmp_path = Path(tmp)
                conn_log = _run_zeek(dest, tmp_path, zeek_bin)
                if conn_log:
                    all_flows.extend(_parse_zeek_conn_log(conn_log, ""))
                eve_json = _run_suricata(dest, tmp_path, suricata_bin, suricata_cfg)
                if eve_json:
                    all_alerts.extend(_parse_suricata_eve(eve_json, ""))
    else:
        raise ValueError(f"Unknown SO mode: {mode}. Use 'filesystem' or 'api'.")

    # ── Fallback: create minimal IR if nothing found ──────────────────────
    if not all_flows and not all_alerts:
        print("  [fallback] No flow data — creating placeholder IR")
        all_flows.append({
            "flow_id": _det_id("so-fallback", "so-header-0"),
            "src_ip": "0.0.0.0", "dst_ip": "0.0.0.0",
            "proto": "unknown", "source": "so_fallback",
        })

    if len(all_flows) > max_flows:
        all_flows = all_flows[:max_flows]

    high_priority_ids = _score_flows(all_flows)

    # ── Provenance bundle ─────────────────────────────────────────────────
    canonical_parts = []
    for f in sorted(pcap_files_info, key=lambda x: x.get("path", "")):
        canonical_parts.append(f"{f.get('path', '')}:{f.get('sha256', '')}:{f.get('bytes', 0)}")
    if not canonical_parts:
        canonical_parts.append(f"so-ingest:{project_id}:{len(all_flows)}")
    bundle_sha = hashlib.sha256("\n".join(canonical_parts).encode()).hexdigest()

    manifest = {
        "schema_version": "1.1.0",
        "bundle_sha256": bundle_sha,
        "root": "security_onion",
        "files": pcap_files_info,
        "rejected": [],
        "meta_bundle": {
            "source": "aipam.ingest.security_onion",
            "so_mode": mode,
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
        "source_type": "security_onion",
        "sensitivity": sensitivity,
        "bundle_sha256": bundle_sha,
        "high_priority_flow_ids": high_priority_ids,
        "alert_ids": [a["alert_id"] for a in all_alerts],
        "flows": all_flows,
        "alerts": all_alerts,
        "metadata": {
            "source": "aipam.ingest.security_onion",
            "so_mode": mode,
            "total_flows": len(all_flows),
            "total_alerts": len(all_alerts),
            "sensors": sensors,
            "time_range": time_range,
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
        link_id="aipam.ingest.security_onion", run_id=run_id,
        step_id="ingest_bundle", status="OK",
        inputs={"mode": mode, "sensitivity": sensitivity, "sensors": sensors},
        outputs={"bundle_sha256": bundle_sha, "job_id": job_id},
        metrics={"total_flows": len(all_flows), "total_alerts": len(all_alerts),
                 "pcap_count": len(pcap_files_info)},
        errors={},
    )

    print(f"[aipam.ingest.security_onion] ✓ {len(all_flows)} flows, "
          f"{len(all_alerts)} alerts, sensitivity={sensitivity}")

    return {
        "status": "SUCCEEDED",
        "metrics": {
            "so_mode": mode,
            "total_flows": len(all_flows),
            "total_alerts": len(all_alerts),
            "high_priority_flows": len(high_priority_ids),
            "sensitivity": sensitivity,
        },
    }
