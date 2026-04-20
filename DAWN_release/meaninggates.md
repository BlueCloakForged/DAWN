# Meaning Gates: DAWN Trust and Handoff Analysis

## A) Current State
*   **Trust Claims**: DAWN currently makes two primary technical trust claims: **Deterministic Execution** (identical inputs → identical outputs) and **Stale-Safe Gating** (approvals are cryptographically bound to a specific input state via SHA256).
*   **Handoff Map**: 
    1.  Human Intent (Raw Prose/Files) → `projects/<id>/inputs/`
    2.  `ingest.project_bundle` → creates `dawn.project.bundle` (Canonical Physical State)
    3.  `ingest.handoff` → creates `dawn.project.ir` (Canonical Intent/IR)
*   **IR Schema**: The current generic IR envelope (found in `dawn/links/ingest.handoff/run.py`) includes:
    *   `intent`: {`summary`, `goal`, `constraints`}
    *   `ir`: {`type`, `payload`}
    *   `confidence`: {`overall`, `flags`, `hitl_required`}
    *   `bundle_sha256`: (The binding key)
*   **HITL vs AUTO**: Managed by the `hitl.gate` link. 
    *   **AUTO**: Triggered if `confidence.overall >= auto_threshold` AND `len(flags) == 0`.
    *   **HITL**: Default (BLOCKED mode) or if AUTO criteria fail. Generates a physical `hitl_approval.json` template for the human to sign.
*   **Approvals & State**: Approvals are stored in `hitl_approval.json` and mirrored in the `dawn.hitl.approval` artifact. They are bound to the `bundle_sha256`. "Interpretation drift" currently slips through because the IR fields are often empty or use stubs (e.g., the `stub` parser).

## B) Trust Claim
"Every automated action is cryptographically bound to a human-verified state, ensuring zero silent drift between intent and execution."

## C) Handoff Map
The canonical representation of intent flows through these IDs:
1.  **`dawn.project.bundle`**: The "Ground Truth" of all physical files provided by the human.
2.  **`dawn.project.ir`**: The "Translation" of prose into machine-readable constraints and topologies.
3.  **`dawn.hitl.approval`**: The "Authorization" to proceed, bound to the specific Bundle SHA.

## D) Gaps / Failure Modes
1.  **Interpretation Drift**: Parsers may ignore subtle prose constraints that aren't mapped to the fixed `intent.constraints` list.
2.  **Missing "Definition of Done" (DoD)**: The current IR lacks an explicit DoD artifact, allowing agents to "finish" without proving invariant satisfaction.
3.  **Silent Contract Violation**: Downstream links (like `impl.apply_patchset`) may succeed technically while violating the high-level `goal` if the link-level contract is too loose.
4.  **Decision Rights Ambiguity**: No explicit field defining what the agent is *authorized* to change vs. what is a fixed constraint (e.g., "don't touch the auth logic").
5.  **Stub Validation**: Current `quality.gates` are essentially stubs (`pass: true`), meaning there is no "Ending Gate" ensuring the "built" result matches the "imagined" IR.

## E) Proposed Additions
1.  **Beginning Gate (`spec.requirements`)**: A new link that enforces a "Contract Proposal" from the human, requiring fields for `goals`, `non-goals`, `constraints`, and `definition_of_done` before the IR is considered "Approved for Execution".
2.  **Ending Gate (`quality.release_verifier`)**: A link that performs a "Release Audit" by comparing the final artifacts against the `dawn.project.ir` requirements and the original `dawn.project.bundle` SHA.
3.  **Artifact `dawn.project.contract`**: A schema-enforced artifact combining the IR and the Human's DoD, which serves as the "Rule of Law" for the agent.

## F) Acceptance Definition
"Done" means:
*   [ ] The output artifacts in `projects/<id>/artifacts/` pass the `quality.release_verifier`.
*   [ ] All invariants defined in the `dawn.project.contract` are cryptographically signed as "Satisfied" by a validation agent.
*   [ ] The final `dawn.project.bundle` SHA matches the original approved intent's SHA.
*   [ ] The `ledger` contains 0 unauthorized `src/` writes outside the agreed-upon scope.

## G) Implementation Notes
*   **Where**: Implement the `spec.requirements` and `quality.release_verifier` links in `dawn/links/`.
*   **Risks**: Increasing the strictness of the Beginning Gate may frustrate users if the "Reasoning Agent" is too pedantic about the input prose. 
*   **Compatibility**: These additions utilize the existing DAWN `Link` and `Artifact_Store` runtime, requiring no changes to the core orchestrator.
