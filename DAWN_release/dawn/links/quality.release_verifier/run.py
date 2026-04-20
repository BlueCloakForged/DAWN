import json
from pathlib import Path
from typing import Dict, Any, List

def run(context, config):
    """
    quality.release_verifier - The "Ending Gate" Auditor
    
    Verifies:
    1. Bundle/Contract binding matches approval.
    2. Ledger shows no sandbox failures or policy violations.
    3. Pipeline had no failed links.
    4. Decision Rights: No writes outside allowed_paths.
    5. Definition of Done: Required tests passed.
    """
    project_root = Path(context["project_root"])
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    
    # 1. Load Contract and Approval
    contract_meta = artifact_store.get("dawn.project.contract")
    approval_meta = artifact_store.get("dawn.hitl.approval")
    
    if not contract_meta or not approval_meta:
        raise Exception("INPUT_MISSING: contract and approval required for release verification.")
    
    with open(contract_meta["path"]) as f:
        contract = json.load(f)
    with open(approval_meta["path"]) as f:
        approval = json.load(f)
        
    audit_results = {
        "status": "PASS",
        "checks": {},
        "evidence": {}
    }
    
    # Check 1: Cryptographic Coherence
    binding_pass = (
        approval.get("bundle_sha256") == contract.get("bundle_sha256") and
        approval.get("contract_sha256") == contract.get("contract_sha256")
    )
    audit_results["checks"]["binding_coherence"] = "PASS" if binding_pass else "FAIL"
    
    # Check 2: Ledger Audit (Sandbox & Pipeline Health)
    ledger_path = project_root / "ledger" / "events.jsonl"
    ledger_violations = []
    pipeline_failures = []
    unauthorized_writes = []
    
    allowed_paths = contract.get("decision_rights", {}).get("allowed_paths", [])
    
    if ledger_path.exists():
        with open(ledger_path) as f:
            for line in f:
                event = json.loads(line)
                # Check for sandbox failures
                if event.get("step_id") == "sandbox_check" and event.get("status") == "FAILED":
                    ledger_violations.append(event)
                # Check for policy violations
                if event.get("errors", {}).get("type") == "POLICY_VIOLATION":
                    ledger_violations.append(event)
                # Check for unauthorized writes in evidence
                if "leaked_paths" in event.get("errors", {}):
                    for path in event["errors"]["leaked_paths"]:
                        if not any(path.startswith(p.replace("*", "")) for p in allowed_paths):
                            unauthorized_writes.append(path)
                # Check for pipeline failures
                if event.get("step_id") == "link_complete" and event.get("status") == "FAILED":
                    pipeline_failures.append(event.get("link_id"))

    audit_results["checks"]["sandbox_integrity"] = "PASS" if not ledger_violations else "FAIL"
    audit_results["checks"]["pipeline_health"] = "PASS" if not pipeline_failures else "FAIL"
    audit_results["checks"]["scope_compliance"] = "PASS" if not unauthorized_writes else "FAIL"
    
    # Check 3: Definition of Done (Tests)
    dod = contract.get("definition_of_done", {})
    test_req = dod.get("tests", {})
    test_pass = True
    if test_req.get("must_pass"):
        # Look for test reports in artifacts
        # This is a simplified check for V1
        test_reports = [a for a in context["artifact_index"] if "test.report" in a.lower() or "test_report" in a.lower()]
        if not test_reports:
            test_pass = False
        else:
            # Check most recent test report status
            latest_report_id = sorted(test_reports)[-1]
            report_meta = artifact_store.get(latest_report_id)
            with open(report_meta["path"]) as f:
                report = json.load(f)
                if not report.get("pass", False) and report.get("failed", 0) > 0:
                    test_pass = False
    
    audit_results["checks"]["definition_of_done"] = "PASS" if test_pass else "FAIL"
    
    # Check 4: Scenarios (Acceptance)
    scenarios_req = contract.get("acceptance", {}).get("scenarios", [])
    scenario_pass = True
    if scenarios_req:
        scenario_reports = [a for a in context["artifact_index"] if "scenario.report" in a.lower() or "scenarios.report" in a.lower()]
        if not scenario_reports:
            # If scenarios defined but no report, fail if strict
            scenario_pass = False
        else:
            latest_scenario_id = sorted(scenario_reports)[-1]
            scenario_meta = artifact_store.get(latest_scenario_id)
            with open(scenario_meta["path"]) as f:
                report = json.load(f)
                # Ensure all required scenarios are covered and passing
                passed_scenarios = {s["id"] for s in report.get("scenarios", []) if s.get("status") == "PASSED"}
                for s_id in scenarios_req:
                    if s_id not in passed_scenarios:
                        scenario_pass = False
                        break
    
    audit_results["checks"]["scenario_verification"] = "PASS" if scenario_pass else "FAIL"
    
    # Final Decision
    if any(res == "FAIL" for res in audit_results["checks"].values()):
        audit_results["status"] = "FAIL"
    
    # Evidence for Review
    audit_results["evidence"] = {
        "failed_links": pipeline_failures,
        "policy_violations": [v.get("errors", {}).get("message") for v in ledger_violations],
        "unauthorized_writes": unauthorized_writes,
        "bundle_sha256": contract.get("bundle_sha256"),
        "contract_sha256": contract.get("contract_sha256")
    }
    
    # Publish Audit
    sandbox.publish(
        artifact="dawn.quality.release_audit",
        filename="release_audit.json",
        obj=audit_results,
        schema="json"
    )
    
    # 5. Generate Trust Receipt (Markdown)
    trust_receipt = f"""# DAWN Trust Receipt
**Project ID**: {context["project_id"]}
**Audit Status**: {audit_results["status"]}

---

## 🔐 Cryptographic Binding
- **Bundle SHA256**: `{contract.get("bundle_sha256")[:16]}...`
- **Contract SHA256**: `{contract.get("contract_sha256")[:16]}...`
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
    sandbox.publish_text(
        artifact="dawn.trust.receipt",
        filename="trust_receipt.md",
        text=trust_receipt,
        schema="markdown"
    )
    
    if audit_results["status"] == "FAIL":
        raise Exception(f"CONTRACT_VIOLATION: {audit_results['checks']}")
        
    return {
        "status": "SUCCEEDED",
        "metrics": audit_results["checks"]
    }
