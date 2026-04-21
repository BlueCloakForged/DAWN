# Module: ingest.t2t_handoff

## Purpose
Handoff to T2T for document ingestion and IR generation

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `dawn.project.descriptor`
- `dawn.project.ir`
- `dawn.project.export.primary`
- `dawn.project.export.workflow`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `600s`
