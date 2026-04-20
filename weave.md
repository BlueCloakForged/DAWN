# DAWN Agent Playbook: Weaving Links into a Pipeline-of-Pipelines

**Purpose:** This document teaches an Agent how to **compose (“weave”) DAWN links** into a coherent pipeline for any project, while staying **deterministic, auditable, and low-token**.  
**Non-goal:** The Agent should not “invent” process steps at runtime. The Agent should select and configure existing links, then execute and verify.

---

## 0) Core Mental Model

### What a Link is
A **Link** is an autonomous, deterministic unit of work that:
- declares what it **requires** and what it **produces** in `link.yaml`
- runs via fixed steps (no creative reasoning)
- emits artifacts only into its sandbox
- logs every step as ledger events (JSONL), including an `artifact_index`

### What “Weaving” means
**Weaving = choosing an ordered set of links + ensuring their contracts align.**  
You do not manually pass files around. Instead:
- links produce artifacts with **logical `artifactId`s**
- downstream links require `artifactId`s
- the orchestrator resolves `artifactId → {path, digest, producer}` via the ledger’s artifact index

---

## 1) Hard Rules for Agents (Do Not Break)

1. **Contract-first:** Never assume a file exists; rely on `spec.requires[]` and the `artifact_index`.
2. **artifactId-first:** Prefer `artifactId` dependencies; do not depend on filenames unless explicitly required.
3. **Determinism:** No open-ended planning loops. Use the link catalog and pipeline YAML.
4. **Sandbox discipline:** Links write only under:
   - `projects/<project_id>/artifacts/<link_id>/`
   - `projects/<project_id>/logs/`
5. **Evidence-driven progress:** Progress is proven by:
   - ledger events (`STARTED|SUCCEEDED|FAILED|SKIPPED`)
   - required artifacts present + schema-valid
6. **Do not “paper over” failures:** If a link fails, the Agent must:
   - read the ledger error details
   - either fix config, adjust pipeline, or stop with a clear failure report

---

## 2) Inputs the Agent Uses

### Required project inputs
- A project scope/idea (e.g., `projects/<project_id>/idea.md`) or structured descriptor if already generated.
- A selected pipeline YAML (e.g., `dawn/pipelines/default.yaml`), optionally with overrides.

### The link catalog
- All link implementations live in `dawn/links/<link_id>/`
- Each link has a `link.yaml` that defines:
  - `spec.requires[]`
  - `spec.produces[]`
  - `spec.when` or `spec.steps[].when` (depending on implementation)
  - `schema` validation metadata

---

## 3) How to Weave Links (Step-by-Step)

### Step 1 — Choose a pipeline “spine”
Start from a known pipeline (e.g., `default_app_dev`) and adapt it.
A minimal, common SDLC spine often looks like:

1) `service.catalog`  
2) `build.ci`  
3) `quality.gates`  
4) `validation.self_heal` (conditional / failure-only often)  
5) `chain.validator`

Do not add links until you can explain:
- what they require
- what they produce
- why the pipeline needs them

### Step 2 — Validate the contract graph before running
For each adjacent pair of links:
- confirm upstream produces an `artifactId` that downstream requires
- ensure schema types match (`json`, etc.)
- ensure any `from_link` constraints are compatible with the producer

**If a required artifactId is missing from upstream produces:**
- add the producing link, OR
- change downstream requirements to match the correct artifactId, OR
- remove the downstream link

### Step 3 — Decide conditional execution (`when`)
Use `when` to keep pipelines lean and deterministic.

Supported conditions:
- `always`
- `on_success(<link_id>)`
- `on_failure(<link_id>)`
- `if_artifact_exists(<artifactId>)`

Common patterns:
- Put repair/self-heal links behind `on_failure(quality.gates)` or `on_failure(build.ci)`
- Use `if_artifact_exists(artifactId)` to enable optional enrichments without breaking runs

### Step 4 — Apply overrides (minimal)
Use pipeline overrides only for:
- runtime knobs (timeouts, retries)
- enabling/disabling pattern packs
- selecting schema strictness
- selecting which invariants to enforce

Do **not** override outputs unless you are also updating downstream requirements.

### Step 5 — Run the pipeline
Run via CLI (macOS):

```bash
PYTHONPATH=. python3 -m dawn.runtime.main --project <project_id> --pipeline dawn/pipelines/<pipeline>.yaml
Or use VS Code tasks:

DAWN: Run Default Pipeline

DAWN: New Link (scaffold only; weaving still requires contract alignment)

Step 6 — Verify execution (ledger-driven)

The Agent must verify:

each link has a terminal event: SUCCEEDED, FAILED, or SKIPPED

if SUCCEEDED, required produced artifacts exist and are schema-valid

the artifact_index includes expected artifactId mappings

Use summary tool:

python3 dawn/runtime/summary.py projects/<project_id>/ledger/events.jsonl


Then inspect the last events:

tail -n 50 projects/<project_id>/ledger/events.jsonl

4) How Data Moves Between Links (No Guessing)
Artifact handoff

Upstream produces: outputs["artifactId"] = {path, digest, link_id}

Orchestrator updates artifact_index

Downstream resolves requires.artifactId from artifact_index

Schema guarantees

If schema.type: json is declared for a produced artifact, it must:

parse as valid JSON

(if configured) pass JSON Schema validation

The Agent must treat schema failure as a hard stop unless a link is explicitly optional.

5) Failure Handling Protocol (Deterministic)
If a link FAILS before execution

Typical causes:

missing required artifactId

ambiguous artifact origin (if using filenames/legacy mode)

condition evaluation error

Agent action:

Read ledger event for the failed step and error type.

Fix by one of:

add required producer link

correct requires.artifactId or add from_link

change when condition

Re-run pipeline.

If a link FAILS after execution

Typical causes:

produced artifact missing

schema invalid

invariant violated

Agent action:

Identify which output is missing/invalid from the ledger error.

Fix by one of:

adjust the link runner to emit required output

adjust link.yaml produces (ONLY if downstream does not depend on it)

adjust schema or output serialization

Re-run pipeline.

If a link is SKIPPED

Agent must confirm SKIPPED is expected by:

verifying the condition and the upstream status/artifact existence that triggered it

6) Composition Safety Rules (Avoid Drift and Ambiguity)

Prefer requires.artifactId over filenames.

If a link still uses filename requirements, either:

migrate it to artifactId, OR

specify from_link to prevent collisions

Do not allow multiple links to produce the same logical artifactId.

Keep artifactId naming consistent:

<producer_link_id>.<artifact_name>

example: service.catalog.catalog, quality.gates.report

7) Building New Links (Factory Output Quality Bar)

A newly scaffolded link is “weavable” only if:

its link.yaml declares complete requires[] and produces[]

it writes produced artifacts under its sandbox

it emits ledger events with outputs in artifact_index format

it can be placed into a pipeline without manual glue code

If any of the above are missing, the Agent must not include it in the pipeline until fixed.

8) Deliverable Format When the Agent Finishes Weaving

The Agent should output (or generate) a brief “Weave Plan”:

pipeline chosen (YAML path)

list of links in order

per-link rationale (1 line each)

key handoffs (artifactIds)

any conditions (when) used

expected outputs (artifactIds)

how to run (CLI command)

how to verify (summary + ledger inspection commands)

9) Quick Reference Commands (macOS)

Run pipeline:

PYTHONPATH=. python3 -m dawn.runtime.main --project <project_id> --pipeline dawn/pipelines/default.yaml


Verify:

python3 dawn/runtime/summary.py projects/<project_id>/ledger/events.jsonl
tail -n 50 projects/<project_id>/ledger/events.jsonl


Automated verification:

./scripts/verify.sh

10) Agent “Stop Conditions” (When to Halt)

Stop and report if:

a required artifactId cannot be produced by any available link

schema validation fails and no deterministic fix exists

invariant failures indicate the pipeline is incorrectly composed

a link violates sandbox rules (write outside allowed directories)


::contentReference[oaicite:0]{index=0}