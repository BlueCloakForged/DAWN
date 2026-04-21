# Module: forgescaffold.test_matrix

## Purpose
Synthesize a test matrix spanning L0-L3 for the discovered units

## Dependencies (Requires)
- `forgescaffold.system_catalog.json`
- `forgescaffold.dataflow_map.json`

## Produces
- `forgescaffold.test_matrix.yaml`
- `forgescaffold.test_harness.manifest.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `300s`
