# Module: aipam.ingest.arkime

## Purpose
Source-agnostic Arkime ingest link. Queries the Arkime API using a filter expression, downloads matching session PCAPs, runs Zeek/Suricata, and produces the unified aipam.flow.ir schema.

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `aipam.flow.ir`
- `dawn.project.bundle`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 600` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |
| Transient runtime error (first attempt) | Retries up to `1` time(s) automatically | Inspect link log if all retries exhausted |

## Runtime
- **Timeout:** `600s`
- **Retries:** `1`
- **Always runs:** yes (not skipped on pipeline skip-mode)
