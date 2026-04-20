"""
Requirements Map Generator

Parses SRS to extract canonical requirements tokens.
Produces requirements_map.json as single source of truth for requirements.

This link ensures requirements parsing is decoupled from SRS generation.
"""

import json
import re
from pathlib import Path


def run(context, config):
    """
    Parse SRS to extract requirements.
    
    Reads: dawn.spec.srs (SRS markdown)
    Produces: requirements_map.json (canonical requirements)
    """
    artifact_index = context["artifact_index"]
    project_id = context.get("project_id", "unknown")
    
    # Read SRS artifact
    srs_artifact = artifact_index.get("dawn.spec.srs")
    if not srs_artifact:
        raise FileNotFoundError("dawn.spec.srs artifact not found")
    
    srs_path = Path(srs_artifact["path"])
    with open(srs_path, 'r') as f:
        srs_content = f.read()
    
    # Parse requirements from SRS
    requirements = parse_requirements_from_srs(srs_content)
    
    # Generate requirements map
    req_map = {
        "schema_version": "1.0.0",
        "project_id": project_id,
        "source_artifact": "dawn.spec.srs",
        "source_file": "srs.md",
        "requirements": requirements
    }
    
    # Write to sandbox
    context["sandbox"].write_json("requirements_map.json", req_map)
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "total_requirements": len(requirements),
            "operators": len([r for r in requirements if r["type"] == "operator"]),
            "examples": len([r for r in requirements if r["type"] == "example"])
        }
    }


def parse_requirements_from_srs(srs_content):
    """
    Parse SRS markdown to extract requirements.
    
    Returns list of requirement dicts with type, value, source_line, source_text.
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
    requirements.sort(key=lambda r: (
        r['type'], 
        r.get('value', ''), 
        r.get('expr', ''), 
        r['source_line']
    ))
    
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
                    "source_line": i,
                    "source_text": line.strip()
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
                "source_line": i,
                "source_text": line.strip()
            })
    
    return examples
