"""Executes the logic.generate_ir step in the DAWN pipeline."""

def run(context, config):
    """Run."""
    print("Running Stable Link...")
    from pathlib import Path
    blueprint = Path(context['project_root']) / 'inputs' / 'blueprint.json'
    import json
    with open(blueprint, 'r') as f: data = json.load(f)
    context['sandbox'].publish('dawn.project.ir', 'ir.json', data)
    return {"status": "SUCCEEDED"}
