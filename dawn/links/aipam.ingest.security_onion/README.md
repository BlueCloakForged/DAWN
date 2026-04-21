# Module: aipam.ingest.security_onion

## Purpose
Source-agnostic Security Onion ingest link. Connects to Security Onion via API or filesystem mode, pulls PCAP/log data for the specified time range and sensors, extracts flows via Zeek/Suricata or parses existing SO Zeek logs, and produces the unified aipam.flow.ir schema.

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
