# Module: test.sleep_long

## Purpose
Test link that sleeps for 10 seconds (used to test BUDGET_TIMEOUT)

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `test.sleep_result`
- `verification_artifact.txt`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `600s`
