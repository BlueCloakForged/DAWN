"""Executes the test.branch step in the DAWN pipeline."""
def run(context, config):
    """Run."""
    params = config.get("config", config)
    score = params.get("score", 0.5)
    artifact_id = params.get("artifact", "test.branch_result")
    
    print(f"test.branch: Publishing {artifact_id} with score {score}")
    context["sandbox"].publish(artifact_id, f"{artifact_id}.json", {"score": score})
    return {"status": "SUCCEEDED"}
