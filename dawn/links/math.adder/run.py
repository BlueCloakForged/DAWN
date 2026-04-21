"""Executes the math.adder step in the DAWN pipeline."""
def run(context, config):
    """Run."""
    print("MATH: Performing addition (Dummy Link)...")
    return {"status": "SUCCEEDED", "metrics": {"result": "4 (Simulated)"}}
