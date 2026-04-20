"""correlate.campaign — Cross-project campaign correlation.

Scans sibling project directories for ``aipam.findings.ir`` artifacts,
builds an inverted index of ``(dest_ip, mitre_technique_id)`` → projects,
and identifies "strong links" where ≥2 cases share the same indicators.

Publishes ``aipam.campaign.correlation`` listing related case IDs,
shared indicators, and a confidence score.

Note: This link intentionally breaks DAWN's per-project isolation to
enable cross-case intelligence. It reads **only** published artifacts
from sibling projects (via ``artifact_index.json``), never raw inputs.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


def _load_sibling_findings(
    projects_dir: Path,
    own_project_id: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Scan sibling projects for aipam.findings.ir.

    Returns: {project_id: [finding_dicts]}
    """
    results: Dict[str, List[Dict[str, Any]]] = {}

    if not projects_dir.exists():
        return results

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        pid = project_dir.name
        if pid == own_project_id:
            continue  # Skip self

        # Try artifact_index.json first (canonical DAWN way)
        art_index_path = project_dir / "artifact_index.json"
        findings_path = None

        if art_index_path.exists():
            try:
                with open(art_index_path) as fh:
                    idx = json.load(fh)
                meta = idx.get("aipam.findings.ir")
                if meta:
                    candidate = Path(meta.get("path", ""))
                    if not candidate.is_absolute():
                        candidate = project_dir / candidate
                    if candidate.exists():
                        findings_path = candidate
            except (json.JSONDecodeError, OSError):
                pass

        # Fallback: look in known artifact output paths
        if findings_path is None:
            for candidate in [
                project_dir / "artifacts" / "analyze.forensic_cot" / "findings_ir.json",
                project_dir / "artifacts" / "findings_ir.json",
            ]:
                if candidate.exists():
                    findings_path = candidate
                    break

        if findings_path is None:
            continue

        try:
            with open(findings_path) as fh:
                data = json.load(fh)
            findings = data.get("findings", [])
            if findings:
                results[pid] = findings
        except (json.JSONDecodeError, OSError):
            continue

    return results


def _build_inverted_index(
    all_findings: Dict[str, List[Dict[str, Any]]],
) -> Dict[Tuple[str, str], Set[str]]:
    """
    Build inverted index: (dest_ip, mitre_technique_id) → {project_ids}
    """
    index: Dict[Tuple[str, str], Set[str]] = defaultdict(set)

    for pid, findings in all_findings.items():
        for f in findings:
            technique = f.get("mitre_technique_id", "")
            if not technique:
                continue

            # Extract dest IPs from affected_hosts or evidence
            hosts = f.get("affected_hosts", [])
            evidence = f.get("raw_evidence_snippet", "")

            for ip in hosts:
                index[(ip, technique)].add(pid)

    return index


def _extract_correlation_groups(
    inverted_index: Dict[Tuple[str, str], Set[str]],
    min_projects: int = 2,
    boost_per_link: float = 0.1,
) -> List[Dict[str, Any]]:
    """
    Extract strong links where ≥min_projects share the same indicator pair.
    """
    groups: List[Dict[str, Any]] = []
    seen_combos: Set[frozenset] = set()

    for (ip, technique), project_ids in inverted_index.items():
        if len(project_ids) < min_projects:
            continue

        combo_key = frozenset(project_ids) | {ip, technique}
        if combo_key in seen_combos:
            continue
        seen_combos.add(combo_key)

        # Confidence: base 0.6 + boost per linked project
        confidence = min(1.0, 0.6 + (len(project_ids) - 1) * boost_per_link)

        # §1 Deterministic Execution: correlation_id derived from content hash
        combo_str = f"{ip}:{technique}:{':'.join(sorted(project_ids))}"
        det_id = hashlib.sha256(combo_str.encode()).hexdigest()[:8]

        groups.append({
            "correlation_id": f"campaign-{det_id}",
            "shared_ip": ip,
            "shared_technique": technique,
            "linked_projects": sorted(project_ids),
            "project_count": len(project_ids),
            "confidence": round(confidence, 2),
            "link_type": "strong",
        })

    # Sort by confidence descending
    groups.sort(key=lambda g: g["confidence"], reverse=True)

    return groups


# ---------------------------------------------------------------------------
# DAWN entry point
# ---------------------------------------------------------------------------

def run(context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    DAWN Link: correlate.campaign

    1. Load own aipam.findings.ir
    2. Scan sibling projects for their findings
    3. Build inverted index: (dest_ip, MITRE technique) → projects
    4. Extract strong links (≥2 projects sharing same indicators)
    5. Publish aipam.campaign.correlation
    """
    project_id = context["project_id"]
    project_root = Path(context["project_root"])
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    ledger = context["ledger"]
    pipeline_id = context.get("pipeline_id", "aipam_forensic")
    run_id = context.get("run_id", "unknown")

    config = link_config.get("spec", {}).get("config", {})
    min_shared = config.get("min_shared_projects", 2)
    boost = config.get("confidence_boost_per_link", 0.1)

    projects_dir = project_root.parent  # sibling projects

    print(f"[correlate.campaign] Scanning sibling projects in {projects_dir}")

    # Load own findings
    own_meta = artifact_store.get("aipam.findings.ir")
    if not own_meta:
        raise RuntimeError("MISSING_REQUIRED_ARTIFACT: aipam.findings.ir not found")

    with open(own_meta["path"]) as fh:
        own_data = json.load(fh)

    own_findings = own_data.get("findings", [])

    # Load sibling findings
    all_findings = _load_sibling_findings(projects_dir, project_id)
    all_findings[project_id] = own_findings  # Include self

    total_projects = len(all_findings)
    total_findings = sum(len(f) for f in all_findings.values())

    print(f"  Found {total_projects} projects with {total_findings} total findings")

    # Build inverted index and extract correlations
    inverted = _build_inverted_index(all_findings)
    groups = _extract_correlation_groups(inverted, min_shared, boost)

    print(f"  Identified {len(groups)} correlation group(s)")
    for g in groups:
        print(f"    • {g['shared_ip']} + {g['shared_technique']} "
              f"→ {g['linked_projects']} (confidence={g['confidence']})")

    # Publish correlation artifact
    # §2 Provenance Binding: thread source_bundle_sha256
    bundle_meta = artifact_store.get("dawn.project.bundle")
    bundle_sha = ""
    if bundle_meta:
        try:
            with open(bundle_meta["path"]) as fh:
                bundle_sha = json.load(fh).get("bundle_sha256", "")
        except (json.JSONDecodeError, OSError):
            pass

    correlation = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_project": project_id,
        "source_bundle_sha256": bundle_sha,
        "projects_scanned": total_projects,
        "total_findings_scanned": total_findings,
        "correlation_groups": groups,
        "summary": {
            "total_groups": len(groups),
            "strong_links": len([g for g in groups if g["link_type"] == "strong"]),
            "projects_with_links": len(
                set(p for g in groups for p in g["linked_projects"])
            ),
        },
    }

    sandbox.publish(
        artifact="aipam.campaign.correlation",
        filename="campaign_correlation.json",
        obj=correlation,
        schema="json",
    )

    print(f"[correlate.campaign] ✓ Published {len(groups)} correlation groups")

    # §1 Audit Integrity: log correlation results
    ledger.log_event(
        project_id=project_id, pipeline_id=pipeline_id,
        link_id="correlate.campaign", run_id=run_id,
        step_id="correlation_complete", status="OK",
        inputs={"projects_scanned": total_projects, "findings_scanned": total_findings},
        outputs={"correlation_groups": len(groups), "source_bundle_sha256": bundle_sha},
        metrics={"strong_links": len([g for g in groups if g['link_type'] == 'strong'])},
        errors={},
    )

    return {
        "status": "SUCCEEDED",
        "metrics": {
            "projects_scanned": total_projects,
            "findings_scanned": total_findings,
            "correlation_groups": len(groups),
        },
    }
