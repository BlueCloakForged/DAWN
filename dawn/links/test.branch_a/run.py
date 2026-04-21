"""Executes the test.branch_a step in the DAWN pipeline."""
def run(context, config):
    """Run."""
    params = config.get("config", config)
    score = params.get("score", 0.9)
    print(f"test.branch_a: Publishing branch_a with score {score}")
    context["sandbox"].publish("branch_a", "branch_a.json", {"score": score})
    return {"status": "SUCCEEDED"}
