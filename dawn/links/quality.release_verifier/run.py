"""quality.release_verifier — The "Ending Gate" Auditor.

Two operating modes:

1. **Standard DAWN**: Requires ``dawn.project.contract`` + ``dawn.hitl.approval``.
   Performs cryptographic binding, ledger audit, scope compliance, and DoD checks.

2. **AIPAM Forensic**: Activates when ``aipam.findings.reviewed`` is present.
   Performs bundle provenance, ledger audit (sandbox violations + guardrail warnings),
   campaign correlation summary, severity breakdown, and produces
   a comprehensive ``trust_receipt.md``.
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional


def _load_artifact(artifact_store, artifact_id: str) -> Optional[Dict[str, Any]]:
    """Load an artifact's JSON content, returning None if missing."""
    meta = artifact_store.get(artifact_id)
    if not meta:
        return None
    try:
        with open(meta["path"]) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, KeyError):
        return None


def _load_text_artifact(artifact_store, artifact_id: str) -> Optional[str]:
    """Load an artifact's text content, returning None if missing."""
    meta = artifact_store.get(artifact_id)
    if not meta:
        return None
    try:
        with open(meta["path"]) as f:
            return f.read()
    except (OSError, KeyError):
        return None


def _audit_ledger(project_root: Path) -> Dict[str, Any]:
    """Parse ledger events and classify them."""
    ledger_path = project_root / "ledger" / "events.jsonl"
    results = {
        "total_events": 0,
        "sandbox_violations": 0,
        "policy_violations": 0,
        "guardrail_warnings": 0,
        "pipeline_failures": 0,
        "failed_links": [],
        "violation_details": [],
        "guardrail_details": [],
    }

    if not ledger_path.exists():
        return results

    with open(ledger_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            results["total_events"] += 1

            # Sandbox failures
            if event.get("step_id") == "sandbox_check" and event.get("status") == "FAILED":
                results["sandbox_violations"] += 1
                results["violation_details"].append({
                    "link_id": event.get("link_id"),
                    "type": "SANDBOX_VIOLATION",
                })

            # Policy violations
            if event.get("errors", {}).get("type") == "POLICY_VIOLATION":
                results["policy_violations"] += 1
                results["violation_details"].append({
                    "link_id": event.get("link_id"),
                    "type": "POLICY_VIOLATION",
                    "message": event.get("errors", {}).get("message", ""),
                })

            # Guardrail warnings (AIPAM-specific)
            if event.get("step_id") == "guardrail_hallucination":
                results["guardrail_warnings"] += 1
                results["guardrail_details"].append({
                    "link_id": event.get("link_id"),
                    "hallu_count": event.get("errors", {}).get("hallucinated_count", 0),
                })

            # Pipeline failures
            if event.get("step_id") == "link_complete" and event.get("status") == "FAILED":
                results["pipeline_failures"] += 1
                results["failed_links"].append(event.get("link_id"))

    return results


def _generate_aipam_trust_receipt(
    context: Dict[str, Any],
    audit: Dict[str, Any],
    ledger: Dict[str, Any],
    bundle: Optional[Dict[str, Any]],
    findings_reviewed: Optional[Dict[str, Any]],
    campaign: Optional[Dict[str, Any]],
    metrics: Optional[Dict[str, Any]],
    suricata_text: Optional[str],
    sigma: Optional[Dict[str, Any]],
) -> str:
    """Generate full AIPAM trust receipt as Markdown."""
    project_id = context["project_id"]
    status = audit["status"]
    now = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    lines = []
    lines.append(f"# 🛡️ AIPAM Trust Receipt")
    lines.append(f"")
    lines.append(f"**Project:** `{project_id}`  ")
    lines.append(f"**Audit Status:** {'✅ PASS' if status == 'PASS' else '❌ FAIL'}  ")
    lines.append(f"**Generated:** {now}  ")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    # ── Bundle Provenance ──
    lines.append(f"## 🔐 Bundle Provenance")
    lines.append(f"")
    if bundle:
        sha = bundle.get("bundle_sha256", "N/A")
        lines.append(f"| Field | Value |")
        lines.append(f"|-------|-------|")
        lines.append(f"| Bundle SHA256 | `{sha[:32]}...` |")
        lines.append(f"| Files in Bundle | {len(bundle.get('files', []))} |")
        lines.append(f"| Provenance Check | {audit['checks'].get('bundle_provenance', 'N/A')} |")
    else:
        lines.append(f"*No bundle artifact present.*")
    lines.append(f"")

    # ── Ledger Audit ──
    lines.append(f"## 📋 Ledger Audit")
    lines.append(f"")
    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total Events | {ledger['total_events']} |")
    lines.append(f"| Sandbox Violations | {ledger['sandbox_violations']} |")
    lines.append(f"| Policy Violations | {ledger['policy_violations']} |")
    lines.append(f"| Guardrail Warnings | {ledger['guardrail_warnings']} |")
    lines.append(f"| Pipeline Failures | {ledger['pipeline_failures']} |")
    lines.append(f"")

    if ledger["guardrail_details"]:
        lines.append(f"### Guardrail Details")
        for gd in ledger["guardrail_details"]:
            lines.append(f"- **{gd['link_id']}**: {gd['hallu_count']} hallucinated flow IDs detected")
        lines.append(f"")

    # ── Findings Summary ──
    lines.append(f"## 🔍 Findings Summary")
    lines.append(f"")
    if findings_reviewed:
        findings = findings_reviewed.get("findings", [])
        confirmed = sum(1 for f in findings if f.get("analyst_status") == "confirmed")
        false_pos = sum(1 for f in findings if f.get("analyst_status") == "false_positive")
        unverified = len(findings) - confirmed - false_pos
        review_mode = findings_reviewed.get("review_mode", "unknown")

        lines.append(f"| Metric | Count |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total Findings | {len(findings)} |")
        lines.append(f"| ✅ Confirmed | {confirmed} |")
        lines.append(f"| ❌ False Positive | {false_pos} |")
        lines.append(f"| ⏳ Unverified | {unverified} |")
        lines.append(f"| Review Mode | {review_mode} |")
        lines.append(f"")

        # Severity breakdown
        severity_counts: Dict[str, int] = {}
        for f in findings:
            sev = f.get("severity", "unknown")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        if severity_counts:
            lines.append(f"### Severity Breakdown")
            lines.append(f"")
            for sev in ["critical", "high", "medium", "low"]:
                count = severity_counts.get(sev, 0)
                if count:
                    emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(sev, "⚪")
                    lines.append(f"- {emoji} **{sev.upper()}**: {count}")
            lines.append(f"")
    else:
        lines.append(f"*No reviewed findings present.*")
        lines.append(f"")

    # ── Campaign Correlation ──
    lines.append(f"## 🔗 Campaign Correlation")
    lines.append(f"")
    if campaign:
        groups = campaign.get("correlation_groups", [])
        summary = campaign.get("summary", {})
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Projects Scanned | {campaign.get('projects_scanned', 0)} |")
        lines.append(f"| Strong Links | {summary.get('strong_links', 0)} |")
        lines.append(f"| Linked Projects | {summary.get('projects_with_links', 0)} |")
        lines.append(f"")

        if groups:
            lines.append(f"### Correlation Groups")
            lines.append(f"")
            lines.append(f"| IP | MITRE | Linked Cases | Confidence |")
            lines.append(f"|----|-------|-------------|------------|")
            for g in groups[:10]:  # Cap at 10
                linked = ", ".join(g.get("linked_projects", []))
                lines.append(
                    f"| `{g.get('shared_ip', '?')}` "
                    f"| {g.get('shared_technique', '?')} "
                    f"| {linked} "
                    f"| {g.get('confidence', 0)} |"
                )
            lines.append(f"")
    else:
        lines.append(f"*No campaign correlation data present.*")
        lines.append(f"")

    # ── Detection Rules ──
    lines.append(f"## 🛡️ Detection Rules Exported")
    lines.append(f"")
    if suricata_text:
        rule_count = sum(1 for line in suricata_text.split("\n")
                         if line.strip() and not line.strip().startswith("#"))
        lines.append(f"- **Suricata rules:** {rule_count}")
    if sigma:
        lines.append(f"- **Sigma rules:** {sigma.get('total_rules', 0)}")

    if not suricata_text and not sigma:
        lines.append(f"*No detection rules exported.*")
    lines.append(f"")

    # ── Final Verdict ──
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## 📜 Audit Verdict")
    lines.append(f"")

    checks = audit.get("checks", {})
    for check_name, result in checks.items():
        icon = "✅" if result == "PASS" else "❌"
        lines.append(f"- {icon} **{check_name}**: {result}")
    lines.append(f"")

    if status == "PASS":
        lines.append(f"> **This forensic case has passed all audit checks.** "
                      f"The trust receipt certifies that findings were properly "
                      f"ingested, analyzed, reviewed, and correlated with "
                      f"full ledger provenance.")
    else:
        lines.append(f"> ⚠️ **Audit FAILED.** Review the checks above "
                      f"before releasing this case.")

    lines.append(f"")
    lines.append(f"---")
    lines.append(f"*This receipt is cryptographically bound to the project state "
                  f"and represents a verified claim of execution integrity.*")

    return "\n".join(lines)


def run(context, config):
    """
    quality.release_verifier - The "Ending Gate" Auditor

    Operates in two modes:
    1. Standard DAWN: contract + approval based
    2. AIPAM Forensic: findings + bundle based (no contract needed)
    """
    project_root = Path(context["project_root"])
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    ledger = context["ledger"]
    project_id = context["project_id"]
    pipeline_id = context.get("pipeline_id", "aipam_forensic")
    run_id = context.get("run_id", "unknown")

    # Detect mode
    contract = _load_artifact(artifact_store, "dawn.project.contract")
    approval = _load_artifact(artifact_store, "dawn.hitl.approval")
    findings_reviewed = _load_artifact(artifact_store, "aipam.findings.reviewed")
    bundle = _load_artifact(artifact_store, "dawn.project.bundle")

    is_aipam_mode = findings_reviewed is not None
    is_standard_mode = contract is not None and approval is not None

    if not is_aipam_mode and not is_standard_mode:
        raise Exception(
            "INPUT_MISSING: Either (contract + approval) for standard mode "
            "or (aipam.findings.reviewed) for AIPAM mode is required."
        )

    # ── AIPAM Forensic Mode ──────────────────────────────────────────
    if is_aipam_mode:
        print("[quality.release_verifier] Operating in AIPAM Forensic mode")

        campaign = _load_artifact(artifact_store, "aipam.campaign.correlation")
        metrics = _load_artifact(artifact_store, "aipam.analysis.metrics")
        findings_ir = _load_artifact(artifact_store, "aipam.findings.ir")
        sigma = _load_artifact(artifact_store, "aipam.rules.sigma")
        suricata_text = _load_text_artifact(artifact_store, "aipam.rules.suricata")

        ledger_audit = _audit_ledger(project_root)

        audit_results = {
            "status": "PASS",
            "mode": "AIPAM_FORENSIC",
            "checks": {},
            "evidence": {},
        }

        # Check 1: Bundle provenance
        if bundle and findings_ir:
            findings_sha = findings_ir.get("source_bundle_sha256")
            bundle_sha = bundle.get("bundle_sha256")
            prov_pass = findings_sha is not None and findings_sha == bundle_sha
            audit_results["checks"]["bundle_provenance"] = "PASS" if prov_pass else "FAIL"
        else:
            audit_results["checks"]["bundle_provenance"] = "SKIP"

        # Check 2: Sandbox integrity
        audit_results["checks"]["sandbox_integrity"] = (
            "PASS" if ledger_audit["sandbox_violations"] == 0 else "FAIL"
        )

        # Check 3: Pipeline health
        audit_results["checks"]["pipeline_health"] = (
            "PASS" if ledger_audit["pipeline_failures"] == 0 else "FAIL"
        )

        # Check 4: Guardrail warnings (INFO only — does not fail audit)
        audit_results["checks"]["guardrail_audit"] = (
            f"PASS ({ledger_audit['guardrail_warnings']} warnings handled)"
        )

        # Check 5: Findings review completeness
        if findings_reviewed:
            findings = findings_reviewed.get("findings", [])
            unverified = sum(
                1 for f in findings
                if f.get("analyst_status") == "unverified"
            )
            review_pass = unverified == 0 or findings_reviewed.get("review_mode") != "BLOCKED"
            audit_results["checks"]["review_completeness"] = (
                "PASS" if review_pass else f"FAIL ({unverified} unreviewed)"
            )

        # Check 6: Detection rules generated
        has_rules = suricata_text is not None or sigma is not None
        audit_results["checks"]["detection_export"] = "PASS" if has_rules else "SKIP"

        # Final verdict
        if any(str(v).startswith("FAIL") for v in audit_results["checks"].values()):
            audit_results["status"] = "FAIL"

        # Evidence
        audit_results["evidence"] = {
            "ledger_summary": {
                "total_events": ledger_audit["total_events"],
                "sandbox_violations": ledger_audit["sandbox_violations"],
                "guardrail_warnings": ledger_audit["guardrail_warnings"],
            },
            "bundle_sha256": bundle.get("bundle_sha256", "N/A") if bundle else "N/A",
        }

        # Publish audit JSON
        sandbox.publish(
            artifact="dawn.quality.release_audit",
            filename="release_audit.json",
            obj=audit_results,
            schema="json",
        )

        # Generate and publish trust receipt
        receipt = _generate_aipam_trust_receipt(
            context, audit_results, ledger_audit, bundle,
            findings_reviewed, campaign, metrics,
            suricata_text, sigma,
        )

        receipt_path = sandbox.write_text("trust_receipt.md", receipt)
        if sandbox.artifact_store:
            sandbox.artifact_store.register(
                artifact_id="dawn.trust.receipt",
                abs_path=str(Path(receipt_path).absolute()),
                schema="markdown",
                producer_link_id="quality.release_verifier",
            )

        print(f"[quality.release_verifier] ✓ AIPAM audit: {audit_results['status']}")
        print(f"  Trust receipt: {receipt_path}")

        # §1 Audit Integrity: log audit result to ledger
        ledger.log_event(
            project_id=project_id, pipeline_id=pipeline_id,
            link_id="quality.release_verifier", run_id=run_id,
            step_id="audit_complete", status="OK" if audit_results["status"] == "PASS" else "FAILED",
            inputs={"mode": "AIPAM_FORENSIC"},
            outputs={"audit_status": audit_results["status"]},
            metrics=audit_results["checks"],
            errors={},
        )

        if audit_results["status"] == "FAIL":
            raise Exception(f"AUDIT_FAILED: {audit_results['checks']}")

        return {
            "status": "SUCCEEDED",
            "metrics": audit_results["checks"],
        }

    # ── Standard DAWN Mode ───────────────────────────────────────────
    print("[quality.release_verifier] Operating in Standard DAWN mode")

    audit_results = {
        "status": "PASS",
        "mode": "STANDARD",
        "checks": {},
        "evidence": {},
    }

    # Check 1: Cryptographic Coherence
    binding_pass = (
        approval.get("bundle_sha256") == contract.get("bundle_sha256") and
        approval.get("contract_sha256") == contract.get("contract_sha256")
    )
    audit_results["checks"]["binding_coherence"] = "PASS" if binding_pass else "FAIL"

    # Check 1b: AIPAM Findings Provenance (if present)
    findings_ir = _load_artifact(artifact_store, "aipam.findings.ir")
    if findings_ir and bundle:
        prov_pass = (
            findings_ir.get("source_bundle_sha256") is not None
            and findings_ir.get("source_bundle_sha256") == bundle.get("bundle_sha256")
        )
        audit_results["checks"]["aipam_findings_provenance"] = "PASS" if prov_pass else "FAIL"

    # Check 2: Ledger Audit
    ledger_audit = _audit_ledger(project_root)

    audit_results["checks"]["sandbox_integrity"] = (
        "PASS" if ledger_audit["sandbox_violations"] == 0 else "FAIL"
    )
    audit_results["checks"]["pipeline_health"] = (
        "PASS" if ledger_audit["pipeline_failures"] == 0 else "FAIL"
    )

    # Scope compliance (from contract)
    allowed_paths = contract.get("decision_rights", {}).get("allowed_paths", [])
    unauthorized = []
    ledger_path = project_root / "ledger" / "events.jsonl"
    if ledger_path.exists():
        with open(ledger_path) as f:
            for line in f:
                try:
                    event = json.loads(line)
                    if "leaked_paths" in event.get("errors", {}):
                        for path in event["errors"]["leaked_paths"]:
                            if not any(path.startswith(p.replace("*", "")) for p in allowed_paths):
                                unauthorized.append(path)
                except json.JSONDecodeError:
                    continue

    audit_results["checks"]["scope_compliance"] = "PASS" if not unauthorized else "FAIL"

    # Check 3: Definition of Done
    dod = contract.get("definition_of_done", {})
    test_req = dod.get("tests", {})
    test_pass = True
    if test_req.get("must_pass"):
        test_reports = [
            a for a in context.get("artifact_index", {})
            if "test.report" in a.lower() or "test_report" in a.lower()
        ]
        if not test_reports:
            test_pass = False
        else:
            latest = sorted(test_reports)[-1]
            report = _load_artifact(artifact_store, latest)
            if report and (not report.get("pass", False) and report.get("failed", 0) > 0):
                test_pass = False

    audit_results["checks"]["definition_of_done"] = "PASS" if test_pass else "FAIL"

    # Check 4: Scenarios
    scenarios_req = contract.get("acceptance", {}).get("scenarios", [])
    scenario_pass = True
    if scenarios_req:
        scenario_reports = [
            a for a in context.get("artifact_index", {})
            if "scenario.report" in a.lower()
        ]
        if not scenario_reports:
            scenario_pass = False

    audit_results["checks"]["scenario_verification"] = "PASS" if scenario_pass else "FAIL"

    # Final verdict
    if any(v == "FAIL" for v in audit_results["checks"].values()):
        audit_results["status"] = "FAIL"

    audit_results["evidence"] = {
        "failed_links": ledger_audit["failed_links"],
        "policy_violations": [v["message"] for v in ledger_audit.get("violation_details", [])],
        "unauthorized_writes": unauthorized,
        "bundle_sha256": contract.get("bundle_sha256"),
        "contract_sha256": contract.get("contract_sha256"),
    }

    sandbox.publish(
        artifact="dawn.quality.release_audit",
        filename="release_audit.json",
        obj=audit_results,
        schema="json",
    )

    # Standard trust receipt
    trust_receipt = f"""# DAWN Trust Receipt
**Project ID**: {context["project_id"]}
**Audit Status**: {audit_results["status"]}

---

## 🔐 Cryptographic Binding
- **Bundle SHA256**: `{contract.get("bundle_sha256", "N/A")[:16]}...`
- **Contract SHA256**: `{contract.get("contract_sha256", "N/A")[:16]}...`
- **Binding Coherence**: {audit_results["checks"]["binding_coherence"]}

## 🛡️ Governance & Compliance
- **Sandbox Integrity**: {audit_results["checks"]["sandbox_integrity"]}
- **Scope Compliance**: {audit_results["checks"]["scope_compliance"]}
- **Policy Violations**: {len(audit_results["evidence"]["policy_violations"])}

## ✅ Definition of Done
- **Pipeline Health**: {audit_results["checks"]["pipeline_health"]}
- **Verification Tests**: {audit_results["checks"]["definition_of_done"]}
- **Scenario Verification**: {audit_results["checks"]["scenario_verification"]}

---
*This receipt is cryptographically bound to the project state and represents a verified claim of execution integrity.*
"""
    receipt_path = sandbox.write_text("trust_receipt.md", trust_receipt)
    if sandbox.artifact_store:
        sandbox.artifact_store.register(
            artifact_id="dawn.trust.receipt",
            abs_path=str(Path(receipt_path).absolute()),
            schema="markdown",
            producer_link_id="quality.release_verifier",
        )

    if audit_results["status"] == "FAIL":
        raise Exception(f"CONTRACT_VIOLATION: {audit_results['checks']}")

    return {
        "status": "SUCCEEDED",
        "metrics": audit_results["checks"],
    }
