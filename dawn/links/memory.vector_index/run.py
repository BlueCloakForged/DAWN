"""memory.vector_index — Forensic Memory (ChromaDB vectorization).

Vectorizes confirmed (post-HITL) findings into a global ChromaDB
instance that persists across projects.  Each confirmed finding's
rationale + evidence snippet is embedded using the L1 model and
stored with full provenance metadata.

Inputs:
    * ``aipam.findings.reviewed`` — confirmed findings only

Outputs:
    * ``aipam.memory.receipt`` — log of what was indexed
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# AIPAM import bootstrap
# ---------------------------------------------------------------------------

_AIPAM_BACKEND = os.environ.get(
    "AIPAM_BACKEND_PATH",
    str(Path(__file__).resolve().parents[3] / "AIPAM" / "backend"),
)
if _AIPAM_BACKEND not in sys.path:
    sys.path.insert(0, _AIPAM_BACKEND)


# ---------------------------------------------------------------------------
# ChromaDB Interface
# ---------------------------------------------------------------------------

def _get_chromadb_client(config: Dict[str, Any]):
    """Lazy-init a persistent ChromaDB client."""
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
    except ImportError:
        raise RuntimeError(
            "chromadb is required for memory.vector_index. "
            "Install with: pip install chromadb"
        )

    db_path = os.path.expanduser(
        config.get("chromadb_path", "~/.aipam/forensic_memory")
    )
    Path(db_path).mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=db_path)
    return client


def _get_or_create_collection(client, config: Dict[str, Any]):
    """Get or create the forensic findings collection."""
    collection_name = config.get("collection_name", "aipam_forensic_findings")
    return client.get_or_create_collection(
        name=collection_name,
        metadata={"description": "AIPAM confirmed forensic findings"},
    )


def _get_embedding(text: str, config: Dict[str, Any]) -> Optional[List[float]]:
    """Get embedding vector via Ollama /api/embeddings."""
    try:
        import httpx
    except ImportError:
        return None

    endpoint = config.get("llm_endpoint", "http://localhost:11434")
    model = config.get("model_name", "llama3.1:8b")

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{endpoint}/api/embeddings",
                json={"model": model, "prompt": text},
            )
            if resp.status_code == 200:
                body = resp.json()
                return body.get("embedding")
    except Exception as exc:
        print(f"  ⚠ Embedding failed: {exc}")
    return None


def _build_document_text(finding: Dict[str, Any]) -> str:
    """Build the text to embed from a finding."""
    parts = []

    mitre = finding.get("mitre_technique_id", "")
    if mitre:
        parts.append(f"MITRE ATT&CK: {mitre}")

    severity = finding.get("severity", "")
    if severity:
        parts.append(f"Severity: {severity}")

    classification = finding.get("classification", "")
    if classification:
        parts.append(f"Classification: {classification}")

    rationale = finding.get("rationale", finding.get("description", ""))
    if rationale:
        parts.append(f"Rationale: {rationale}")

    evidence = finding.get("raw_evidence_snippet", finding.get("evidence_snippet", ""))
    if evidence:
        parts.append(f"Evidence: {evidence}")

    hosts = finding.get("affected_hosts", [])
    if hosts:
        parts.append(f"Affected hosts: {', '.join(str(h) for h in hosts)}")

    return "\n".join(parts)


def _finding_id(finding: Dict[str, Any], job_id: str) -> str:
    """Generate a deterministic ID for deduplication."""
    content = json.dumps(finding, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{job_id}:{content}".encode()).hexdigest()[:16]
    return f"finding-{digest}"


# ---------------------------------------------------------------------------
# DAWN entry point
# ---------------------------------------------------------------------------

def run(context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    DAWN Link: memory.vector_index

    1. Load aipam.findings.reviewed (confirmed findings)
    2. For each finding, build document text
    3. Get embedding from L1 model
    4. Upsert into global ChromaDB
    5. Publish aipam.memory.receipt
    """
    project_id = context["project_id"]
    pipeline_id = context.get("pipeline_id", "aipam_forensic")
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    ledger = context["ledger"]
    run_id = context.get("run_id", str(uuid.uuid4()))

    config = link_config.get("spec", {}).get("config", {})

    print(f"[memory.vector_index] Indexing confirmed findings for {project_id}")

    start_time = time.time()

    # ── Load reviewed findings ────────────────────────────────────────
    meta = artifact_store.get("aipam.findings.reviewed")
    if not meta:
        print("  ⚠ No aipam.findings.reviewed artifact — skipping vectorization")
        receipt = {
            "project_id": project_id,
            "status": "SKIPPED",
            "reason": "No reviewed findings available",
            "indexed_count": 0,
        }
        sandbox.publish(
            artifact="aipam.memory.receipt",
            filename="memory_receipt.json",
            obj=receipt,
            schema="json",
        )
        return {"status": "SUCCEEDED", "metrics": {"indexed": 0, "skipped": True}}

    with open(meta["path"]) as fh:
        reviewed_data = json.load(fh)

    findings = reviewed_data.get("findings", [])

    # Filter to confirmed only (not flagged for review)
    confirmed = [
        f for f in findings
        if not f.get("requires_review", False)
    ]

    print(f"  Total findings: {len(findings)}, confirmed: {len(confirmed)}")

    if not confirmed:
        print("  ⚠ No confirmed findings to index")
        receipt = {
            "project_id": project_id,
            "status": "SKIPPED",
            "reason": "No confirmed findings",
            "indexed_count": 0,
        }
        sandbox.publish(
            artifact="aipam.memory.receipt",
            filename="memory_receipt.json",
            obj=receipt,
            schema="json",
        )
        return {"status": "SUCCEEDED", "metrics": {"indexed": 0, "skipped": True}}

    # ── Initialize ChromaDB ───────────────────────────────────────────
    try:
        client = _get_chromadb_client(config)
        collection = _get_or_create_collection(client, config)
    except Exception as exc:
        print(f"  ⚠ ChromaDB init failed: {exc}")
        receipt = {
            "project_id": project_id,
            "status": "FAILED",
            "reason": f"ChromaDB init failed: {exc}",
            "indexed_count": 0,
        }
        sandbox.publish(
            artifact="aipam.memory.receipt",
            filename="memory_receipt.json",
            obj=receipt,
            schema="json",
        )
        return {"status": "SUCCEEDED", "metrics": {"indexed": 0, "error": str(exc)}}

    # ── Vectorize and upsert ──────────────────────────────────────────
    batch_size = config.get("batch_size", 50)
    indexed_count = 0
    skipped_count = 0
    indexed_ids = []

    for i, finding in enumerate(confirmed):
        doc_text = _build_document_text(finding)
        doc_id = _finding_id(finding, project_id)

        # Get embedding from L1 model
        embedding = _get_embedding(doc_text, config)

        # Build metadata for ChromaDB
        doc_metadata = {
            "project_id": project_id,
            "job_id": reviewed_data.get("job_id", ""),
            "mitre_technique_id": finding.get("mitre_technique_id", ""),
            "severity": finding.get("severity", ""),
            "confidence_score": float(finding.get("confidence_score", 0)),
            "classification": finding.get("classification", ""),
            "source_bundle_sha256": reviewed_data.get("source_bundle_sha256", ""),
        }

        try:
            if embedding:
                collection.upsert(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[doc_text],
                    metadatas=[doc_metadata],
                )
            else:
                # ChromaDB default embedding (without explicit vector)
                collection.upsert(
                    ids=[doc_id],
                    documents=[doc_text],
                    metadatas=[doc_metadata],
                )
            indexed_count += 1
            indexed_ids.append(doc_id)
        except Exception as exc:
            print(f"  ⚠ Failed to index finding {i}: {exc}")
            skipped_count += 1

    duration_ms = int((time.time() - start_time) * 1000)

    print(f"  Indexed: {indexed_count}, skipped: {skipped_count}")

    # ── Publish receipt ───────────────────────────────────────────────
    receipt = {
        "project_id": project_id,
        "job_id": reviewed_data.get("job_id", ""),
        "status": "COMPLETED",
        "indexed_count": indexed_count,
        "skipped_count": skipped_count,
        "total_confirmed": len(confirmed),
        "indexed_ids": indexed_ids,
        "chromadb_path": os.path.expanduser(
            config.get("chromadb_path", "~/.aipam/forensic_memory")
        ),
        "collection_name": config.get("collection_name", "aipam_forensic_findings"),
        "duration_ms": duration_ms,
    }

    sandbox.publish(
        artifact="aipam.memory.receipt",
        filename="memory_receipt.json",
        obj=receipt,
        schema="json",
    )

    # ── Audit ─────────────────────────────────────────────────────────
    ledger.log_event(
        project_id=project_id, pipeline_id=pipeline_id,
        link_id="memory.vector_index", run_id=run_id,
        step_id="vectorization_complete", status="OK",
        inputs={"confirmed_findings": len(confirmed)},
        outputs={"indexed": indexed_count, "skipped": skipped_count},
        metrics={"duration_ms": duration_ms, "indexed": indexed_count},
        errors={},
    )

    print(f"[memory.vector_index] ✓ {indexed_count} findings indexed in {duration_ms}ms")

    return {
        "status": "SUCCEEDED",
        "metrics": {
            "duration_ms": duration_ms,
            "indexed": indexed_count,
            "skipped": skipped_count,
        },
    }
