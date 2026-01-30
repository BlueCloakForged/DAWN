# DAWN: Deterministic Auditable Workflow Network

DAWN is a pipeline orchestration framework designed for **deterministic execution**, **comprehensive auditability**, and **contract-based artifact management**.

It treats your software development lifecycle as a secure supply chain, ensuring that every step (Link) only runs when its strict requirements are met and its inputs match the expected cryptographic signatures.

## Key Features

- **Deterministic Execution**: Identical inputs always produce identical outputs. "It works on my machine" is solved by design.
- **Stale-Safe Gating**: Human approvals are cryptographically bound to specific input states. If a file changes after approval, the approval is automatically revoked.
- **Contract-Driven**: Every step declares explicit `requires` and `produces` contracts, ensuring integrity across the pipeline.
- **Audit Ledger**: Every event is logged to an immutable ledger for compliance and debugging.

## Getting Started

### Prerequisites

- Python 3.8+
- `pip`

### Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/yourusername/DAWN.git
    cd DAWN
    ```

2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

### Running a Pipeline

DAWN comes with a `web_calc_final` example project to demonstrate its capabilities.

1.  **View the Pipeline**:
    Check `web_calc_final/pipeline.yaml` to see how the workflow is defined.

2.  **Run the Orchestrator**:
    ```bash
    python3 scripts/run_pipeline.py web_calc_final
    ```

3.  **Inspect Artifacts**:
    Navigate to `web_calc_final/artifacts` to see the generated outputs.

## Architecture

DAWN is built around the concept of **Links**. A Link is an isolated unit of work that reads from artifacts and produces new artifacts.

- **Links**: `dawn/links/` (e.g., `ingest.project_bundle`, `validate.json_artifacts`)
- **Pipelines**: `dawn/pipelines/` (YAML definitions of workflows)
- **Runtime**: `dawn/runtime/` (The engine that executes the links)

## Documentation

- [Logical Links](logicallinks.md): Detailed explanation of the link concept.
- [Technical Paper](docs/TECHNICAL_PAPER.md): Deep dive into the system's design and verification.

## License

[MIT License](LICENSE)
