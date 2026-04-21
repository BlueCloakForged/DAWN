# Module: package.evidence_pack

## Purpose
Executes the `package.evidence_pack` step in the DAWN pipeline.

## Dependencies (Requires)
- `dawn.project.descriptor`
- `dawn.project.ir`
- `package.project_bundle.zip`
- `dawn.src.diff`
- `dawn.project.report`

## Produces
- `dawn.evidence.pack`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
