"""Executes the test.task step in the DAWN pipeline."""
def run(context, config):
    """Run."""
    outcome = config.get('outcome', 'SUCCEEDED')
    print(f'TASK: Running with outcome {outcome}...')
    if outcome == 'FAILED': return {'status': 'FAILED', 'errors': {'message': 'Forced failure'}}
    return {'status': 'SUCCEEDED'}
