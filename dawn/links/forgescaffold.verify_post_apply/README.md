# Module: forgescaffold.verify_post_apply

## Purpose
Run harness tests and core checks after patchset apply

## Dependencies (Requires)
- `forgescaffold.test_matrix.yaml`
- `forgescaffold.test_harness.manifest.json`

## Produces
- `forgescaffold.verification_report.json`
- `forgescaffold.test_results.manifest.json`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 900` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `900s`
