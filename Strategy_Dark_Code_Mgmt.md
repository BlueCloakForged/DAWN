# Strategy: Managing "Dark Code"
## The Problem
"Dark Code" is AI-generated code that passes tests and ships but is not understood by any human in the organization. This creates organizational liability, regulatory exposure, and engineering fragility.

## The Goal
To move at AI-speed while maintaining human accountability. We transition from "Authorship" (writing every line) to "Comprehension" (owning the logic and implications).

## Core Principles
1. **Speed requires new safeguards:** Traditional human-mediated touchpoints break at AI volumes.
2. **Observability != Comprehension:** Telemetry tells you *that* it broke; comprehension tells you *why* it exists.
3. **The Flywheel:** Use specs to drive evals, and use comprehension gates to improve future specs.