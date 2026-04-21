# Module: forgescaffold.write_index_checkpoint

## Purpose
Write a signed checkpoint for the evidence index

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `forgescaffold.index_checkpoint.json`
- `forgescaffold.index_checkpoint.signature.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 60` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `60s`
