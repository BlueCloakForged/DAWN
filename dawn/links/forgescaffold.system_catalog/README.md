# Module: forgescaffold.system_catalog

## Purpose
Generate a deterministic system catalog for the project workspace

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.system_catalog.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 900` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `900s`
