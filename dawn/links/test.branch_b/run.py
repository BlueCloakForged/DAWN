def run(context, config):
    params = config.get("config", config)
    score = params.get("score", 0.5)
    print(f"test.branch_b: Publishing branch_b with score {score}")
    context["sandbox"].publish("branch_b", "branch_b.json", {"score": score})
    return {"status": "SUCCEEDED"}
