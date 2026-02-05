"""
Requirement Coverage Validator

Compares requirements from SRS against implementation evidence in patchset.
Enforces policy: FAIL, GATE, or WARN on missing requirements.
"""

import json
import re
import os
from pathlib import Path


class RequirementsCoverageError(Exception):
    """Raised when requirements are missing and policy is FAIL"""
    pass


def run(context, config):
    """
    Main entry point for requirements coverage validation.
    
    1. Parse SRS → extract requirements
    2. Inspect patchset → extract implementation signals
    3. Evaluate coverage
    4. Enforce policy
    """
    project_root = Path(context["project_root"])
    policy = config.get("policy", "FAIL")
    strict = config.get("strict", True)
    
    # Load artifacts via artifact index
    artifact_index = context["artifact_index"]
    
    # Read requirements_map (preferred) or parse SRS (fallback)
    req_map_artifact = artifact_index.get("dawn.requirements_map")
    provenance_req_source = "requirements_map"
    
    if req_map_artifact:
        with open(req_map_artifact["path"], 'r') as f:
            req_data = json.load(f)
        requirements = req_data["requirements"]
    else:
        # Fallback: parse SRS directly
        provenance_req_source = "srs_fallback"
        srs_artifact = artifact_index.get("dawn.spec.srs")
        if not srs_artifact:
            raise FileNotFoundError("dawn.spec.srs artifact not found")
        
        srs_path = Path(srs_artifact["path"])
        with open(srs_path, 'r') as f:
            srs_content = f.read()
        requirements = parse_requirements_from_srs(srs_content)
    
    # Extract implementation signals
    # Prefer capabilities_manifest, fallback to patchset inspection
    signals, provenance = extract_signals(artifact_index)
    provenance["requirements_source"] = provenance_req_source
    
    # 3. Evaluate coverage
    coverage_result = evaluate_coverage(requirements, signals, provenance)
    
    # 4. Build report
    report = build_coverage_report(coverage_result, policy, provenance)
    
    # 5. Write report
    context["sandbox"].write_json("requirements_coverage_report.json", report)
    
    # 6. Enforce policy
    enforce_policy(report, policy, context, project_root)
    
    return {
        "status": "SUCCEEDED" if report["status"] == "PASSED" else "FAILED",
        "metrics": {
            "total_requirements": report["summary"]["total_requirements"],
            "covered": report["summary"]["covered"],
            "missing": report["summary"]["missing"]
        }
    }


def parse_requirements_from_srs(srs_content):
    """
    Parse SRS markdown to extract requirements.
    
    Returns list of requirement dicts with type, value, source_line.
    """
    requirements = []
    lines = srs_content.split('\n')
    
    # Extract operators
    operators = extract_operators(srs_content, lines)
    requirements.extend(operators)
    
    # Extract examples
    examples = extract_examples(srs_content, lines)
    requirements.extend(examples)
    
    # Sort for determinism
    requirements.sort(key=lambda r: (r['type'], r.get('value', ''), r.get('expr', ''), r['source_line']))
    
    return requirements


def extract_operators(content, lines):
    """Extract operator requirements from SRS"""
    operators = []
    
    # Pattern: "Support operators: +, -, *, /" or "operators?: +, -, *, /, ^"
    pattern = r'[Ss]upport (?:operators?|ops?):\s*([+\-*/^,\s()]+)'
    
    for i, line in enumerate(lines, 1):
        match = re.search(pattern, line)
        if match:
            ops_str = match.group(1)
            # Extract individual operators
            for op in re.findall(r'[+\-*/^]', ops_str):
                operators.append({
                    "id": f"REQ_OP_{op}",
                    "type": "operator",
                    "value": op,
                    "source_line": i
                })
    
    # Dedupe operators (same operator on multiple lines)
    seen = set()
    unique_ops = []
    for op in operators:
        key = op['value']
        if key not in seen:
            seen.add(key)
            unique_ops.append(op)
    
    return unique_ops


def extract_examples(content, lines):
    """Extract example requirements from Success Criteria"""
    examples = []
    
    # Pattern: `calc "2+2"` prints `4` or similar
    # Also handle: - `calc "2^8"` prints `256`
    pattern = r'`calc\s+"([^"]+)"`\s+(?:prints?|→|==)\s+`?(\d+)`?'
    
    for i, line in enumerate(lines, 1):
        for match in re.finditer(pattern, line):
            expr = match.group(1)
            expected = match.group(2)
            examples.append({
                "id": f"REQ_EX_{expr.replace(' ', '')}",
                "type": "example",
                "expr": expr,
                "expected": expected,
                "source_line": i
            })
    
    return examples


def extract_signals(artifact_index):
    """
    Extract implementation signals.
    Strategy:
    1. Use capabilities_manifest for operators (if present)
    2. Always check patchset for examples (test presence)
    
    Returns: (signals dict, provenance dict)
    """
    signals = {}
    provenance = {
        "requirements_source": None,
        "capabilities_source": None,
        "used_fallback": False
    }
    
    manifest_artifact = artifact_index.get("dawn.capabilities_manifest")
    patchset_artifact = artifact_index.get("dawn.patchset")
    
    # Get operator signals from manifest (preferred) or patchset
    if manifest_artifact:
        with open(manifest_artifact["path"], 'r') as f:
            manifest = json.load(f)
        capabilities = manifest.get("capabilities", {})
        for op in capabilities.get("operators_supported", []):
            signals[f"op_{op}"] = {
                "evidence": f"declared in capabilities_manifest",
                "source_artifact_id": "dawn.capabilities_manifest",
                "source_path": str(manifest_artifact["path"]),
                "evidence_detail": f"capabilities.operators_supported contains '{op}'"
            }
        provenance["capabilities_source"] = "capabilities_manifest"
    else:
        provenance["capabilities_source"] = "patchset_fallback"
        provenance["used_fallback"] = True
    
    # Always check patchset for test examples (even if manifest exists)
    if patchset_artifact:
        with open(patchset_artifact["path"], 'r') as f:
            patchset = json.load(f)
        
        # Look for examples in test files
        for filename, file_info in patchset.items():
            if 'test' in filename.lower():
                content = file_info.get('content', '')
                # Pattern: evaluate("2+2"), evaluate("2^8"), etc.
                for match in re.finditer(r'evaluate\s*\(\s*["\']([^"\']+)["\']\s*\)', content):
                    test_expr = match.group(1)
                    signals[f"ex_{test_expr}"] = {
                        "evidence": f"found in {filename}",
                        "source_artifact_id": "dawn.patchset",
                        "source_path": str(patchset_artifact["path"]),
                        "evidence_detail": f"test file {filename} contains evaluate(\"{test_expr}\")"
                    }
    
    return signals, provenance


def extract_from_manifest(manifest):
    """Extract signals from capabilities manifest"""
    signals = {}
    
    capabilities = manifest.get("capabilities", {})
    
    # Map operators
    for op in capabilities.get("operators_supported", []):
        signals[f"op_{op}"] = f"declared in capabilities_manifest"
    
    return signals


def extract_from_patchset_inspection(patchset):
    """
    Inspect patchset to find implementation evidence.
    
    Returns dict mapping requirement keys to evidence strings.
    """
    signals = {}
    
    # Check for operators in parser files
    for filename, file_info in patchset.items():
        content = file_info.get('content', '')
        
        # Look for operators in parser code
        if 'parser' in filename.lower():
            for op in ['+', '-', '*', '/', '^']:
                # Look for operator in code (as string literal or in logic)
                if f"'{op}'" in content or f'"{op}"' in content or f'["{op}"]' in content or f"['{op}']" in content:
                    signals[f"op_{op}"] = f"found in {filename}"
        
        # Look for examples in test files
        if 'test' in filename.lower():
            # Extract test expressions
            # Pattern: evaluate("2+2"), evaluate("2^8"), etc.
            for match in re.finditer(r'evaluate\s*\(\s*["\']([^"\']+)["\']\s*\)', content):
                test_expr = match.group(1)
                signals[f"ex_{test_expr}"] = f"found in {filename}"
    
    return signals


def evaluate_coverage(requirements, signals, provenance):
    """
    Compare requirements against signals to determine coverage.
    
    Returns dict with covered, missing, and unknown lists.
    """
    covered = []
    missing = []
    
    for req in requirements:
        if req['type'] == 'operator':
            signal_key = f"op_{req['value']}"
            signal_data = signals.get(signal_key)
            
            if signal_data:
                covered.append({
                    "requirement": req,
                    "evidence": signal_data["evidence"],
                    "evidence_source_artifact_id": signal_data["source_artifact_id"],
                    "evidence_source_path": signal_data["source_path"],
                    "evidence_detail": signal_data["evidence_detail"]
                })
            else:
                missing.append({
                    "requirement": req,
                    "expected_evidence": [
                        f"operator '{req['value']}' in capabilities_manifest.operators_supported",
                        f"operator '{req['value']}' handled in parser code"
                    ]
                })
        
        elif req['type'] == 'example':
            signal_key = f"ex_{req['expr']}"
            signal_data = signals.get(signal_key)
            
            if signal_data:
                covered.append({
                    "requirement": req,
                    "evidence": signal_data["evidence"],
                    "evidence_source_artifact_id": signal_data["source_artifact_id"],
                    "evidence_source_path": signal_data["source_path"],
                    "evidence_detail": signal_data["evidence_detail"]
                })
            else:
                missing.append({
                    "requirement": req,
                    "expected_evidence": [
                        f"test case: evaluate(\"{req['expr']}\") == {req['expected']} in patchset tests"
                    ]
                })
    
    return {
        "total": len(requirements),
        "covered": covered,
        "missing": missing
    }


def build_coverage_report(coverage_result, policy, provenance):
    """Build the coverage report JSON with provenance"""
    status = "PASSED" if len(coverage_result["missing"]) == 0 else "FAILED"
    
    # Determine requirements source
    req_source = "requirements_map" if provenance.get("requirements_source") != "srs_fallback" else "srs_fallback"
    
    return {
        "schema_version": "1.0.0",
        "policy": policy,
        "status": status,
        "mode": {
            "requirements_source": req_source,
            "capabilities_source": provenance.get("capabilities_source", "unknown"),
            "used_fallback": provenance.get("used_fallback", False)
        },
        "summary": {
            "total_requirements": coverage_result["total"],
            "covered": len(coverage_result["covered"]),
            "missing": len(coverage_result["missing"]),
            "unknown": 0
        },
        "covered": coverage_result["covered"],
        "missing": coverage_result["missing"],
        "unknown": []
    }


def enforce_policy(report, policy, context, project_root):
    """
    Enforce the configured policy based on coverage report.
    
    FAIL: Raise error if missing requirements
    GATE: Create approval template and block
    WARN: Log warnings and continue
    """
    if report["status"] == "PASSED":
        return  # All good
    
    missing_count = report["summary"]["missing"]
    
    if policy == "FAIL":
        # Raise error to fail the link
        raise RequirementsCoverageError(
            f"Requirements coverage validation failed: {missing_count} requirements not implemented. "
            f"See requirements_coverage_report.json for details."
        )
    
    elif policy == "GATE":
        # Create gate approval template
        gate_path = project_root / "inputs" / "requirements_coverage_approval.json"
        gate_data = {
            "gate": "requirements_coverage",
            "project_id": context.get("project_id", "unknown"),
            "missing_requirements": missing_count,
            "approved": False,
            "comment": "",
            "approved_at": None,
            "approved_by": None
        }
        
        with open(gate_path, 'w') as f:
            json.dump(gate_data, f, indent=2)
        
        raise RequirementsCoverageError(
            f"Requirements coverage gate activated: {missing_count} requirements missing. "
            f"Review requirements_coverage_report.json and approve via {gate_path}"
        )
    
    elif policy == "WARN":
        # Just log warning
        print(f"WARNING: Requirements coverage validation found {missing_count} missing requirements")
        # Continue execution
    
    else:
        raise ValueError(f"Unknown policy: {policy}")
