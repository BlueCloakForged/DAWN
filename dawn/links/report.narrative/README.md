# Module: report.narrative

## Purpose
Forensic Narrative Builder (Chat Bridge). Synthesizes Level 1/2/3 findings into a conversational forensic story using the Generalist Model. Produces aipam.forensic.narrative in Markdown format.

## Dependencies (Requires)
- `aipam.flow.ir`
- `aipam.findings.ir`
- `aipam.malware.ir`
- `dawn.project.bundle`

## Produces
- `aipam.forensic.narrative`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Required input artifact not found | Returns `FAILED` with missing-artifact error | Verify upstream link ran and produced the artifact |

## Runtime
- **Timeout:** `600s`
