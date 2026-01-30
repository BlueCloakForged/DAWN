# Getting Started with DAWN

This guide will walk you through setting up DAWN, understanding its core concepts, and running your first pipeline.

## 1. Installation

DAWN is designed to be lightweight.

1.  **Clone the Repository**:
    ```bash
    git clone https://github.com/your-username/DAWN.git
    cd DAWN
    ```

2.  **Install Dependencies**:
    Create a virtual environment (recommended) and install the requirements.
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

## 2. Your First Project

DAWN organizes work into **Projects**. A project contains:
- `inputs/`: Source files (code, docs, etc.)
- `artifacts/`: Generated outputs (intermediate JSON, reports)
- `pipeline.yaml`: The workflow definition

### Create a Hello World Project

1.  Create the project directory:
    ```bash
    mkdir -p projects/hello-world/inputs
    ```

2.  Add a simple input file:
    ```bash
    echo "Hello DAWN" > projects/hello-world/inputs/message.txt
    ```

3.  Define a pipeline (`projects/hello-world/pipeline.yaml`):
    ```yaml
    apiVersion: dawn.pipelines/v1
    kind: Pipeline
    metadata:
      name: hello-world
      description: "A simple hello world pipeline"
    links:
      - id: ingest.project_bundle
      - id: validate.json_artifacts
    ```

4.  Run the pipeline:
    ```bash
    python3 scripts/run_pipeline.py hello-world
    ```

## 3. Understanding the Output

DAWN will execute the links in order.

1.  **Ingest Project Bundle**: Reads your `inputs/`, calculates SHA256 hashes, and creates a `dawn.project.bundle` artifact.
2.  **Validate JSON Artifacts**: Checks that the bundle is valid JSON.

Check `projects/hello-world/artifacts/ingest.project_bundle/dawn.project.bundle.json` to see the result. Notice how it cataloged your input file with a cryptographic hash.

## 4. Next Steps

- Explore `dawn/links/` to see available links.
- Read `docs/TECHNICAL_PAPER.md` for a deep dive into the architecture.
