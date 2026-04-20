"""analyze.forensic_cot — DAWN Link bridging AIPAM's ForensicEngine.

Reads ``aipam.flow.ir`` from the artifact store, runs the Phase 2
Chain-of-Thought analyzer with anti-hallucination guardrails, and
publishes validated findings as ``aipam.findings.ir``.

Guardrail violations (hallucinated flow IDs) are logged as audit
events to the DAWN ledger for full traceability.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# AIPAM import bootstrap — add the AIPAM backend to sys.path so that
# ``from app.core import ...`` works when executing inside DAWN runtime.
# ---------------------------------------------------------------------------

_AIPAM_BACKEND = os.environ.get(
    "AIPAM_BACKEND_PATH",
    str(Path(__file__).resolve().parents[3] / "AIPAM" / "backend"),
)
if _AIPAM_BACKEND not in sys.path:
    sys.path.insert(0, _AIPAM_BACKEND)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_flow_ir(artifact_store) -> Dict[str, Any]:
    """Load and return the aipam.flow.ir artifact as a dict."""
    meta = artifact_store.get("aipam.flow.ir")
    if not meta:
        raise RuntimeError(
            "MISSING_REQUIRED_ARTIFACT: aipam.flow.ir not found in artifact store"
        )
    with open(meta["path"]) as fh:
        return json.load(fh)


def _load_bundle_sha(artifact_store) -> Optional[str]:
    """Read bundle_sha256 from dawn.project.bundle for provenance."""
    meta = artifact_store.get("dawn.project.bundle")
    if not meta:
        return None
    with open(meta["path"]) as fh:
        bundle = json.load(fh)
    return bundle.get("bundle_sha256")


def _build_analysis_context(flow_ir: Dict[str, Any]):
    """Convert a flow IR dict into an AIPAM AnalysisContext."""
    from app.core.interfaces import AnalysisContext

    return AnalysisContext(
        job_id=flow_ir.get("job_id", f"dawn-{uuid.uuid4().hex[:8]}"),
        exercise_id=flow_ir.get("exercise_id", "dawn-pipeline"),
        mode=flow_ir.get("mode", "single_window"),
        zeek_log_path=flow_ir.get("zeek_log_path"),
        suricata_log_path=flow_ir.get("suricata_log_path"),
        high_priority_flow_ids=flow_ir.get("high_priority_flow_ids", []),
        alert_ids=flow_ir.get("alert_ids", []),
        metadata=flow_ir.get("metadata", {}),
    )


def _build_engine(config: Dict[str, Any]):
    """
    Construct the ForensicEngine with ChainOfThoughtAnalyzer and
    FlowExistenceGuardrail using link configuration.
    """
    from app.core.engine import ForensicEngine, ChainOfThoughtAnalyzer
    from app.core.guardrails import FlowExistenceGuardrail
    from app.llm.providers.ollama import OllamaProvider

    endpoint = config.get("llm_endpoint", "http://localhost:11434")
    model = config.get("model_name", "llama3.1:8b")

    provider = OllamaProvider(endpoint=endpoint, model=model)

    analyzer = ChainOfThoughtAnalyzer(
        provider=provider,
        top_n=config.get("top_n", 3),
    )

    guardrail = FlowExistenceGuardrail()

    engine = ForensicEngine(
        analyzers=[analyzer],
        guardrails=[guardrail],
    )

    return engine


def _findings_to_dicts(findings) -> List[Dict[str, Any]]:
    """Serialize Finding objects to JSON-safe dicts."""
    results = []
    for f in findings:
        d = f.model_dump()
        # Ensure all values are JSON-serializable
        for key in ("zeek_log_path", "suricata_log_path"):
            if key in d and d[key] is not None:
                d[key] = str(d[key])
        results.append(d)
    return results


def _log_guardrail_events(
    findings,
    ledger,
    project_id: str,
    pipeline_id: str,
    run_id: str,
):
    """
    Log a DAWN ledger event for each finding flagged by
    FlowExistenceGuardrail (requires_review == True).
    """
    flagged = [f for f in findings if f.requires_review]
    for finding in flagged:
        ledger.log_event(
            project_id=project_id,
            pipeline_id=pipeline_id,
            link_id="analyze.forensic_cot",
            run_id=run_id,
            step_id="guardrail_hallucination",
            status="WARNING",
            inputs={
                "finding_mitre": finding.mitre_technique_id,
                "cited_flow_ids": finding.cited_flow_ids,
            },
            outputs={},
            metrics={},
            errors={
                "type": "GUARDRAIL_HALLUCINATION",
                "message": finding.review_reason or "Hallucinated flow IDs detected",
                "hallucinated_ids": [
                    fid for fid in finding.cited_flow_ids
                    # All cited IDs are suspect since the guardrail flagged this
                ],
            },
        )
    return len(flagged)


# ---------------------------------------------------------------------------
# DAWN Link entry point
# ---------------------------------------------------------------------------

def run(context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    DAWN Link: analyze.forensic_cot

    Bridges AIPAM's ForensicEngine into the DAWN pipeline runtime.

    Steps:
        1. Load aipam.flow.ir → AnalysisContext
        2. Initialize ForensicEngine (CoT + FlowExistenceGuardrail)
        3. Execute analysis (async → sync bridge via asyncio.run)
        4. Log guardrail violations to DAWN ledger
        5. Publish findings as aipam.findings.ir
        6. Publish analysis metrics
    """
    project_id = context["project_id"]
    pipeline_id = context.get("pipeline_id", "aipam_forensic")
    project_root = Path(context["project_root"])
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    ledger = context["ledger"]
    run_id = context.get("run_id", str(uuid.uuid4()))

    config = link_config.get("spec", {}).get("config", {})

    print(f"[analyze.forensic_cot] Starting forensic analysis for {project_id}")
    print(f"  Model: {config.get('model_name', 'llama3.1:8b')}")
    print(f"  Top-N: {config.get('top_n', 3)}")

    start_time = time.time()

    # ── Step 1: Load flow IR ──────────────────────────────────────────────
    flow_ir = _load_flow_ir(artifact_store)
    bundle_sha = _load_bundle_sha(artifact_store)

    flow_count = len(flow_ir.get("high_priority_flow_ids", []))
    alert_count = len(flow_ir.get("alert_ids", []))
    print(f"  Flow IR loaded: {flow_count} priority flows, {alert_count} alerts")

    # ── Step 2: Build analysis context and engine ─────────────────────────
    ctx = _build_analysis_context(flow_ir)
    engine = _build_engine(config)

    # ── Step 3: Execute analysis (async → sync bridge) ────────────────────
    print(f"[analyze.forensic_cot] Running ForensicEngine...")

    try:
        findings = asyncio.run(engine.run(ctx, session=None))
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        print(f"[analyze.forensic_cot] Engine FAILED: {exc}")
        return {
            "status": "FAILED",
            "errors": {
                "type": "RUNTIME_ERROR",
                "message": str(exc),
                "step_id": "engine_execution",
            },
            "metrics": {"duration_ms": duration_ms},
        }

    duration_ms = int((time.time() - start_time) * 1000)
    print(f"[analyze.forensic_cot] Engine produced {len(findings)} findings in {duration_ms}ms")

    # ── Step 4: Log guardrail violations to ledger ────────────────────────
    hallucination_count = _log_guardrail_events(
        findings, ledger, project_id, pipeline_id, run_id,
    )
    if hallucination_count > 0:
        print(f"  ⚠ {hallucination_count} finding(s) flagged by FlowExistenceGuardrail")

    # ── Step 5: Publish findings artifact ─────────────────────────────────
    findings_dicts = _findings_to_dicts(findings)

    findings_payload = {
        "job_id": ctx.job_id,
        "source_bundle_sha256": bundle_sha,
        "analysis_model": config.get("model_name", "llama3.1:8b"),
        "total_findings": len(findings_dicts),
        "flagged_for_review": hallucination_count,
        "findings": findings_dicts,
    }

    sandbox.publish(
        artifact="aipam.findings.ir",
        filename="findings_ir.json",
        obj=findings_payload,
        schema="json",
    )

    # ── Step 6: Publish analysis metrics ──────────────────────────────────
    auto_threshold = config.get("auto_threshold", 0.7)
    confirmed = [f for f in findings if f.confidence_score >= auto_threshold]

    metrics_payload = {
        "duration_ms": duration_ms,
        "model_name": config.get("model_name", "llama3.1:8b"),
        "total_findings": len(findings),
        "confirmed_findings": len(confirmed),
        "flagged_for_review": hallucination_count,
        "auto_threshold": auto_threshold,
        "input_flows": flow_count,
        "input_alerts": alert_count,
        "source_bundle_sha256": bundle_sha,
        "severity_breakdown": _severity_breakdown(findings),
    }

    sandbox.publish(
        artifact="aipam.analysis.metrics",
        filename="analysis_metrics.json",
        obj=metrics_payload,
        schema="json",
    )

    print(f"[analyze.forensic_cot] ✓ Published {len(findings)} findings, "
          f"{len(confirmed)} auto-confirmed (threshold={auto_threshold})")

    return {
        "status": "SUCCEEDED",
        "outputs": {
            "total_findings": len(findings),
            "confirmed": len(confirmed),
            "flagged_for_review": hallucination_count,
        },
        "metrics": {
            "duration_ms": duration_ms,
            "findings_count": len(findings),
            "hallucination_count": hallucination_count,
        },
    }


def _severity_breakdown(findings) -> Dict[str, int]:
    """Count findings by severity level."""
    breakdown: Dict[str, int] = {}
    for f in findings:
        sev = getattr(f, "severity", "unknown")
        breakdown[sev] = breakdown.get(sev, 0) + 1
    return breakdown
