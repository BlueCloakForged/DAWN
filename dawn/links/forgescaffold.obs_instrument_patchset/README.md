# Module: forgescaffold.obs_instrument_patchset

## Purpose
Generate a deterministic observability instrumentation patchset

## Dependencies (Requires)
- `dawn.project.bundle`
- `forgescaffold.system_catalog.json`
- `forgescaffold.dataflow_map.json`
- `forgescaffold.log_envelope.schema.json`

## Produces
- `forgescaffold.instrumentation.patchset.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
