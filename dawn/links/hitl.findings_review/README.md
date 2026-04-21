# Module: hitl.findings_review

## Purpose
AIPAM-specific HITL gate for per-finding analyst review. Generates a review template listing each finding; analyst marks each as confirmed or false_positive. Publishes reviewed findings.

## Dependencies (Requires)
- `aipam.findings.ir`
- `dawn.project.bundle`

## Produces
- `aipam.findings.reviewed`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 0 # human-paced` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `0 # human-paceds`
