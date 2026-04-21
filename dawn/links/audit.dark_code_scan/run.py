"""
audit.dark_code_scan — Dark Code Scanner for DAWN

PURPOSE:
    Walks the DAWN source tree and scores every module on a 'comprehension risk'
    scale. A module is considered 'dark' if it lacks the documentation artifacts
    that a new engineer (or a new team) would need to understand it.

DEPENDENCIES:
    - Access to the dawn/ source directory (resolved relative to this file)
    - Python stdlib only (ast, pathlib, json)

DEPENDENTS:
    - audit.dark_code_report pipeline
    - Any CI gate that enforces documentation thresholds

FAILURE MODES:
    - If the dawn/ directory is not found, returns FAILED with a diagnostic.
    - If individual files have syntax errors, they are flagged but scanning continues.

DESIGN DECISIONS:
    - We use Python's ast module to count docstrings and function/class definitions
      rather than regex, because ast handles multiline strings and edge cases correctly.
    - Risk scoring is deliberately simple (missing docs = points) so the output is
      auditable by a human and not itself 'dark'.
"""

import ast
import json
from pathlib import Path
from typing import Dict, Any, List


# ---------------------------------------------------------------------------
# Scoring weights — each missing element adds to the risk score
# ---------------------------------------------------------------------------
WEIGHT_NO_MODULE_DOCSTRING = 3    # Module-level docstring missing
WEIGHT_NO_MANIFEST = 5            # No README.md or manifest.md in directory
WEIGHT_NO_LINK_DESCRIPTION = 2    # link.yaml has empty/missing description
WEIGHT_UNDOCUMENTED_FUNCTION = 1  # Public function without docstring
WEIGHT_LOW_COMMENT_DENSITY = 2    # Less than 5% of lines are comments


def _scan_python_file(filepath: Path) -> Dict[str, Any]:
    """
    Parse a single Python file and extract documentation metrics.

    Returns a dict with:
        - has_module_docstring: bool
        - total_functions: int
        - documented_functions: int
        - total_lines: int
        - comment_lines: int
        - syntax_error: bool (if the file couldn't be parsed)
    """
    source = filepath.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()
    total_lines = len(lines)
    comment_lines = sum(1 for line in lines if line.strip().startswith("#"))

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return {
            "has_module_docstring": False,
            "total_functions": 0,
            "documented_functions": 0,
            "total_lines": total_lines,
            "comment_lines": comment_lines,
            "syntax_error": True,
        }

    # Check module docstring
    has_module_docstring = (
        isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, (ast.Constant, ast.Str))
        if tree.body
        else False
    )

    # Count functions/methods and their docstrings
    total_functions = 0
    documented_functions = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip private/dunder methods for public API focus
            if node.name.startswith("_") and not node.name.startswith("__"):
                continue
            total_functions += 1
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, (ast.Constant, ast.Str))
            ):
                documented_functions += 1

    return {
        "has_module_docstring": has_module_docstring,
        "total_functions": total_functions,
        "documented_functions": documented_functions,
        "total_lines": total_lines,
        "comment_lines": comment_lines,
        "syntax_error": False,
    }


def _score_module(metrics: Dict[str, Any], has_manifest: bool) -> int:
    """
    Calculate a risk score for a module. Higher = more 'dark'.
    Score of 0 means fully documented.
    """
    score = 0

    if not metrics["has_module_docstring"]:
        score += WEIGHT_NO_MODULE_DOCSTRING

    if not has_manifest:
        score += WEIGHT_NO_MANIFEST

    # Undocumented functions
    undocumented = metrics["total_functions"] - metrics["documented_functions"]
    score += undocumented * WEIGHT_UNDOCUMENTED_FUNCTION

    # Comment density check
    if metrics["total_lines"] > 10:
        density = metrics["comment_lines"] / metrics["total_lines"]
        if density < 0.05:
            score += WEIGHT_LOW_COMMENT_DENSITY

    if metrics["syntax_error"]:
        score += 10  # Syntax errors are a major red flag

    return score


def _scan_link_directory(link_dir: Path) -> Dict[str, Any]:
    """
    Scan a single link directory for documentation completeness.
    Checks for: link.yaml description, README/manifest, run.py docstrings.
    """
    result = {
        "name": link_dir.name,
        "path": str(link_dir),
        "has_manifest": False,
        "has_link_yaml": False,
        "link_description": None,
        "files": {},
        "risk_score": 0,
    }

    # Check for manifest/README
    for manifest_name in ["manifest.md", "README.md", "README"]:
        if (link_dir / manifest_name).exists():
            result["has_manifest"] = True
            break

    # Check link.yaml
    link_yaml = link_dir / "link.yaml"
    if link_yaml.exists():
        result["has_link_yaml"] = True
        # Simple YAML description extraction (no pyyaml dependency)
        content = link_yaml.read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("description:"):
                desc = stripped[len("description:"):].strip().strip('"').strip("'")
                result["link_description"] = desc if desc else None
                break

    # Scan Python files
    total_score = 0
    for py_file in sorted(link_dir.glob("*.py")):
        if py_file.name.startswith(".") or py_file.name == "__init__.py":
            continue
        metrics = _scan_python_file(py_file)
        file_score = _score_module(metrics, result["has_manifest"])
        result["files"][py_file.name] = {**metrics, "risk_score": file_score}
        total_score += file_score

    # Add penalty for missing link description
    if not result["link_description"]:
        total_score += WEIGHT_NO_LINK_DESCRIPTION

    result["risk_score"] = total_score
    return result


def _scan_runtime_directory(runtime_dir: Path) -> List[Dict[str, Any]]:
    """
    Scan the dawn/runtime/ directory for documentation gaps.
    """
    results = []
    for py_file in sorted(runtime_dir.glob("*.py")):
        if py_file.name.startswith(".") or py_file.name == "__init__.py":
            continue
        metrics = _scan_python_file(py_file)
        has_manifest = (runtime_dir / "README.md").exists() or (
            runtime_dir / "manifest.md"
        ).exists()
        score = _score_module(metrics, has_manifest)
        results.append(
            {
                "name": py_file.name,
                "path": str(py_file),
                "risk_score": score,
                **metrics,
            }
        )
    return results


def _classify_risk(score: int) -> str:
    """Map numeric score to human-readable tier."""
    if score >= 10:
        return "CRITICAL"
    elif score >= 6:
        return "HIGH"
    elif score >= 3:
        return "MEDIUM"
    else:
        return "LOW"


def run(project_context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point for the dark code scanner.

    Walks dawn/links/ and dawn/runtime/, scoring each module on comprehension risk.
    Produces a JSON report ranked by risk score.
    """
    artifact_store = project_context["artifact_store"]

    # Resolve dawn/ source directory relative to this link
    dawn_root = Path(__file__).resolve().parent.parent.parent
    links_dir = dawn_root / "links"
    runtime_dir = dawn_root / "runtime"
    concord_dir = dawn_root / "concord"

    if not dawn_root.exists():
        return {
            "status": "FAILED",
            "error": f"DAWN source directory not found at {dawn_root}",
        }

    # ── Scan Links ──────────────────────────────────────────────────────
    link_results = []
    if links_dir.exists():
        for link_dir in sorted(links_dir.iterdir()):
            if link_dir.is_dir() and not link_dir.name.startswith(("_", ".")):
                link_results.append(_scan_link_directory(link_dir))

    # ── Scan Runtime ────────────────────────────────────────────────────
    runtime_results = []
    if runtime_dir.exists():
        runtime_results = _scan_runtime_directory(runtime_dir)

    # ── Scan CONCORD (baseline comparison) ──────────────────────────────
    concord_results = []
    if concord_dir.exists():
        for py_file in sorted(concord_dir.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            metrics = _scan_python_file(py_file)
            has_manifest = (concord_dir / "README.md").exists()
            score = _score_module(metrics, has_manifest)
            concord_results.append(
                {"name": py_file.name, "path": str(py_file), "risk_score": score, **metrics}
            )

    # ── Build Report ────────────────────────────────────────────────────
    # Sort everything by risk score descending
    link_results.sort(key=lambda x: x["risk_score"], reverse=True)
    runtime_results.sort(key=lambda x: x["risk_score"], reverse=True)
    concord_results.sort(key=lambda x: x["risk_score"], reverse=True)

    # Summary statistics
    total_links = len(link_results)
    dark_links = sum(1 for r in link_results if not r["has_manifest"])
    documented_links = total_links - dark_links
    avg_link_risk = (
        sum(r["risk_score"] for r in link_results) / total_links if total_links else 0
    )

    total_runtime = len(runtime_results)
    runtime_no_docstring = sum(
        1 for r in runtime_results if not r["has_module_docstring"]
    )

    report = {
        "scan_metadata": {
            "dawn_root": str(dawn_root),
            "scanner_version": "1.0.0",
        },
        "summary": {
            "total_links": total_links,
            "dark_links": dark_links,
            "documented_links": documented_links,
            "documentation_coverage_pct": round(
                (documented_links / total_links * 100) if total_links else 0, 1
            ),
            "average_link_risk_score": round(avg_link_risk, 1),
            "total_runtime_modules": total_runtime,
            "runtime_modules_without_docstring": runtime_no_docstring,
            "total_concord_modules": len(concord_results),
            "risk_distribution": {
                "CRITICAL": sum(
                    1
                    for r in link_results + runtime_results
                    if _classify_risk(r["risk_score"]) == "CRITICAL"
                ),
                "HIGH": sum(
                    1
                    for r in link_results + runtime_results
                    if _classify_risk(r["risk_score"]) == "HIGH"
                ),
                "MEDIUM": sum(
                    1
                    for r in link_results + runtime_results
                    if _classify_risk(r["risk_score"]) == "MEDIUM"
                ),
                "LOW": sum(
                    1
                    for r in link_results + runtime_results
                    if _classify_risk(r["risk_score"]) == "LOW"
                ),
            },
        },
        "tier_1_critical": [
            {
                "name": r.get("name"),
                "risk_score": r["risk_score"],
                "risk_tier": _classify_risk(r["risk_score"]),
                "path": r.get("path"),
            }
            for r in (link_results + runtime_results)
            if r["risk_score"] >= 10
        ],
        "links": [
            {
                "name": r["name"],
                "risk_score": r["risk_score"],
                "risk_tier": _classify_risk(r["risk_score"]),
                "has_manifest": r["has_manifest"],
                "has_link_yaml": r["has_link_yaml"],
                "link_description": r.get("link_description"),
            }
            for r in link_results
        ],
        "runtime": [
            {
                "name": r["name"],
                "risk_score": r["risk_score"],
                "risk_tier": _classify_risk(r["risk_score"]),
                "has_module_docstring": r["has_module_docstring"],
                "total_functions": r["total_functions"],
                "documented_functions": r["documented_functions"],
                "total_lines": r["total_lines"],
            }
            for r in runtime_results
        ],
        "concord_baseline": [
            {
                "name": r["name"],
                "risk_score": r["risk_score"],
                "risk_tier": _classify_risk(r["risk_score"]),
                "has_module_docstring": r["has_module_docstring"],
                "total_functions": r["total_functions"],
                "documented_functions": r["documented_functions"],
            }
            for r in concord_results
        ],
    }

    # Write artifact
    artifact_name = "dark_code_report.json"
    file_path = artifact_store.write_artifact(
        "audit.dark_code_scan", artifact_name, report
    )

    # Print summary to pipeline log
    print(f"\n{'='*60}")
    print(f"  DARK CODE SCAN REPORT")
    print(f"{'='*60}")
    print(f"  Links:   {dark_links}/{total_links} dark ({100 - report['summary']['documentation_coverage_pct']}%)")
    print(f"  Runtime: {runtime_no_docstring}/{total_runtime} without docstrings")
    print(f"  Risk Distribution:")
    for tier, count in report["summary"]["risk_distribution"].items():
        print(f"    {tier}: {count}")
    print(f"{'='*60}\n")

    return {
        "status": "SUCCEEDED",
        "outputs": {artifact_name: {"path": str(file_path)}},
        "metrics": {
            "total_modules_scanned": total_links + total_runtime,
            "dark_modules": dark_links + runtime_no_docstring,
            "documentation_coverage_pct": report["summary"]["documentation_coverage_pct"],
        },
    }
