# Module: aipam.ingest

## Purpose
PCAP-specific ingestion link for AIPAM forensic projects. Validates PCAP file headers (magic bytes), computes per-file SHA256 digests, and publishes a deterministic project bundle.

## Dependencies (Requires)
- *(none — runs standalone)*

## Produces
- `dawn.project.bundle`

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| Execution exceeds `timeoutSeconds: 300` | Returns `FAILED` with timeout diagnostic | Retry or increase timeout in `link.yaml` |

## Runtime
- **Timeout:** `300s`
- **Always runs:** yes (not skipped on pipeline skip-mode)
