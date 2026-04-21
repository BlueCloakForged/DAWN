"""Executes the ligand.suppressor step in the DAWN pipeline."""
import json
from pathlib import Path

def run(context, config):
    """
    Competitive Suppression Link (Lateral Inhibition).
    Compares a metric across branches and issues "Soft Kill" commands.
    """
    print("LIGAND: Running Suppressor (Lateral Inhibition)...")
    
    # Config parameters
    # comparison_set: List of artifact IDs to compare
    # metric_field: Field name to compare (e.g. 'coherence_score')
    # focus_threshold: Margin required to inhibit (influenced by LIGAND focus)
    
    # LIGAND: Extract params from link_config["config"] if present, else top-level
    link_params = config.get("config", config)
    
    comparison_set = link_params.get("comparison_set", [])
    metric_field = link_params.get("metric_field", "coherence_score")
    
    # Get LIGAND focus level from pool snapshot
    pool_path = Path(context['project_root']) / 'artifacts' / 'meta.bundle' / 'ligand.pool.snapshot.json'
    focus = 1.0
    if pool_path.exists():
        with open(pool_path, "r") as f:
            pool = json.load(f)
            focus = pool.get("vector", {}).get("focus", 1.0)
    
    print(f"LIGAND: Effective Focus: {focus:.2f}")

    results = []
    artifact_store = context["artifact_store"]

    for art_id in comparison_set:
        art_meta = artifact_store.get(art_id)
        if not art_meta:
            continue
        
        path = Path(art_meta["path"])
        if not path.exists():
            continue
            
        try:
            with open(path, "r") as f:
                data = json.load(f)
            
            score = data.get(metric_field, 0.0)
            results.append({"id": art_id, "score": score, "link_id": art_meta.get("producer_link_id")})
        except Exception:
            pass

    if not results:
        print("LIGAND: No sufficient data to compare for suppression.")
        return {"status": "SUCCEEDED"}

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    winner = results[0]
    print(f"LIGAND: Winner is {winner['link_id']} with score {winner['score']:.3f}")

    # Inhibit others if they are significantly weaker (modulated by focus)
    # The higher the focus, the more aggressive the inhibition.
    inhibition_threshold = winner["score"] * (1.0 - (0.5 * focus)) # Example heuristic

    inhibited_count = 0
    for res in results[1:]:
        if res["score"] < inhibition_threshold:
            print(f"LIGAND: Inhibiting {res['link_id']} (score {res['score']:.3f} < {inhibition_threshold:.3f})")
            # Note: In a real multi-branch system, we would target this specific link's context.
            # In our current orchestrator, we publish a global inhibition artifact for this project.
            # Project-level inhibition stops all subsequent links.
            context["sandbox"].publish("ligand.inhibition", "inhibition_signal.json", {
                "source": "ligand.suppressor",
                "target_link_id": res["link_id"],
                "reason": "competitive_suppression",
                "score_delta": winner["score"] - res["score"]
            })
            inhibited_count += 1

    return {"status": "SUCCEEDED", "metrics": {"inhibited_branches": inhibited_count}}
