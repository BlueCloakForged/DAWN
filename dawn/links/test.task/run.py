def run(context, config):
    outcome = config.get('outcome', 'SUCCEEDED')
    print(f'TASK: Running with outcome {outcome}...')
    if outcome == 'FAILED': return {'status': 'FAILED', 'errors': {'message': 'Forced failure'}}
    return {'status': 'SUCCEEDED'}
