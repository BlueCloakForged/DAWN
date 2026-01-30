"""
Ingest Handoff Link - Domain-Agnostic Human→Machine Bridge

Converts human input bundle into machine-readable project IR.

Architecture:
  Human → dawn.project.bundle → parser → dawn.project.ir
                                       → optional exports (CRO, n8n, etc.)
  
Core Philosophy:
  - DAWN is orchestration, not domain-specific
  - Parser is pluggable (T2T, code_analyzer, doc_parser, etc.)
  - IR is domain-agnostic with embedded metadata
  - Exports are optional, domain-specific derivatives

Produces:
  - dawn.project.ir (PRIMARY - single source of truth)
  - dawn.export.cro (OPTIONAL - CRO-specific topology)
  - dawn.export.n8n (OPTIONAL - n8n workflow)

Determinism:
  - No timestamps in primary IR
  - Bundle SHA256 embedded from bundle manifest
  - Sorted keys, sorted lists
"""

import sys
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional

# Import T2T components (adjust path as needed)
T2T_PATH = Path(__file__).parent.parent.parent.parent / "T2T"
sys.path.insert(0, str(T2T_PATH))

try:
    from src.parser.otp_parser import OTPParser
    from src.layout.layout_engine import LayoutEngine
    from src.exporter.cro_exporter import CROExporter
    from src.exporter.workflow_exporter import WorkflowExporter
    T2T_AVAILABLE = True
except ImportError:
    T2T_AVAILABLE = False


def run(context, config):
    """
    Execute Human→Machine handoff with pluggable parser.
    
    Reads: dawn.project.bundle (from artifact_index)
    Produces: dawn.project.ir (primary)
    
    Supported parsers:
      - stub: Simple test parser for acceptance tests (no T2T dependency)
      - t2t: Full T2T parser (requires T2T installation)
    """
    project_root = Path(context["project_root"])
    artifact_index = context.get("artifact_index", {})
    artifact_store = context["artifact_store"]
    
    # Determine parser
    parser_id = config.get("parser", "stub")
    
    # 1. Load bundle manifest to get bundle_sha256
    artifact_store = context["artifact_store"]
    bundle_meta = artifact_store.get("dawn.project.bundle")
    if not bundle_meta:
        raise Exception("dawn.project.bundle not found - ensure ingest.project_bundle ran first")
    
    with open(bundle_meta["path"]) as f:
        bundle_manifest = json.load(f)
    
    bundle_sha256 = bundle_manifest["bundle_sha256"]
    inputs_dir = project_root / bundle_manifest["root"]
    
    # Determine parser
    parser_id = config.get("parser", "stub")
    
    # DEBUG: Log config to verify it's received
    print(f"[DEBUG ingest.handoff] parser={parser_id}, config={config}")
    
    # 2. Parse based on parser type
    if parser_id == "stub":
        # Stub parser (no T2T)
        parsed_data, confidence = parse_stub(bundle_manifest, config)
        
        # DEBUG: Log what stub parser returned
        print(f"[DEBUG stub parser] confidence={confidence}")
        
        parser_metadata = {
            "id": "stub",
            "version": "1.0.0"
        }
    elif parser_id == "t2t":
        # T2T parser
        if not T2T_AVAILABLE:
            raise ImportError(
                "T2T parser requested but modules not available.\n"
                f"Expected path: {T2T_PATH}\n"
                "Use parser: stub for tests without T2T dependency."
            )
        parsed_data, confidence = parse_t2t(inputs_dir, bundle_manifest, config)
        
        parser_metadata = {
            "id": "t2t",
            "version": "1.0.0",
            "engine": config.get("t2t_engine", "default")
        }
    else:
        raise ValueError(f"Unknown parser: {parser_id}. Use 'stub' or 't2t'")
    
    # 3. Build domain-agnostic IR
    project_ir = build_project_ir(
        bundle_sha256=bundle_sha256,
        parser_id=parser_id,
        parsed_data=parsed_data,
        confidence=confidence
    )
    
    # 4. Write primary IR
    sandbox = context["sandbox"]
    sandbox.publish(
        artifact="dawn.project.ir",
        filename="project_ir.json",
        obj=project_ir,
        schema="json"
    )
    
    # 5. Optional exports (only for t2t parser)
    exports_produced = []
    if parser_id == "t2t" and "network_ir" in parsed_data:
        exports_produced = produce_t2t_exports(
            sandbox, parsed_data["network_ir"], config
        )
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "bundle_sha256": bundle_sha256,
            "parser_id": parser_id,
            "confidence_overall": confidence["overall"],
            "hitl_required": confidence["hitl_required"],
            "exports_produced": exports_produced
        }
    }


def parse_stub(bundle_manifest: Dict, link_config: Dict) -> tuple[Dict, Dict]:
    """
    Stub parser for testing (no T2T dependency).
    
    Config overrides are AUTHORITATIVE:
    - stub_confidence: sets overall exactly
    - stub_flags: sets flags exactly (no defaults added)
    """
    files = bundle_manifest.get("files", [])
    
    # Extract file types
    file_types = set()
    total_bytes = 0
    for f in files:
        ext = Path(f["path"]).suffix
        if ext:
            file_types.add(ext)
        total_bytes += f.get("bytes", 0)
    
    # Extract config values (link_config may have nested .config)
    # Handle both direct config dict and link.yaml structure
    if "config" in link_config and isinstance(link_config["config"], dict):
        config = link_config["config"]  # Nested structure from orchestrator
    else:
        config = link_config  # Direct structure
    
    # Compute defaults (only used if config doesn't override)
    default_confidence = 0.75
    default_flags = []
    if ".pdf" not in file_types:
        default_flags.append("no_pdf_files")
    if not any(ext in [".png", ".jpg", ".svg", ".drawio"] for ext in file_types):
        default_flags.append("no_diagram_files")
    
    # Config overrides are AUTHORITATIVE
    if "stub_confidence" in config:
        confidence_overall = config["stub_confidence"]
    else:
        confidence_overall = default_confidence
    
    if "stub_flags" in config:
        flags = config["stub_flags"]  # Use exactly what's in config
    else:
        flags = default_flags
    
    # Build confidence object
    confidence = {
        "overall": confidence_overall,
        "flags": flags,
        "hitl_required": True  # Can be overridden by config too if needed
    }
    
    # Build parsed data
    parsed_data = {
        "type": "stub_parse",
        "files_analyzed": len(files),
        "file_types": sorted(list(file_types)),
        "total_bytes": total_bytes
    }
    
    return parsed_data, confidence



def parse_t2t(inputs_dir: Path, bundle_manifest: Dict, config: Dict) -> tuple[Dict, Dict]:
    """
    T2T parser - requires T2T installation.
    """
    # Find OTP PDF in bundle
    otp_path = find_otp_pdf_in_bundle(inputs_dir, bundle_manifest)
    
    # Parse using T2T
    network_ir = parse_otp(otp_path, config)
    
    # Apply layout
    layout_strategy = config.get("layout_strategy", "tiered")
    layout_engine = LayoutEngine()
    network_ir = layout_engine.apply_layout(network_ir, strategy=layout_strategy)
    
    # Compute confidence
    confidence = compute_confidence(network_ir, bundle_manifest)
    
    # Convert network_ir to dict
    ir_dict = network_ir.to_dict() if hasattr(network_ir, 'to_dict') else vars(network_ir)
    
    # Extract services
    all_services = set()
    for node in network_ir.nodes:
        for service in node.services:
            all_services.add(service.name)
    
    parsed_data = {
        "type": "network_topology",
        "network_ir": network_ir,  # Keep for exports
        "payload": {
            "name": network_ir.name or "Parsed network topology",
            "nodes": len(network_ir.nodes),
            "groups": len(network_ir.groups),
            "connections": len(network_ir.connections),
            "services": sorted(all_services),
            "details": ir_dict
        }
    }
    
    return parsed_data, confidence


def find_otp_pdf_in_bundle(inputs_dir: Path, manifest: Dict) -> Path:
    """
    Find OTP PDF from bundle manifest.
    
    Priority: files containing 'otp' in name, then any .pdf
    """
    files = manifest.get("files", [])
    pdf_files = [f for f in files if f["path"].endswith(".pdf")]
    
    if not pdf_files:
        raise FileNotFoundError(
            "No PDF files found in bundle\n"
            "Expected: OTP PDF or network diagram PDF"
        )
    
    # Prefer files with 'otp' in name
    otp_candidates = [f for f in pdf_files if "otp" in f["path"].lower()]
    chosen = otp_candidates[0] if otp_candidates else pdf_files[0]
    
    # Convert manifest path to actual file location
    # Manifest paths are like "inputs/file.pdf"
    path_parts = Path(chosen["path"]).parts
    if path_parts[0] == "inputs":
        file_rel_path = Path(*path_parts[1:])
    else:
        file_rel_path = Path(chosen["path"])
    
    return inputs_dir / file_rel_path


def parse_otp(otp_path: Path, config: Dict) -> Any:
    """Parse OTP PDF using T2T parser."""
    if not otp_path.exists():
        raise FileNotFoundError(f"OTP PDF not found: {otp_path}")
    
    parser = OTPParser()
    
    try:
        network_ir = parser.parse(str(otp_path.absolute()))
    except Exception as e:
        raise RuntimeError(
            f"T2T parsing failed for {otp_path.name}\n"
            f"Error: {e}\n"
            f"Absolute path: {otp_path.absolute()}"
        )
    
    return network_ir


def compute_confidence(network_ir: Any, manifest: Dict) -> Dict[str, Any]:
    """
    Compute confidence score and flags.
    
    Returns deterministic dict (no timestamps).
    """
    nodes = network_ir.nodes
    groups = network_ir.groups
    connections = network_ir.connections
    
    # Scoring logic (from T2T)
    nodes_with_os = sum(1 for n in nodes if n.template_hint)
    nodes_with_ip = sum(1 for n in nodes if n.interfaces)
    
    score = 0.0
    if nodes:
        score += (nodes_with_os / len(nodes)) * 0.3
        score += (nodes_with_ip / len(nodes)) * 0.2
    
    if groups:
        score += 0.2
    
    if connections:
        score += 0.15
    
    # Flags
    flags = []
    files = manifest.get("files", [])
    if not any("diagram" in f["path"].lower() for f in files):
        flags.append("no_diagram_files")
    
    if score < 0.5:
        flags.append("low_confidence")
    
    if nodes_with_os < len(nodes):
        flags.append(f"{len(nodes) - nodes_with_os}_nodes_without_os")
    
    hitl_required = score < 0.7 or len(flags) > 0
    
    return {
        "overall": round(score, 2),
        "flags": sorted(flags),  # Sorted for determinism
        "hitl_required": hitl_required
    }


def build_project_ir(
    bundle_sha256: str,
    parser_id: str,
    parsed_data: Dict,
    confidence: Dict
) -> Dict[str, Any]:
    """
    Build domain-agnostic project IR envelope.
    
    NO TIMESTAMPS - deterministic output only.
    """
    # Extract intent from parsed data
    data_type = parsed_data.get("type", "unknown")
    
    if data_type == "stub_parse":
        intent = {
            "summary": f"Stub parse of {parsed_data['files_analyzed']} files",
            "goal": "Acceptance test validation",
            "constraints": []
        }
        ir_payload = {
            "files_analyzed": parsed_data["files_analyzed"],
            "total_bytes": parsed_data["total_bytes"],
            "file_types": parsed_data["file_types"]
        }
    elif data_type == "network_topology":
        payload_data = parsed_data.get("payload", {})
        intent = {
            "summary": f"Network topology with {payload_data.get('nodes', 0)} nodes",
            "goal": "Deploy cyber range infrastructure",
            "constraints": []
        }
        ir_payload = payload_data
    else:
        intent = {
            "summary": "Parsed content",
            "goal": "Project implementation",
            "constraints": []
        }
        ir_payload = parsed_data
    
    return {
        "schema_version": "1.0.0",
        "bundle_sha256": bundle_sha256,
        "parser": {
            "id": parser_id,
            "version": "1.0.0"
        },
        "intent": intent,
        "ir": {
            "type": data_type,
            "payload": ir_payload
        },
        "confidence": confidence
    }


def produce_t2t_exports(sandbox, network_ir: Any, config: Dict) -> list[str]:
    """Produce optional T2T exports."""
    exports = []
    
    # CRO export
    if "cro" in config.get("exports", []):
        cro_exporter = CROExporter()
        cro_data = cro_exporter.export(network_ir)
        cro_envelope = {
            "schema_version": "1.0.0",
            "format": "cro",
            "exporter": "t2t",
            "payload": cro_data
        }
        sandbox.publish(
            artifact="dawn.export.cro",
            filename="export.cro.json",
            obj=cro_envelope,
            schema="json"
        )
        exports.append("cro")
    
    # n8n export
    if "n8n" in config.get("exports", []) and network_ir.workflow:
        workflow_exporter = WorkflowExporter()
        workflow_data = workflow_exporter.export(network_ir)
        n8n_envelope = {
            "schema_version": "1.0.0",
            "format": "n8n",
            "exporter": "t2t",
            "payload": workflow_data
        }
        sandbox.publish(
            artifact="dawn.export.n8n",
            filename="export.n8n.json",
            obj=n8n_envelope,
            schema="json"
        )
        exports.append("n8n")
    
    return exports


def load_artifact_json(artifact_index: Dict, artifact_id: str) -> Dict:
    """Load and parse JSON artifact from index."""
    artifact = artifact_index.get(artifact_id)
    if not artifact:
        raise FileNotFoundError(f"{artifact_id} not found in artifact index")
    
    artifact_path = Path(artifact["path"])
    if not artifact_path.exists():
        raise FileNotFoundError(f"{artifact_id} file not found: {artifact_path}")
    
    with open(artifact_path, 'r') as f:
        return json.load(f)
