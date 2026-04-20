# 8. Open Source Components & GitHub Resources

This subsystem will integrate battle-tested open-source tools from the GitHub ecosystem to support ingestion, processing, telemetry fusion, explainability, and decision support.

These tools ensure rapid development, modularity, and compatibility with DoD experimentation workflows like Project DYNAMIS.

---

## 8.1 Data Ingestion Tools

### 📡 NetFlow / PCAP Ingestion

- **[nfdump](https://github.com/phaag/nfdump)**
  - NetFlow v5/v9/IPFIX collector and parser
  - CLI and scriptable output formats
- **[GoFlow](https://github.com/cloudflare/goflow)**
  - Go-based high-performance NetFlow/sFlow collector
  - Streams to Kafka, supports real-time fusion

### 📝 Syslog & Logs

- **[Fluent Bit](https://github.com/fluent/fluent-bit)**
  - Lightweight log shipper for edge and containerized environments
  - Ideal for METS / Target Box deployment
- **[Vector](https://github.com/vectordotdev/vector)**
  - Unified logs and metrics processor with observability focus

### 📊 Telemetry / Metrics

- **[Telegraf](https://github.com/influxdata/telegraf)**
  - Agent for collecting system metrics, CPU/mem/load telemetry
- **[OpenTelemetry Collector](https://github.com/open-telemetry/opentelemetry-collector)**
  - Vendor-neutral telemetry pipeline for metrics, logs, traces

---

## 8.2 Data Fusion & Preprocessing

- **[Apache NiFi](https://github.com/apache/nifi)**
  - Drag-and-drop data ingestion and transformation tool
  - Great for odd formats: CSV, XML, JSON, binary logs
- **[Logstash](https://github.com/elastic/logstash)**
  - Parsing and enrichment of log/event data
  - Integrates with vector stores and graph DBs

---

## 8.3 Vector & Graph Databases

- **[ChromaDB](https://github.com/chroma-core/chroma)**
  - High-performance vector DB for document or session memory
- **[Kùzu](https://github.com/kuzudb/kuzu)**
  - Lightweight, high-speed graph database ideal for ISR fusion
  - Enables context linking, entity tracing, and visual COP generation

---

## 8.4 Inference & Agent Wrappers

- **[Ollama](https://github.com/ollama/ollama)**
  - Local model runtime (GGUF, quantized LLMs like Phi-4)
  - CPU-only fallback, REST API ready
- **[LangChain](https://github.com/langchain-ai/langchain)**
  - Utility layer for LLM orchestration (used internally by SAM)
- **[LangGraph](https://github.com/langchain-ai/langgraph)** *(optional)*
  - Fault-tolerant multi-agent framework with retry paths

---

## 8.5 Explainability & Visualization

- **[Streamlit](https://github.com/streamlit/streamlit)**
  - Lightweight Python dashboard UI
  - Already used in SAM for COA display, feedback loop
- **[STIX 2.1 Libraries](https://github.com/oasis-open/cti-python-stix2)**
  - DoD-relevant alert formatting and schema compliance

---

## 8.6 Deployment & Observability

- **[Docker Compose](https://github.com/docker/compose)**
  - Use for multi-container orchestration (model, UI, logs, agents)
- **[Prometheus + Node Exporter](https://github.com/prometheus/node_exporter)**
  - System health and telemetry during live LUEs

---

## 8.7 Optional Enhancements

- **[FastAPI](https://github.com/tiangolo/fastapi)**
  - If a lightweight REST API layer is needed
- **[Redis](https://github.com/redis/redis)**
  - Optional cache layer (already supported in Mem0 backend)
