# Module: test.large_output

## Purpose
Test link that writes a large file (used to test BUDGET_OUTPUT_LIMIT)

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `test.large_file`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `600s`
