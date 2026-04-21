# Module: test.src_write_isolation

## Purpose
Test link that attempts src/ write (used to test isolation mode blocking)

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `test.isolation_result`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `600s`
