
def run(context, config):
    print("Running Stable Link...")
    from pathlib import Path
    blueprint = Path(context['project_root']) / 'inputs' / 'blueprint.json'
    import json
    with open(blueprint, 'r') as f: data = json.load(f)
    context['sandbox'].publish('dawn.project.ir', 'ir.json', data)
    return {"status": "SUCCEEDED"}
