# Layer 2: Self-Describing Systems (Context Engineering)
## Implementation Instructions
Every code module must include structural and semantic context to eliminate "Dark" pockets in the codebase.

### 1. Structural Context (The "Where")
Every module/service must include a `manifest.md` or header describing:
- **Purpose:** What does this specific code do?
- **Dependencies:** What does this code rely on?
- **Dependents:** What other parts of the system rely on this?

### 2. Semantic Context (The "What")
Define the "Rules of Engagement" beyond simple API shapes. Documentation must include:
- **Performance Expectations:** Expected latency/throughput.
- **Failure Modes:** How does this fail? (e.g., graceful degradation vs. hard crash).
- **Retry Semantics:** Should the caller retry?
- **Behavioral Contracts:** Specific side effects or state changes.

### 3. Agent Instructions
"When generating code, you must include inline semantic context that explains *why* a specific logic path was chosen, especially for non-obvious optimizations."