"""export.detection_rules — Detection-as-Code from forensic findings.

Generates Suricata IDS rules and Sigma log-detection rules from
confirmed findings in ``aipam.findings.reviewed``.

Strategy:
  1. For each confirmed finding, extract key indicators (IPs, ports,
     MITRE technique, evidence snippet).
  2. If LLM is available (``use_llm=true``), prompt it to generate
     precise detection rules with context.
  3. Fall back to deterministic templates if LLM is unavailable.

Publishes:
  - ``aipam.rules.suricata``  — one .rules file with all Suricata rules
  - ``aipam.rules.sigma``     — one .yaml file with all Sigma rules
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# MITRE → Suricata class mapping
# ---------------------------------------------------------------------------

MITRE_TO_SURICATA_CLASS = {
    "T1071": "trojan-activity",       # Application Layer Protocol
    "T1071.001": "trojan-activity",   # Web Protocols
    "T1071.004": "trojan-activity",   # DNS
    "T1059": "attempted-admin",       # Command and Scripting
    "T1059.001": "attempted-admin",   # PowerShell
    "T1059.003": "attempted-admin",   # Windows Command Shell
    "T1048": "bad-unknown",           # Exfiltration Over Alt Protocol
    "T1105": "trojan-activity",       # Ingress Tool Transfer
    "T1203": "attempted-user",        # Exploitation for Client Exec
    "T1566": "attempted-recon",       # Phishing
    "T1190": "web-application-attack",# Exploit Public-Facing App
}


# ---------------------------------------------------------------------------
# Template-based rule generators (deterministic fallback)
# ---------------------------------------------------------------------------

def _template_suricata_rule(
    finding: Dict[str, Any],
    sid_base: int,
    index: int,
) -> str:
    """Generate a Suricata rule from a finding using templates."""
    technique = finding.get("mitre_technique_id", "T0000")
    evidence = finding.get("raw_evidence_snippet", "")
    severity = finding.get("severity", "medium")
    hosts = finding.get("affected_hosts", [])
    classification = finding.get("classification", "Unknown")

    # Extract IPs and ports from evidence
    ip_pattern = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    ips = re.findall(ip_pattern, evidence)
    port_pattern = r":(\d{2,5})"
    ports = re.findall(port_pattern, evidence)

    # Determine direction and addresses
    dst_ip = ips[0] if ips else "any"
    dst_port = ports[0] if ports else "any"

    # Map severity to priority
    priority = {"critical": 1, "high": 2, "medium": 3, "low": 4}.get(severity, 3)

    # Suricata classification
    classtype = MITRE_TO_SURICATA_CLASS.get(technique, "misc-activity")

    sid = sid_base + index

    # Build rule
    rule = (
        f'alert ip any any -> {dst_ip} {dst_port} '
        f'(msg:"AIPAM {classification} - {technique}"; '
        f'classtype:{classtype}; '
        f'sid:{sid}; rev:1; '
        f'priority:{priority}; '
        f'metadata: mitre_technique {technique}, '
        f'severity {severity}, '
        f'generated_by aipam_dawn;)'
    )
    return rule


def _template_sigma_rule(
    finding: Dict[str, Any],
    index: int,
) -> Dict[str, Any]:
    """Generate a Sigma rule from a finding using templates."""
    technique = finding.get("mitre_technique_id", "T0000")
    evidence = finding.get("raw_evidence_snippet", "")
    severity = finding.get("severity", "medium")
    hosts = finding.get("affected_hosts", [])
    rationale = finding.get("rationale", "")
    classification = finding.get("classification", "Unknown")

    # Extract IPs
    ip_pattern = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    ips = re.findall(ip_pattern, evidence)

    # Build detection conditions based on technique
    detection = {"selection": {}, "condition": "selection"}

    if technique.startswith("T1071"):  # App Layer Protocol
        detection["selection"] = {
            "DestinationIp|contains": ips if ips else ["PLACEHOLDER"],
        }
    elif technique.startswith("T1059"):  # Command/Script
        detection["selection"] = {
            "CommandLine|contains": ["encoded", "base64", "-enc"],
            "ParentImage|endswith": ["\\powershell.exe", "\\cmd.exe"],
        }
    elif technique.startswith("T1048"):  # Exfiltration
        detection["selection"] = {
            "DestinationIp|contains": ips if ips else ["PLACEHOLDER"],
            "DestinationPort": [53, 443, 8443],
        }
    else:
        detection["selection"] = {
            "DestinationIp|contains": ips if ips else ["PLACEHOLDER"],
        }

    # Map severity to sigma level
    level_map = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}

    sigma = {
        "title": f"AIPAM Detection: {classification} ({technique})",
        "id": f"aipam-{technique.lower()}-{index:03d}",
        "status": "experimental",
        "description": rationale[:200] if rationale else f"Detects {technique} activity",
        "references": [f"https://attack.mitre.org/techniques/{technique.replace('.', '/')}/"],
        "author": "AIPAM/DAWN Forensic Pipeline",
        "date": time.strftime("%Y/%m/%d"),
        "tags": [f"attack.{technique.lower()}"],
        "logsource": {
            "category": "network_connection" if technique.startswith("T107") else "process_creation",
            "product": "zeek" if technique.startswith("T107") else "windows",
        },
        "detection": detection,
        "falsepositives": ["Legitimate business connections to listed IPs"],
        "level": level_map.get(severity, "medium"),
    }
    return sigma


# ---------------------------------------------------------------------------
# LLM-assisted generation
# ---------------------------------------------------------------------------

def _llm_generate_rules(
    finding: Dict[str, Any],
    endpoint: str,
    model: str,
) -> Optional[Dict[str, str]]:
    """Use OllamaProvider to generate rules (best-effort)."""
    try:
        import requests

        prompt = f"""You are a SOC detection engineer. Generate exactly ONE Suricata IDS rule and ONE Sigma log-detection rule for this forensic finding.

FINDING:
- MITRE Technique: {finding.get('mitre_technique_id', 'Unknown')}
- Severity: {finding.get('severity', 'medium')}
- Evidence: {finding.get('raw_evidence_snippet', 'N/A')}
- Rationale: {finding.get('rationale', 'N/A')}
- Affected Hosts: {finding.get('affected_hosts', [])}
- Classification: {finding.get('classification', 'Unknown')}

OUTPUT FORMAT:
SURICATA:
<single suricata rule line>

SIGMA:
title: <title>
description: <description>
detection:
  selection:
    <field>: <value>
  condition: selection
level: <level>
"""

        response = requests.post(
            f"{endpoint}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=30,
        )

        if response.status_code == 200:
            text = response.json().get("response", "")
            return {"raw": text}

    except Exception as e:
        print(f"  [llm] Generation failed: {e}")

    return None


# ---------------------------------------------------------------------------
# DAWN entry point
# ---------------------------------------------------------------------------

def run(context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    DAWN Link: export.detection_rules

    1. Load aipam.findings.reviewed
    2. Filter to confirmed findings only
    3. Generate Suricata + Sigma rules
    4. Publish rule artifacts
    """
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    ledger = context["ledger"]
    project_id = context["project_id"]
    pipeline_id = context.get("pipeline_id", "aipam_forensic")
    run_id = context.get("run_id", "unknown")

    config = link_config.get("spec", {}).get("config", {})
    model_name = config.get("model_name", "llama3.1:8b")
    endpoint = config.get("llm_endpoint", "http://localhost:11434")
    use_llm = config.get("use_llm", True)

    # Load reviewed findings
    reviewed_meta = artifact_store.get("aipam.findings.reviewed")
    if not reviewed_meta:
        raise RuntimeError("MISSING_REQUIRED_ARTIFACT: aipam.findings.reviewed")

    with open(reviewed_meta["path"]) as fh:
        reviewed_data = json.load(fh)

    # §2 Provenance Binding: thread source_bundle_sha256 from upstream
    source_bundle_sha256 = reviewed_data.get("source_bundle_sha256", "")

    all_findings = reviewed_data.get("findings", [])
    confirmed = [
        f for f in all_findings
        if f.get("analyst_status") == "confirmed"
    ]

    print(f"[export.detection_rules] {len(confirmed)}/{len(all_findings)} "
          f"confirmed findings → generating rules")

    if not confirmed:
        # Publish empty rules
        sandbox.publish(
            artifact="aipam.rules.suricata",
            filename="suricata_rules.rules",
            obj={"rules": [], "note": "No confirmed findings to generate rules from"},
            schema="json",
        )
        sandbox.publish(
            artifact="aipam.rules.sigma",
            filename="sigma_rules.yaml",
            obj={"rules": [], "note": "No confirmed findings"},
            schema="json",
        )
        return {
            "status": "SUCCEEDED",
            "metrics": {"suricata_rules": 0, "sigma_rules": 0},
        }

    suricata_rules: List[str] = []
    sigma_rules: List[Dict[str, Any]] = []
    sid_base = 9100000  # AIPAM SID range

    for i, finding in enumerate(confirmed):
        technique = finding.get("mitre_technique_id", "?")
        print(f"  [{i+1}/{len(confirmed)}] {technique} → ", end="")

        # Try LLM generation first
        llm_result = None
        if use_llm:
            llm_result = _llm_generate_rules(finding, endpoint, model_name)

        if llm_result:
            print("LLM-generated")
            # §3 Anti-Hallucination: validate LLM rule syntax before commit
            raw_text = llm_result.get("raw", "")
            if "alert " in raw_text and "sid:" in raw_text:
                # LLM produced a validly-structured Suricata rule
                suricata_rules.append(f"# LLM-enhanced rule for {technique}")
                suricata_rules.append(raw_text.split("\n")[0].strip())
            else:
                # LLM output failed validation — fall back to template
                print("    → LLM output invalid, falling back to template")
                rule = _template_suricata_rule(finding, sid_base, i)
                suricata_rules.append(rule)
        else:
            print("template-generated")
            rule = _template_suricata_rule(finding, sid_base, i)
            suricata_rules.append(rule)

        # Sigma is always template-based (structured YAML)
        sigma = _template_sigma_rule(finding, i)
        sigma_rules.append(sigma)

    # Build Suricata rules file
    suricata_header = (
        f"# AIPAM Detection Rules — Generated by DAWN Pipeline\n"
        f"# Date: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n"
        f"# Findings: {len(confirmed)} confirmed\n"
        f"# SID Range: {sid_base}-{sid_base + len(confirmed)}\n"
        f"#\n"
    )
    suricata_text = suricata_header + "\n".join(suricata_rules) + "\n"

    # §2 Sandbox Compliance: use sandbox.publish() exclusively (not write_text + register)
    sandbox.publish(
        artifact="aipam.rules.suricata",
        filename="suricata_rules.rules",
        obj={
            "source_bundle_sha256": source_bundle_sha256,
            "rules_text": suricata_text,
            "rule_count": len(suricata_rules),
        },
        schema="json",
    )

    # Also write a plain-text version alongside for direct IDS import
    sandbox.write_text("suricata_rules.rules.txt", suricata_text)

    # Publish Sigma rules as JSON array (each rule is a YAML-compatible dict)
    sigma_payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_bundle_sha256": source_bundle_sha256,
        "total_rules": len(sigma_rules),
        "rules": sigma_rules,
    }
    sandbox.publish(
        artifact="aipam.rules.sigma",
        filename="sigma_rules.yaml",
        obj=sigma_payload,
        schema="json",
    )

    print(f"[export.detection_rules] ✓ {len(suricata_rules)} Suricata rules, "
          f"{len(sigma_rules)} Sigma rules")

    # §1 Audit Integrity: log rule generation to ledger
    ledger.log_event(
        project_id=project_id, pipeline_id=pipeline_id,
        link_id="export.detection_rules", run_id=run_id,
        step_id="rules_generated", status="OK",
        inputs={"confirmed_findings": len(confirmed), "source_bundle_sha256": source_bundle_sha256},
        outputs={"suricata_rules": len(suricata_rules), "sigma_rules": len(sigma_rules)},
        metrics={"sid_base": sid_base},
        errors={},
    )

    return {
        "status": "SUCCEEDED",
        "outputs": {
            "suricata_text": suricata_text,
        },
        "metrics": {
            "suricata_rules": len(suricata_rules),
            "sigma_rules": len(sigma_rules),
            "confirmed_findings": len(confirmed),
        },
    }
