┌──────────────────────────────────────────────────────────────────────────┐
│ LINK A: ingest.generic_handoff                                            │
├──────────────────────────────────────────────────────────────────────────┤
│ Inputs (project-scoped):                                                  │
│   ./projects/<id>/inputs/*                                                │
│                                                                          │
│ Work:                                                                     │
│   - Read human files (txt/md/pdf/etc)                                     │
│   - Normalize into DAWN canonical project descriptor + IR envelope        │
│                                                                          │
│ Produces (artifactId → file path + digest in artifact_index):             │
│   dawn.project.descriptor  → artifacts/ingest.generic_handoff/            │
│                             project_descriptor.json                       │
│   dawn.project.ir          → artifacts/ingest.generic_handoff/            │
│                             project_ir.json                               │
└──────────────────────────────────────────────────────────────────────────┘
                │
                │  (ArtifactStore registers artifacts by artifactId)
                │  (Ledger logs SUCCEEDED/SKIPPED/FAILED + provenance)
                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ SHARED STATE (Project-local, deterministic)                               │
├──────────────────────────────────────────────────────────────────────────┤
│ Artifact Index (logical map):                                             │
│   artifactId → { path, digest, producer_link_id, metadata }               │
│                                                                          │
│ Ledger (events.jsonl):                                                    │
│   - link_start / link_complete                                            │
│   - invariant_results, standardized errors                                │
└──────────────────────────────────────────────────────────────────────────┘
                │
                │  Requires: artifactId (strict mode can enforce)
                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ LINK B: validate.project_handoff                                          │
├──────────────────────────────────────────────────────────────────────────┤
│ Requires:                                                                 │
│   dawn.project.descriptor                                                 │
│   dawn.project.ir                                                        │
│                                                                          │
│ Validation:                                                               │
│   - JSON structural validity                                              │
│   - schema.ref → jsonschema validation against canonical schemas          │
│   - sanity checks + invariants recorded in ledger                         │
│                                                                          │
│ Produces:                                                                 │
│   dawn.handoff.validation_report → artifacts/validate.project_handoff/    │
│                                 handoff_validation_report.json            │
└──────────────────────────────────────────────────────────────────────────┘
