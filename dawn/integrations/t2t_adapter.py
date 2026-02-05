import sys
import os
import json
import shutil
from pathlib import Path
from dataclasses import asdict, is_dataclass
from enum import Enum

def json_serializable(obj):
    """Recursive function to make dataclasses and enums JSON serializable."""
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj):
        return {k: json_serializable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_serializable(v) for v in obj]
    return obj

def run_t2t(
    inputs_dir: str,
    output_dir: str,
    *,
    enable_vision: bool = False,
    layout_mode: str = "tiered",
    hitl_mode: str = "off"
) -> dict:
    """
    Runs T2T extraction and produces:
      - a canonical IR snapshot (project IR)
      - one or more optional exports (tool-specific)
    Writes everything into output_dir.
    Returns metadata (counts, flags, confidence if available).
    """
    T2T_PATH = "/Users/vinsoncornejo/DAWN/T2T"
    T2T_SRC = os.path.join(T2T_PATH, "src")
    
    # Setup sys.path
    if T2T_PATH not in sys.path:
        sys.path.insert(0, T2T_PATH)
    if T2T_SRC not in sys.path:
        sys.path.insert(0, T2T_SRC)
        
    # Imports inside function to ensure sys.path takes effect
    from src.parser.otp_parser import OTPParser
    from src.layout.layout_engine import LayoutEngine
    from src.exporter.cro_exporter import CROExporter
    
    # Initialize components
    # Map hitl_mode to interactive flag
    interactive = (hitl_mode == "on")
    parser = OTPParser(interactive=interactive, enable_vision=enable_vision)
    layout_engine = LayoutEngine()
    exporter = CROExporter()
    
    # Collect inputs
    input_files = []
    inputs_path = Path(inputs_dir)
    if inputs_path.exists():
        # Check for PDF, TXT, MD files
        for ext in ['*.pdf', '*.txt', '*.md']:
            input_files.extend(list(inputs_path.glob(ext)))
            input_files.extend(list(inputs_path.glob(ext.upper())))
            
    if not input_files:
        # If no files found, but directory exists, maybe it's empty or has other files
        # We'll raise an error if we can't find anything to process
        raise ValueError(f"No valid input files found in {inputs_dir}")
        
    combined_ir = None
    
    for input_file in sorted(input_files):
        print(f"[T2T Adapter] Processing: {input_file}")
        ir = parser.parse(str(input_file))
        if ir:
            if combined_ir is None:
                combined_ir = ir
            else:
                # Merge logic: append nodes, connections, groups
                combined_ir.nodes.extend(ir.nodes)
                combined_ir.connections.extend(ir.connections)
                combined_ir.groups.extend(ir.groups)
                # Workflow merge (take first if exists)
                if ir.workflow and not combined_ir.workflow:
                    combined_ir.workflow = ir.workflow
                elif ir.workflow and combined_ir.workflow:
                    combined_ir.workflow.steps.extend(ir.workflow.steps)
                    
    if combined_ir is None:
        raise ValueError("T2T Extraction failed: No IR produced from inputs")
        
    # Apply Layout
    if layout_mode == 'radial':
        combined_ir = layout_engine.apply_radial_layout(combined_ir)
    else:
        combined_ir = layout_engine.apply_tiered_layout(combined_ir)
        
    # Ensure output_dir exists
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Save Canonical IR (project_ir.json)
    ir_path = os.path.join(output_dir, "project_ir.json")
    with open(ir_path, 'w') as f:
        json.dump(json_serializable(combined_ir), f, indent=2)
        
    # 2. Export and map to canonical names
    # Primary export (T2T maps its current output to export_primary.json)
    primary_export_path = os.path.join(output_dir, "export_primary.json")
    exporter.export(combined_ir, primary_export_path)
    
    # Workflow export (optional)
    # If the combined_ir has a workflow, we also produce export_workflow.json.
    # For now, T2T's primary export includes the workflow logic, 
    # but we'll create a dedicated workflow export if logical steps exist.
    if combined_ir.workflow and combined_ir.workflow.steps:
        workflow_path = os.path.join(output_dir, "export_workflow.json")
        with open(workflow_path, 'w') as f:
            json.dump(json_serializable(combined_ir.workflow), f, indent=2)
    
    # Gather metadata for the return
    metadata = {
        "counts": {
            "nodes": len(combined_ir.nodes),
            "groups": len(combined_ir.groups),
            "connections": len(combined_ir.connections),
            "workflow_steps": len(combined_ir.workflow.steps) if combined_ir.workflow else 0
        },
        "flags": combined_ir.metadata.get("flags", []),
        "confidence": combined_ir.metadata.get("confidence", 0.8) # Heuristic default
    }
    
    return metadata
