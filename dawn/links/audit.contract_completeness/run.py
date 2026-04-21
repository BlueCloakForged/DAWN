"""
audit.contract_completeness — Link Contract Completeness Auditor

PURPOSE:
    Scans every link.yaml in dawn/links/ and checks whether the contract
    contains the semantic fields that Layer 2 (Self-Describing Systems)
    requires: description, failure_modes, retry semantics, and runtime
    configuration.

DEPENDENCIES:
    - Access to dawn/links/ directory (resolved relative to this file)
    - Python stdlib only (pathlib, json, re)

DEPENDENTS:
    - audit.dark_code_report pipeline
    - CI gates enforcing contract standards

FAILURE MODES:
    - If dawn/links/ is missing, returns FAILED.
    - Malformed YAML is flagged per-link (scanning continues).
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional


# ---------------------------------------------------------------------------
# Required fields per Layer 2 specification
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = {
    "description": "Spec must include a human-readable description",
    "failure_modes": "Spec should document how the link can fail",
}

RECOMMENDED_FIELDS = {
    "runtime.timeoutSeconds": "Spec should set an explicit timeout",
    "runtime.retries": "Spec should declare retry policy (even if 0)",
}


def _parse_yaml_simple(content: str) -> Dict[str, Any]:
    """
    Minimal YAML parser for link.yaml files.
    Extracts key fields without requiring pyyaml dependency.
    Handles the subset of YAML used in DAWN link contracts.
    """
    result = {
        "name": None,
        "description": None,
        "has_requires": False,
        "has_produces": False,
        "has_failure_modes": False,
        "has_timeout": False,
        "has_retries": False,
        "has_steps": False,
        "raw_lines": len(content.splitlines()),
    }

    for line in content.splitlines():
        stripped = line.strip()

        # Name
        if stripped.startswith("name:"):
            result["name"] = stripped.split(":", 1)[1].strip().strip('"').strip("'")

        # Description
        if stripped.startswith("description:"):
            desc = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            if desc and desc != ">":
                result["description"] = desc

        # Section presence detection
        if stripped.startswith("requires:"):
            val = stripped.split(":", 1)[1].strip()
            result["has_requires"] = val != "[]"
        if stripped.startswith("produces:"):
            result["has_produces"] = True
        if stripped.startswith("failure_modes:"):
            result["has_failure_modes"] = True
        if stripped.startswith("timeoutSeconds:"):
            result["has_timeout"] = True
        if stripped.startswith("retries:"):
            result["has_retries"] = True
        if stripped.startswith("steps:"):
            result["has_steps"] = True

    # Handle multi-line descriptions (YAML block scalar)
    if result["description"] is None:
        # Check for block scalar after description:
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith("description:"):
                val = line.strip().split(":", 1)[1].strip()
                if val in (">", "|", ">-", "|-"):
                    # Collect next indented lines
                    desc_parts = []
                    for j in range(i + 1, len(lines)):
                        next_line = lines[j]
                        if next_line.strip() and not next_line[0].isspace():
                            break
                        if next_line.strip():
                            desc_parts.append(next_line.strip())
                    if desc_parts:
                        result["description"] = " ".join(desc_parts)
                break

    return result


def _score_contract(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score a link contract on completeness.
    Returns findings with severity levels.
    """
    findings = []
    score = 0

    if not parsed["description"]:
        findings.append({"field": "description", "severity": "CRITICAL",
                         "message": "Missing or empty description"})
        score += 5
    elif len(parsed["description"]) < 20:
        findings.append({"field": "description", "severity": "WARNING",
                         "message": f"Description too brief ({len(parsed['description'])} chars)"})
        score += 2

    if not parsed["has_failure_modes"]:
        findings.append({"field": "failure_modes", "severity": "HIGH",
                         "message": "No failure modes documented"})
        score += 3

    if not parsed["has_timeout"]:
        findings.append({"field": "runtime.timeoutSeconds", "severity": "MEDIUM",
                         "message": "No timeout configured"})
        score += 1

    if not parsed["has_retries"]:
        findings.append({"field": "runtime.retries", "severity": "MEDIUM",
                         "message": "No retry policy declared"})
        score += 1

    if not parsed["has_produces"]:
        findings.append({"field": "produces", "severity": "WARNING",
                         "message": "No output artifacts declared"})
        score += 1

    return {"score": score, "findings": findings}


def run(project_context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point. Scans all link.yaml files and produces a completeness report.
    """
    artifact_store = project_context["artifact_store"]

    dawn_root = Path(__file__).resolve().parent.parent.parent
    links_dir = dawn_root / "links"

    if not links_dir.exists():
        return {
            "status": "FAILED",
            "error": f"Links directory not found at {links_dir}",
        }

    results = []
    total_score = 0

    for link_dir in sorted(links_dir.iterdir()):
        if not link_dir.is_dir() or link_dir.name.startswith(("_", ".")):
            continue

        link_yaml = link_dir / "link.yaml"
        if not link_yaml.exists():
            results.append({
                "name": link_dir.name,
                "status": "MISSING_CONTRACT",
                "score": 10,
                "findings": [{"field": "link.yaml", "severity": "CRITICAL",
                              "message": "No link.yaml contract file found"}],
            })
            total_score += 10
            continue

        try:
            content = link_yaml.read_text(encoding="utf-8", errors="replace")
            parsed = _parse_yaml_simple(content)
            audit = _score_contract(parsed)
            results.append({
                "name": parsed["name"] or link_dir.name,
                "directory": link_dir.name,
                "status": "AUDITED",
                "description": parsed["description"],
                "score": audit["score"],
                "findings": audit["findings"],
                "contract_fields": {
                    "has_requires": parsed["has_requires"],
                    "has_produces": parsed["has_produces"],
                    "has_failure_modes": parsed["has_failure_modes"],
                    "has_timeout": parsed["has_timeout"],
                    "has_retries": parsed["has_retries"],
                },
            })
            total_score += audit["score"]
        except Exception as e:
            results.append({
                "name": link_dir.name,
                "status": "PARSE_ERROR",
                "score": 10,
                "findings": [{"field": "link.yaml", "severity": "CRITICAL",
                              "message": f"Failed to parse: {e}"}],
            })
            total_score += 10

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    # Summary
    total = len(results)
    complete = sum(1 for r in results if r["score"] == 0)
    critical = sum(1 for r in results if r["score"] >= 5)

    report = {
        "summary": {
            "total_links": total,
            "fully_complete": complete,
            "completeness_pct": round((complete / total * 100) if total else 0, 1),
            "critical_gaps": critical,
            "total_debt_score": total_score,
        },
        "links": results,
    }

    artifact_name = "contract_completeness_report.json"
    file_path = artifact_store.write_artifact(
        "audit.contract_completeness", artifact_name, report
    )

    print(f"\n{'='*60}")
    print(f"  CONTRACT COMPLETENESS REPORT")
    print(f"{'='*60}")
    print(f"  Total links:     {total}")
    print(f"  Fully complete:  {complete} ({report['summary']['completeness_pct']}%)")
    print(f"  Critical gaps:   {critical}")
    print(f"  Total debt:      {total_score} points")
    print(f"{'='*60}\n")

    return {
        "status": "SUCCEEDED",
        "outputs": {artifact_name: {"path": str(file_path)}},
        "metrics": {
            "total_links": total,
            "completeness_pct": report["summary"]["completeness_pct"],
            "critical_gaps": critical,
        },
    }
