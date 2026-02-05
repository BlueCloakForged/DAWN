Software Requirements Specification (SRS)

Title: ISR/Sensor Fusion AI/ML Agent (SAM-Phi)
For: Developer Team
Purpose: Support Project DYNAMIS experimentation with an edge-deployable, explainable, real-data-aware AI agent that fuses ISR inputs, contextualizes events, and provides operator-facing decision support.
Platform: Standalone module; deployable inside METS or integrated into CDAP/CRO test infrastructure.

1. Overview / Objective

The AI/ML agent will serve as a sensor fusion and decision-support system, capable of ingesting telemetry, RF data, logs, and prototype outputs from a tactical testbed environment (e.g., METS), and generating a fused, context-rich situational picture with real-time alerts, explanations, and suggested COAs.

The system must operate:

Disconnected from cloud dependencies

With modular deployment (containerized)

With auditable reasoning trace

In a low-SWaP environment, using quantized local models (Phi-4 Q4_K_M)

2. Functional Requirements
2.1 Data Ingestion Endpoints
✅ /ingest/netflow

Accept NetFlow v5/v9 or IPFIX from CRO/log forwarders

Normalize flow records and timestamp entries

Trigger fusion processing when anomalies detected

✅ /ingest/syslog

Accept logs from Linux nodes, containers, or CDAP sensors

Parse log levels, tags, source node

Store in ChromaDB for future context

✅ /ingest/telemetry

Accept JSON-formatted metrics (CPU, disk, link health)

Store in episodic store

Trigger pre-failure predictive analytics

✅ /ingest/prototype

Accept structured outputs from prototype under test (e.g., CSV, JSON, docx)

Parse and normalize into entity/event representations

Feed into Kùzu graph context

2.2 Fusion & Reasoning Engine
✅ /fuse/context

Combine all ingested sources into an event graph (Kùzu-backed)

Extract timeline, entities, and relationships

Output COP in JSON + markdown

✅ /predict/threat

Given fused data, score nodes or flows for threat likelihood (0.0–1.0)

Use previous agent sessions for context

Output: alert object + reasoning trace

✅ /predict/COA

Suggest a course of action (isolate, escalate, ignore)

Provide confidence score

Output: COA object + NL summary + optional command payload

2.3 Explainability & Feedback
✅ /explain/:event_id

Return natural-language rationale

Include: confidence, trigger pattern, and reference to memory/history

✅ /feedback/operator

Accept binary or scalar feedback on COA (e.g., “accepted,” “too aggressive,” “missed”)

Store in SQLite + vector DB

Flag for retraining/adaptation

2.4 Health & Observability
✅ /status

Return agent health: memory usage, CPU, DB connections

Timestamped last reasoning task

✅ /metrics

Return P95 inference time, memory footprint, current token usage

Needed for LUE KPI tracking

3. System Architecture Requirements
Component	Spec
Model Runtime	Ollama, Phi-4 GGUF, Q4_K_M, CPU-only
Agent Core	SOF v2 (Planner, Reasoner, TPV, etc.)
DB Backends	SQLite (episodic), ChromaDB (vector), Kùzu (graph)
Interface Ports	11434 (LLM), 8502 (UI), 6821 (sandbox), API layer TBD
Memory Footprint	≤ 6 GB RAM
Disk Footprint	≤ 5 GB, with logs capped at 500MB per session
Latency Target	P95 ≤ 5s for full fusion → COA loop
Cold Start Time	≤ 20s on CPU-only boot (test on METS-like host)
4. Deployment Environment

Host Platform: METS node or similar x86 Linux box

Connectivity: Local-only or NAT'd; no external internet

Containerization: Docker or OCI-compliant image

Persistent Volume: Required for saving memory DBs, COA logs, feedback

5. Test & Validation Plan
LUE-style test battery includes:
Test	Description	Success Criteria
ISR Fusion Stress	Ingest 3+ sources (NetFlow, logs, prototype)	COP generated within 15s
COA Accuracy	Match against human-generated COA	≥ 80% alignment
Explainability Trace	Show step-by-step reasoning	Human-readable, < 3s render
Offline Recovery	Restarted in offline mode	Last session restored; reasoning continues
Operator Feedback Loop	Accept live corrections	Feedback updates memory store, no crash
6. Output Formats & Integration Targets
Output	Format	Use Case
Common Operational Picture (COP)	JSON + Markdown	Operator dashboards (via CDAP)
Alerts	STIX 2.1 (optional), JSON	Publish to CDAP or CRO pub/sub
COA Recommendations	JSON + NL text	Embedded in CDAP UI
Logs/Traces	SQLite, JSON, Markdown	After Action Reports (AARs)
7. Security / Operational Constraints

Must run in air-gapped SCIF

No outbound DNS or telemetry

Logs must be exportable in classified-safe format

Model weights must be auditable and version-controlled

No real-time learning without operator approval (TTRL must be toggleable)

✅ Deliverables to Developer

 Container image spec with required environment variables

 API docs for /ingest, /predict, /explain

 Preloaded test data (PCAP, syslogs, prototype dump)

 Acceptance test harness (basic REST client or AAR script)

 Deployment checklist for METS node

Would you like this as:

A markdown file for dev handoff?

A PDF/Word-formatted SRS doc?

Or dropped directly into your proposal package?

You’re building the future of ISR fusion at the edge. Let’s package it clean.