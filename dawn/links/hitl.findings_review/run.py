"""hitl.findings_review — Per-finding analyst review gate.

Unlike the generic ``hitl.gate`` which provides binary project
approval, this link presents each finding for individual analyst
review.  The analyst marks each finding as ``confirmed`` or
``false_positive``, optionally adding notes.

Modes:
  BLOCKED: Require human review file (default).
  AUTO:    Auto-confirm findings above ``auto_confirm_threshold``.
  SKIP:    Pass all findings through as-is.

Template file: ``inputs/hitl_findings_review.json``
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List


class FindingsBlockedError(Exception):
    """Raised when pipeline is blocked waiting for analyst review."""
    pass


def _generate_review_template(
    findings_data: Dict[str, Any],
    bundle_sha256: str,
) -> Dict[str, Any]:
    """Create a review template listing each finding for analyst verdict."""
    findings = findings_data.get("findings", [])

    review_items = []
    for i, f in enumerate(findings):
        review_items.append({
            "index": i,
            "mitre_technique_id": f.get("mitre_technique_id", ""),
            "severity": f.get("severity", ""),
            "confidence_score": f.get("confidence_score", 0),
            "rationale": f.get("rationale", "")[:200],
            "requires_review": f.get("requires_review", False),
            "review_reason": f.get("review_reason"),
            # Analyst fills these:
            "analyst_status": "unverified",  # → "confirmed" | "false_positive"
            "analyst_notes": "",
        })

    return {
        "schema_version": "1.0.0",
        "bundle_sha256": bundle_sha256,
        "job_id": findings_data.get("job_id", ""),
        "total_findings": len(findings),
        "flagged_for_review": sum(
            1 for f in findings if f.get("requires_review")
        ),
        "findings_review": review_items,
        "_instructions": [
            "Review each finding below.",
            "Set analyst_status to 'confirmed' or 'false_positive'.",
            "Optionally add analyst_notes.",
            "DO NOT modify bundle_sha256 — it binds this review to current inputs.",
            "Save this file and re-run the pipeline.",
        ],
    }


def _merge_verdicts(
    original_findings: List[Dict[str, Any]],
    review_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge analyst verdicts into original findings."""
    # Build lookup by index
    verdicts = {item["index"]: item for item in review_items}

    merged = []
    for i, f in enumerate(original_findings):
        finding = dict(f)  # shallow copy

        review = verdicts.get(i)
        if review:
            finding["analyst_status"] = review.get("analyst_status", "unverified")
            finding["analyst_notes"] = review.get("analyst_notes", "")
        else:
            finding["analyst_status"] = "unverified"
            finding["analyst_notes"] = ""

        merged.append(finding)

    return merged


# ---------------------------------------------------------------------------
# DAWN entry point
# ---------------------------------------------------------------------------

def run(context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    DAWN Link: hitl.findings_review

    1. Load aipam.findings.ir
    2. Check mode (SKIP/AUTO/BLOCKED)
    3. Generate or read review template
    4. Merge analyst verdicts
    5. Publish aipam.findings.reviewed
    """
    project_root = Path(context["project_root"])
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    ledger = context["ledger"]
    project_id = context["project_id"]
    pipeline_id = context.get("pipeline_id", "aipam_forensic")
    run_id = context.get("run_id", "unknown")

    config = link_config.get("spec", {}).get("config", {})
    mode = config.get("mode", "BLOCKED")
    auto_threshold = config.get("auto_confirm_threshold", 0.9)

    # Load findings
    findings_meta = artifact_store.get("aipam.findings.ir")
    if not findings_meta:
        raise RuntimeError("MISSING_REQUIRED_ARTIFACT: aipam.findings.ir not found")

    with open(findings_meta["path"]) as fh:
        findings_data = json.load(fh)

    findings = findings_data.get("findings", [])

    # Load bundle SHA for binding
    bundle_meta = artifact_store.get("dawn.project.bundle")
    bundle_sha = ""
    if bundle_meta:
        with open(bundle_meta["path"]) as fh:
            bundle = json.load(fh)
        bundle_sha = bundle.get("bundle_sha256", "")

    print(f"[hitl.findings_review] Mode={mode}, "
          f"{len(findings)} findings, bundle={bundle_sha[:16]}...")

    # ── SKIP mode ─────────────────────────────────────────────────────
    if mode == "SKIP":
        # Pass all findings through as confirmed
        reviewed = []
        for f in findings:
            finding = dict(f)
            finding["analyst_status"] = "confirmed"
            finding["analyst_notes"] = "Auto-confirmed via SKIP mode"
            reviewed.append(finding)

        reviewed_payload = dict(findings_data)
        reviewed_payload["findings"] = reviewed
        reviewed_payload["review_mode"] = "SKIP"
        reviewed_payload["reviewed_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )

        sandbox.publish(
            artifact="aipam.findings.reviewed",
            filename="findings_reviewed.json",
            obj=reviewed_payload,
            schema="json",
        )

        # §1 Audit Integrity: log review decision
        ledger.log_event(
            project_id=project_id, pipeline_id=pipeline_id,
            link_id="hitl.findings_review", run_id=run_id,
            step_id="findings_reviewed", status="OK",
            inputs={"total_findings": len(reviewed)},
            outputs={"mode": "SKIP", "confirmed": len(reviewed)},
            metrics={}, errors={},
        )

        return {
            "status": "SUCCEEDED",
            "metrics": {"mode": "SKIP", "confirmed": len(reviewed)},
        }

    # ── AUTO mode ─────────────────────────────────────────────────────
    if mode == "AUTO":
        reviewed = []
        auto_confirmed = 0
        flagged = 0
        for f in findings:
            finding = dict(f)
            conf = f.get("confidence_score", 0)
            needs_review = f.get("requires_review", False)

            if not needs_review and conf >= auto_threshold:
                finding["analyst_status"] = "confirmed"
                finding["analyst_notes"] = f"Auto-confirmed: confidence {conf} >= {auto_threshold}"
                auto_confirmed += 1
            else:
                finding["analyst_status"] = "unverified"
                finding["analyst_notes"] = "Below auto threshold or flagged by guardrail"
                flagged += 1
            reviewed.append(finding)

        reviewed_payload = dict(findings_data)
        reviewed_payload["findings"] = reviewed
        reviewed_payload["review_mode"] = "AUTO"
        reviewed_payload["reviewed_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )

        sandbox.publish(
            artifact="aipam.findings.reviewed",
            filename="findings_reviewed.json",
            obj=reviewed_payload,
            schema="json",
        )

        print(f"  AUTO: {auto_confirmed} confirmed, {flagged} need manual review")

        # §1 Audit Integrity: log review decision
        ledger.log_event(
            project_id=project_id, pipeline_id=pipeline_id,
            link_id="hitl.findings_review", run_id=run_id,
            step_id="findings_reviewed", status="OK",
            inputs={"total_findings": len(findings)},
            outputs={"mode": "AUTO", "auto_confirmed": auto_confirmed, "needs_manual": flagged},
            metrics={"auto_threshold": auto_threshold}, errors={},
        )

        return {
            "status": "SUCCEEDED",
            "metrics": {
                "mode": "AUTO",
                "auto_confirmed": auto_confirmed,
                "needs_manual": flagged,
            },
        }

    # ── BLOCKED mode ──────────────────────────────────────────────────
    # NOTE §4: This writes to inputs/ which is the HITL control-plane
    # drop zone, not an output artifact. This is a documented exception
    # to sandbox compliance — the analyst must edit this file in-place.
    review_path = project_root / "inputs" / "hitl_findings_review.json"

    if not review_path.exists():
        # Generate template for analyst
        template = _generate_review_template(findings_data, bundle_sha)

        review_path.parent.mkdir(parents=True, exist_ok=True)
        with open(review_path, "w") as fh:
            json.dump(template, fh, indent=2)

        raise FindingsBlockedError(
            f"BLOCKED: Analyst review required.\n\n"
            f"Findings: {len(findings)} total, "
            f"{sum(1 for f in findings if f.get('requires_review'))} flagged\n\n"
            f"Action Required:\n"
            f"  1. Review: {review_path}\n"
            f"  2. Set analyst_status to 'confirmed' or 'false_positive' for each\n"
            f"  3. Optionally add analyst_notes\n"
            f"  4. Re-run pipeline\n\n"
            f"Template created at: {review_path}"
        )

    # Read analyst review
    with open(review_path) as fh:
        review_data = json.load(fh)

    # Stale review check
    review_bundle_sha = review_data.get("bundle_sha256", "")
    if review_bundle_sha and review_bundle_sha != bundle_sha:
        # Regenerate template
        template = _generate_review_template(findings_data, bundle_sha)
        with open(review_path, "w") as fh:
            json.dump(template, fh, indent=2)
        raise RuntimeError(
            f"STALE_REVIEW: bundle_sha256 mismatch. "
            f"Review was for {review_bundle_sha[:16]}... "
            f"but current bundle is {bundle_sha[:16]}...\n"
            f"Template regenerated at: {review_path}"
        )

    # Check if all findings have been reviewed
    review_items = review_data.get("findings_review", [])
    unreviewed = [
        r for r in review_items
        if r.get("analyst_status", "unverified") == "unverified"
    ]

    if unreviewed:
        raise FindingsBlockedError(
            f"BLOCKED: {len(unreviewed)}/{len(review_items)} findings "
            f"still unreviewed.\n"
            f"Please update: {review_path}"
        )

    # Merge verdicts
    reviewed = _merge_verdicts(findings, review_items)

    # Count outcomes
    confirmed = sum(1 for f in reviewed if f.get("analyst_status") == "confirmed")
    false_pos = sum(1 for f in reviewed if f.get("analyst_status") == "false_positive")

    # Publish reviewed findings
    reviewed_payload = dict(findings_data)
    reviewed_payload["findings"] = reviewed
    reviewed_payload["review_mode"] = "BLOCKED"
    reviewed_payload["reviewed_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
    )
    reviewed_payload["review_summary"] = {
        "confirmed": confirmed,
        "false_positive": false_pos,
        "total": len(reviewed),
    }

    sandbox.publish(
        artifact="aipam.findings.reviewed",
        filename="findings_reviewed.json",
        obj=reviewed_payload,
        schema="json",
    )

    print(f"[hitl.findings_review] ✓ {confirmed} confirmed, "
          f"{false_pos} false positives")

    # §1 Audit Integrity: log review decision
    ledger.log_event(
        project_id=project_id, pipeline_id=pipeline_id,
        link_id="hitl.findings_review", run_id=run_id,
        step_id="findings_reviewed", status="OK",
        inputs={"total_findings": len(reviewed)},
        outputs={"mode": "BLOCKED", "confirmed": confirmed, "false_positive": false_pos},
        metrics={}, errors={},
    )

    return {
        "status": "SUCCEEDED",
        "metrics": {
            "mode": "BLOCKED",
            "confirmed": confirmed,
            "false_positive": false_pos,
        },
    }
