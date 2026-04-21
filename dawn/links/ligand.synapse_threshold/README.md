# Module: ligand.synapse_threshold

## Purpose
Executes the `ligand.synapse_threshold` step in the DAWN pipeline.

## Dependencies (Requires)
- `ligand.pool.snapshot.json`

## Produces
- `ligand.gate_open`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
