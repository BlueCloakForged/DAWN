"""report.narrative — Forensic Narrative Builder (Chat Bridge).

Synthesizes Level 1 (flow IR), Level 2 (forensic findings), and
Level 3 (deep malware, optional) artifacts into a conversational
Forensic Story using the Generalist Model.

Produces ``aipam.forensic.narrative`` in Markdown format, which
becomes the primary data source for the Chat/UI interface.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# AIPAM import bootstrap
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

def _load_artifact(artifact_store, artifact_id: str) -> Optional[Dict[str, Any]]:
    """Load an artifact, returning None for optional missing artifacts."""
    meta = artifact_store.get(artifact_id)
    if not meta:
        return None
    with open(meta["path"]) as fh:
        return json.load(fh)


def _load_required(artifact_store, artifact_id: str) -> Dict[str, Any]:
    result = _load_artifact(artifact_store, artifact_id)
    if result is None:
        raise RuntimeError(f"MISSING_REQUIRED_ARTIFACT: {artifact_id}")
    return result


def _build_narrative_prompt(
    flow_ir: Dict[str, Any],
    findings_ir: Dict[str, Any],
    malware_ir: Optional[Dict[str, Any]],
    bundle_sha: str,
) -> str:
    """Build the LLM prompt that synthesizes all artifacts into a story."""

    sensitivity = flow_ir.get("sensitivity", "LOW")
    source_type = flow_ir.get("source_type", "unknown")
    total_flows = len(flow_ir.get("flows", []))
    total_alerts = len(flow_ir.get("alerts", []))
    findings = findings_ir.get("findings", [])

    # Summarize top findings
    findings_summary = []
    for f in findings[:10]:  # Cap at 10 for prompt size
        mitre = f.get("mitre_technique_id", "")
        desc = f.get("description", f.get("summary", ""))
        sev = f.get("severity", "unknown")
        conf = f.get("confidence_score", 0)
        findings_summary.append(
            f"  - [{sev}] {mitre}: {desc[:200]} (confidence: {conf:.0%})"
        )

    findings_block = "\n".join(findings_summary) if findings_summary else "  (no findings)"

    # Malware section
    malware_block = ""
    if malware_ir and malware_ir.get("classifications"):
        families = malware_ir.get("unique_families", [])
        iocs = malware_ir.get("unique_iocs", [])
        malware_block = (
            f"\n\n## Level 3 — Deep Malware Identification\n"
            f"Model: {malware_ir.get('model_used', 'mc4minta')}\n"
            f"Malware families identified: {', '.join(families) if families else 'None'}\n"
            f"IOCs extracted: {len(iocs)}\n"
            f"Classifications: {malware_ir.get('total_classifications', 0)}\n"
        )
        for c in malware_ir["classifications"][:5]:
            malware_block += (
                f"  - {c.get('malware_family', '?')} ({c.get('variant', '?')}) — "
                f"confidence: {c.get('confidence', 0):.0%}, "
                f"flow: {c.get('src_ip', '?')} → {c.get('dst_ip', '?')}:{c.get('dst_port', '?')}\n"
            )

    prompt = f"""You are a senior forensic analyst. Write a comprehensive forensic narrative report in Markdown format based on the following analysis results.

## Context
- Source: {source_type}
- Sensitivity: {sensitivity}
- Bundle SHA256: {bundle_sha[:16]}...
- Total Flows Analyzed: {total_flows}
- Total Alerts: {total_alerts}
- Findings Produced: {len(findings)}

## Level 2 — Forensic Findings
{findings_block}
{malware_block}

## Instructions
Write the forensic narrative with the following structure:

1. **Executive Summary** — 2-3 paragraph overview of the investigation
2. **Timeline of Events** — Chronological reconstruction of observed activity
3. **Attack Chain Analysis** — Map findings to kill chain stages
4. **Indicators of Compromise (IOCs)** — IPs, domains, hashes, signatures
5. **MITRE ATT&CK Mapping** — Table of techniques observed
6. **Risk Assessment** — Impact and threat level
7. **Recommendations** — Immediate actions and long-term mitigations

Use professional forensic language. Be specific about evidence. Reference flow IDs and alert signatures where possible.
"""
    return prompt


def _call_generalist(prompt: str, config: Dict[str, Any]) -> str:
    """Call the Generalist LLM to generate the narrative."""
    try:
        import httpx
    except ImportError:
        return _fallback_narrative(prompt)

    endpoint = config.get("llm_endpoint", "http://localhost:11434")
    model = config.get("model_name", "llama3.1:8b")
    temperature = config.get("temperature", 0.3)
    max_tokens = config.get("max_tokens", 4096)

    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{endpoint}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                },
            )
            if resp.status_code == 200:
                body = resp.json()
                return body.get("response", _fallback_narrative(prompt))
            else:
                print(f"  ⚠ LLM returned {resp.status_code}")
                return _fallback_narrative(prompt)
    except Exception as exc:
        print(f"  ⚠ Generalist LLM call failed: {exc}")
        return _fallback_narrative(prompt)


def _fallback_narrative(prompt: str) -> str:
    """Generate a template narrative when LLM is unavailable."""
    return (
        "# Forensic Narrative Report\n\n"
        "## Executive Summary\n\n"
        "This report was generated using automated forensic analysis. "
        "The LLM generalist model was unavailable at the time of generation. "
        "Please review the raw findings artifacts for detailed analysis.\n\n"
        "## Timeline of Events\n\n"
        "_Automated timeline reconstruction requires LLM synthesis._\n\n"
        "## Attack Chain Analysis\n\n"
        "_Pending LLM analysis._\n\n"
        "## Indicators of Compromise\n\n"
        "_See aipam.findings.ir and aipam.malware.ir artifacts._\n\n"
        "## Recommendations\n\n"
        "1. Review findings in the AIPAM dashboard\n"
        "2. Cross-reference IOCs with threat intelligence feeds\n"
        "3. Isolate affected systems pending investigation\n"
    )


# ---------------------------------------------------------------------------
# DAWN entry point
# ---------------------------------------------------------------------------

def run(context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    DAWN Link: report.narrative

    1. Load all available artifacts (flow IR, findings, malware)
    2. Build synthesis prompt
    3. Call Generalist Model
    4. Publish aipam.forensic.narrative (Markdown)
    """
    project_id = context["project_id"]
    pipeline_id = context.get("pipeline_id", "aipam_forensic")
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    ledger = context["ledger"]
    run_id = context.get("run_id", str(uuid.uuid4()))

    config = link_config.get("spec", {}).get("config", {})

    print(f"[report.narrative] Synthesizing forensic story for {project_id}")

    start_time = time.time()

    # ── Load artifacts ────────────────────────────────────────────────────
    flow_ir = _load_required(artifact_store, "aipam.flow.ir")
    findings_ir = _load_required(artifact_store, "aipam.findings.ir")
    malware_ir = _load_artifact(artifact_store, "aipam.malware.ir")  # Optional

    bundle_sha = flow_ir.get("bundle_sha256", "unknown")
    sensitivity = flow_ir.get("sensitivity", "LOW")

    has_malware = malware_ir is not None and bool(malware_ir.get("classifications"))
    print(f"  Sensitivity: {sensitivity}")
    print(f"  L2 findings: {len(findings_ir.get('findings', []))}")
    print(f"  L3 malware: {'YES' if has_malware else 'N/A'}")

    # ── Build prompt and call LLM ─────────────────────────────────────────
    prompt = _build_narrative_prompt(flow_ir, findings_ir, malware_ir, bundle_sha)
    narrative_md = _call_generalist(prompt, config)

    duration_ms = int((time.time() - start_time) * 1000)

    # ── Publish narrative ─────────────────────────────────────────────────
    sandbox.publish(
        artifact="aipam.forensic.narrative",
        filename="forensic_narrative.md",
        obj=narrative_md,
        schema="markdown",
    )

    # ── Audit ─────────────────────────────────────────────────────────────
    ledger.log_event(
        project_id=project_id, pipeline_id=pipeline_id,
        link_id="report.narrative", run_id=run_id,
        step_id="narrative_complete", status="OK",
        inputs={
            "sensitivity": sensitivity,
            "bundle_sha256": bundle_sha,
            "has_malware_ir": has_malware,
        },
        outputs={"narrative_length": len(narrative_md)},
        metrics={"duration_ms": duration_ms, "narrative_chars": len(narrative_md)},
        errors={},
    )

    print(f"[report.narrative] ✓ Generated {len(narrative_md)} chars in {duration_ms}ms")

    return {
        "status": "SUCCEEDED",
        "metrics": {
            "duration_ms": duration_ms,
            "narrative_length": len(narrative_md),
            "has_malware_analysis": has_malware,
        },
    }
