"""Executes the math.multiplier step in the DAWN pipeline."""
def run(context, config):
    """Run."""
    coherence = config.get('mock_coherence', 0.9)
    print(f'MATH: Multiplying (Coherence: {coherence})...')
    context['sandbox'].publish('multiplier_result', 'result.json', {'val': 42})
    return {'status': 'SUCCEEDED', 'metrics': {'coherence_score': coherence}}
