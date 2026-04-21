"""Executes the logic.generate_ir_v2 step in the DAWN pipeline."""

def run(context, config):
    """Run."""
    print("Running Shadow Link (Candidate)...")
    from pathlib import Path
    blueprint = Path(context['project_root']) / 'inputs' / 'blueprint.json'
    import json
    with open(blueprint, 'r') as f: data = json.load(f)
    # V2 is identical for now - should result in parity
    context['sandbox'].publish('dawn.project.ir', 'ir_v2.json', data)
    return {"status": "SUCCEEDED"}
