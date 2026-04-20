PROJECT: projects/<project_id>/
  inputs/                      (human-provided files)
  artifacts/                   (link-owned outputs only)
  ledger/                      (append-only execution log)

            +------------------------------+
            | Link A: ingest.generic_handoff|
            |------------------------------|
REQUIRES -->|  - inputs/idea.md (or txt)   |
            | PRODUCES (artifact IDs):     |
            |  - dawn.project.descriptor   |
            |  - dawn.project.ir           |
            | Writes only to:              |
            |  artifacts/ingest.../        |
            +--------------+---------------+
                           |
                           | artifact_index entry:
                           |   dawn.project.ir -> path + sha256 + producer=Link A
                           v
            +------------------------------+
            | Link B: validate.project_handoff|
            |------------------------------|
REQUIRES -->|  - dawn.project.ir           |
            |    (must come from Link A)   |
            | VALIDATES: schema.ref -> OK? |
            | PRODUCES:                    |
            |  - dawn.handoff.report       |
            | Writes only to:              |
            |  artifacts/validate.../      |
            +------------------------------+

Key idea:
- Links NEVER “reach into” each other’s folders directly.
- They only “see” each other through the artifact index + contracts.
- The orchestrator enforces: missing inputs, ambiguous origins, schema invalid, policy violations.