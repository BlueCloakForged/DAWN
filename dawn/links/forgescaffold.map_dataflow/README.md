# Module: forgescaffold.map_dataflow

## Purpose
Materialize a dataflow graph from the system catalog

## Dependencies (Requires)
- `forgescaffold.system_catalog.json`

## Produces
- `forgescaffold.dataflow_map.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
