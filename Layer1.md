# Layer 1: Spec-Driven Development (SDD)
## Implementation Instructions
Do not generate code until a formal specification is established and understood.

### 1. The Specification Phase
Before coding, the Agent must generate:
- **Requirements:** High-level business logic.
- **Task List:** Granular technical steps to achieve the requirements.
- **Constraints:** Explicit "do-not-do" parameters.

### 2. The Spec-to-Eval Pipeline
- The written Spec serves as the primary source for the **Evaluation (Eval) Layer**.
- The Agent should generate a test suite based on the Spec *before* the functional code is written.
- Success is defined as the code passing the tests derived directly from the Spec.

### 3. Human Accountability
A human must sign off on the **Spec**, not just the code. If you cannot explain the Spec, you cannot ship the code.